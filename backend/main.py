# backend/main.py
from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from landrag import vectorstore, add_document, list_documents, query_rag
from simple_agent import run_compliance_query, search_web_only, run_admin_analysis
from supabase import create_client, Client
from datetime import datetime
import os
import time
import httpx
import asyncio
from typing import List, Dict
from dotenv import load_dotenv
import uuid
from contextlib import asynccontextmanager
from document_worker import start_worker, stop_worker

load_dotenv()

async def resolve_redirect_url(url: str) -> str:
    """Resolve Google redirect URL to actual destination (async)"""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.head(url, follow_redirects=True)
            return str(response.url)
    except Exception as e:
        print(f"⚠️ Could not resolve URL: {url[:80]}... Error: {e}")
        return url  # Return original if resolution fails

async def resolve_web_sources(sources: List[Dict]) -> List[Dict]:
    """Resolve all redirect URLs in web sources (async)"""
    resolved = []
    for source in sources:
        resolved_source = source.copy()
        if 'url' in resolved_source:
            original_url = resolved_source['url']
            resolved_url = await resolve_redirect_url(original_url)
            resolved_source['url'] = resolved_url
            print(f"  ✅ Resolved: {resolved_url}")
        resolved.append(resolved_source)
    return resolved


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown events"""
    # Startup: Start the document worker
    print("🚀 Starting Land Compliance RAG API...")
    await start_worker()
    yield
    # Shutdown: Stop the document worker
    print("🛑 Shutting down Land Compliance RAG API...")
    await stop_worker()


app = FastAPI(title="Land Compliance RAG API", lifespan=lifespan)

# CORS Configuration
# Add your Lovable preview URLs here
LOVABLE_ORIGINS = [
    "http://localhost:3000",  # Local development
    "http://localhost:5173",  # Vite default
    # Lovable preview URLs:
    "https://id-preview--f7f14680-8638-41fc-83c8-2dbe734ac620.lovable.app",
    "https://id-preview--55282d44-5307-482a-9200-899a67006655.lovable.app",
    # Add production URL when ready:
    # "https://your-app.lovable.app",
]

# Allow all origins in development, or specific origins in production
# Set ALLOW_ALL_ORIGINS=false in .env to restrict to LOVABLE_ORIGINS only
ALLOW_ALL_ORIGINS = os.getenv("ALLOW_ALL_ORIGINS", "true").lower() == "true"

cors_origins = ["*"] if ALLOW_ALL_ORIGINS else LOVABLE_ORIGINS

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Supabase
supabase: Client = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY")
)

async def log_query_to_supabase(request, result: dict, response_time_ms: int):
    """Log all 5 agents' outputs to Supabase"""
    try:
        # Extract URLs from web sources for the text array column
        web_source_urls = []
        for source in result.get('web_sources', []):
            if isinstance(source, dict):
                web_source_urls.append(source.get('url', ''))
            elif isinstance(source, str):
                web_source_urls.append(source)

        log_data = {
            'user_query': request.query,
            'user_id': request.user_id,
            'session_id': request.session_id,
            'timestamp': datetime.utcnow().isoformat(),
            'response_time_ms': response_time_ms,
            'input_moderation_passed': True,
            'output_moderation_passed': True,

            # Agent outputs
            'rag_only_answer': result.get('rag_only_answer', ''),
            'rag_sources': result.get('rag_sources', []),
            'agent1_confidence': result.get('rag_confidence', 'unknown'),

            'web_only_answer': result.get('web_only_answer', ''),
            'web_sources': web_source_urls,  # ← Use extracted URLs for text array
            'agent2_source_count': result.get('web_source_count', 0),

            'rag_gaps_identified': result.get('gaps_identified', []),
            'agent3_has_gaps': len(result.get('gaps_identified', [])) > 0,
            'agent3_raw_response': result.get('gap_analysis_raw', ''),
            'alert_level': result.get('alert_level', 'GREEN'),  # Add severity classification

            'agent4_recommended_urls': result.get('recommended_urls', []),
            'agent4_ran': len(result.get('recommended_urls', [])) > 0,
            'rag_update_urls': [url.get('url', '') if isinstance(url, dict) else url for url in result.get('recommended_urls', [])],

            'final_answer': result.get('answer', ''),

            # Legacy compatibility
            'agent_response': result.get('answer', ''),
            'rag_update_flag': result.get('status') == 'RAG Update Needed'
        }

        response = supabase.table('compliance_queries').insert(log_data).execute()
        query_id = response.data[0]['id']
        print(f"✅ Logged to Supabase: query_id = {query_id}")

        # Add to update queue if needed (only RED/YELLOW, not GREEN)
        alert_level = result.get('alert_level', 'GREEN')
        priority_map = {
            'RED': 'high',
            'YELLOW': 'medium',
            'GREEN': None  # Not queued
        }
        queue_priority = priority_map.get(alert_level, 'medium')
        
        if log_data['agent4_ran'] and alert_level != 'GREEN':
            for url_obj in result.get('recommended_urls', []):
                if isinstance(url_obj, dict):
                    queue_data = {
                        'source_url': url_obj.get('url', ''),
                        'source_title': url_obj.get('title', url_obj.get('reason', 'Recommended by Agent 4')),
                        'related_query_id': query_id,
                        'priority': queue_priority,  # Map from severity: RED=high, YELLOW=medium
                        'processed': False
                    }
                    supabase.table('rag_update_queue').insert(queue_data).execute()
            print(f"✅ Added {len(result.get('recommended_urls', []))} URLs to update queue with priority={queue_priority}")

        return query_id

    except Exception as e:
        print(f"❌ Logging error: {e}")
        import traceback
        traceback.print_exc()
        return None

# FIXED: Added user_id and session_id
class AgentRequest(BaseModel):
    query: str
    user_id: str = "default_user"
    session_id: str = "default_session"

class QueryRequest(BaseModel):
    question: str

@app.get("/")
async def root():
    return {"message": "Land Compliance RAG API is running"}

@app.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    """Upload a PDF document to the RAG system"""
    try:
        allowed_extensions = ['.pdf', '.txt', '.docx', '.xlsx', '.csv', '.html', '.xml']
        if not any(file.filename.endswith(ext) for ext in allowed_extensions):
            raise HTTPException(status_code=400, detail="Unsupported file type")

        content = await file.read()
        file_size_mb = len(content) / 1024 / 1024
        print(f"[DEBUG] File {file.filename}: {file_size_mb:.2f}MB")

        if len(content) > 50 * 1024 * 1024:
            return {
                "success": True,
                "message": f"File too large ({file_size_mb:.1f}MB). Maximum 50MB.",
                "chunks_processed": 0
            }

        temp_path = f"/tmp/{file.filename}"
        with open(temp_path, "wb") as buffer:
            buffer.write(content)

        result = await add_document(temp_path, file.filename)
        os.remove(temp_path)

        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/query")
async def query_documents(request: QueryRequest):
    """Query the RAG system (basic, no agent)"""
    try:
        response = await query_rag(request.question)
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/documents")
async def get_documents():
    """Get list of all uploaded documents"""
    try:
        result = list_documents()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    return {"status": "ok"}

@app.get("/admin/analysis/{query_id}")
async def get_admin_analysis(query_id: str, request: Request):
    """Get admin analysis results for a query
    
    Verifies admin status and returns analysis data including RAG comparison,
    gap analysis, and recommended URLs. Returns 'processing' status if analysis
    is still in progress.
    """
    try:
        # Get user_id from header
        user_id = request.headers.get('X-User-ID')
        if not user_id:
            raise HTTPException(status_code=401, detail="User ID required in X-User-ID header")
        
        # Verify admin status
        try:
            role_result = supabase.table('user_roles')\
                .select('role')\
                .eq('user_id', user_id)\
                .single()\
                .execute()
            
            user_role = role_result.data.get('role') if role_result.data else None
            if user_role != 'admin':
                raise HTTPException(status_code=403, detail="Admin access required")
        except Exception as e:
            # Handle case where user_roles query fails or user not found
            if isinstance(e, HTTPException):
                raise
            print(f"⚠️ Error verifying admin status: {e}")
            raise HTTPException(status_code=403, detail="Admin access required")
        
        # Fetch query from Supabase
        try:
            query_result = supabase.table('compliance_queries')\
                .select('*')\
                .eq('id', query_id)\
                .single()\
                .execute()
            
            if not query_result.data:
                raise HTTPException(status_code=404, detail="Query not found")
        except Exception as e:
            if isinstance(e, HTTPException):
                raise
            print(f"⚠️ Error fetching query: {e}")
            raise HTTPException(status_code=404, detail="Query not found")
        
        data = query_result.data
        
        # Determine status - check if RAG analysis is complete
        has_rag_answer = data.get('rag_only_answer') and len(str(data.get('rag_only_answer', '')).strip()) > 0
        status = 'complete' if has_rag_answer else 'processing'
        
        # Format web_sources - they're stored as text array (URLs only) in Supabase
        # Convert to list of objects with url/title format
        web_sources = []
        stored_web_sources = data.get('web_sources', [])
        if stored_web_sources:
            for source in stored_web_sources:
                if isinstance(source, dict):
                    # Already an object
                    web_sources.append({
                        'url': source.get('url', ''),
                        'title': source.get('title', 'Source')
                    })
                elif isinstance(source, str):
                    # Just a URL string
                    web_sources.append({
                        'url': source,
                        'title': 'Source'  # Title not stored, use generic
                    })
        
        # Format recommended_urls - stored as jsonb (list of objects)
        recommended_urls = data.get('agent4_recommended_urls', [])
        if not isinstance(recommended_urls, list):
            recommended_urls = []
        
        # Ensure each recommended URL has the expected format
        formatted_recommended_urls = []
        for url_obj in recommended_urls:
            if isinstance(url_obj, dict):
                formatted_recommended_urls.append({
                    'url': url_obj.get('url', ''),
                    'title': url_obj.get('title', url_obj.get('reason', 'Recommended source')),
                    'reason': url_obj.get('reason', '')
                })
            elif isinstance(url_obj, str):
                formatted_recommended_urls.append({
                    'url': url_obj,
                    'title': 'Recommended source',
                    'reason': ''
                })
        
        # Format gaps - stored as array
        gaps = data.get('rag_gaps_identified', [])
        if not isinstance(gaps, list):
            gaps = []
        
        # Format RAG sources - stored as array
        rag_sources = data.get('rag_sources', [])
        if not isinstance(rag_sources, list):
            rag_sources = []
        
        # Return formatted response matching Lovable prompt structure
        return {
            'status': status,
            'web_answer': data.get('web_only_answer', ''),
            'web_sources': web_sources,
            'rag_answer': data.get('rag_only_answer', ''),
            'rag_sources': rag_sources,
            'gaps': gaps,
            'agent3_raw_response': data.get('agent3_raw_response', ''),
            'alert_level': data.get('alert_level', 'GREEN'),
            'recommended_urls': formatted_recommended_urls
        }
        
    except HTTPException:
        # Re-raise HTTP exceptions (401, 403, 404)
        raise
    except Exception as e:
        print(f"❌ Error in get_admin_analysis: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

async def get_conversation_history(session_id: str, limit: int = 5) -> List[Dict]:
    """Fetch recent conversation history for a session"""
    try:
        result = supabase.table('compliance_queries') \
            .select('user_query, final_answer, timestamp') \
            .eq('session_id', session_id) \
            .order('timestamp', desc=True) \
            .limit(limit + 1) \
            .execute()
        
        # Reverse to get chronological order (oldest first), exclude the current query
        history = list(reversed(result.data[1:])) if len(result.data) > 1 else []
        return history
    except Exception as e:
        print(f"⚠️ Error fetching conversation history: {e}")
        return []

@app.get("/history")
async def get_history():
    """Fetch recent query history"""
    try:
        result = supabase.table('compliance_queries') \
            .select('id, user_query, created_at, rag_update_flag') \
            .order('created_at', desc=True) \
            .limit(50) \
            .execute()

        return {"history": result.data}
    except Exception as e:
        print(f"❌ Error fetching history: {e}")
        return {"history": []}

@app.get("/conversation/{session_id}")
async def get_conversation_with_rag(session_id: str, request: Request):
    """Fetch conversation history with RAG responses for a session
    
    Returns full conversation history including RAG answers, sources, gaps, and alert levels.
    Useful for displaying conversation history in the frontend with RAG analysis data.
    """
    try:
        # Get user_id from header (optional, but recommended for user-specific filtering)
        user_id = request.headers.get('X-User-ID')
        
        # Build query
        query = supabase.table('compliance_queries') \
            .select('id, user_query, final_answer, web_only_answer, rag_only_answer, rag_sources, web_sources, rag_gaps_identified, alert_level, agent4_recommended_urls, timestamp, created_at') \
            .eq('session_id', session_id) \
            .order('timestamp', desc=False)  # Oldest first for chronological order
        
        # Optionally filter by user_id if provided
        if user_id:
            query = query.eq('user_id', user_id)
        
        result = query.limit(100).execute()
        
        # Format the response
        formatted_history = []
        for item in result.data:
            # Format web_sources (may be text array or objects)
            web_sources = []
            stored_web_sources = item.get('web_sources', [])
            if stored_web_sources:
                for source in stored_web_sources:
                    if isinstance(source, dict):
                        web_sources.append({
                            'url': source.get('url', ''),
                            'title': source.get('title', 'Source')
                        })
                    elif isinstance(source, str):
                        web_sources.append({
                            'url': source,
                            'title': 'Source'
                        })
            
            # Format recommended URLs
            recommended_urls = item.get('agent4_recommended_urls', [])
            if not isinstance(recommended_urls, list):
                recommended_urls = []
            
            formatted_recommended = []
            for url_obj in recommended_urls:
                if isinstance(url_obj, dict):
                    formatted_recommended.append({
                        'url': url_obj.get('url', ''),
                        'title': url_obj.get('title', url_obj.get('reason', 'Recommended source')),
                        'reason': url_obj.get('reason', '')
                    })
                elif isinstance(url_obj, str):
                    formatted_recommended.append({
                        'url': url_obj,
                        'title': 'Recommended source',
                        'reason': ''
                    })
            
            formatted_history.append({
                'id': item.get('id'),
                'user_query': item.get('user_query', ''),
                'final_answer': item.get('final_answer', ''),
                'web_answer': item.get('web_only_answer', ''),
                'rag_answer': item.get('rag_only_answer', ''),
                'rag_sources': item.get('rag_sources', []),
                'web_sources': web_sources,
                'gaps': item.get('rag_gaps_identified', []),
                'alert_level': item.get('alert_level', 'GREEN'),
                'recommended_urls': formatted_recommended,
                'timestamp': item.get('timestamp') or item.get('created_at')
            })
        
        return {"conversation": formatted_history}
        
    except Exception as e:
        print(f"❌ Error fetching conversation history: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error fetching conversation: {str(e)}")

@app.post("/agent")
async def agent_query(request: AgentRequest):
    """Fast user response (Agent 2 only) + async admin analysis"""
    start_time = time.time()
    
    try:
        # Fetch conversation history for context (exclude current query)
        conversation_history = await get_conversation_history(request.session_id, limit=7)
        if conversation_history:
            print(f"💬 Found {len(conversation_history)} previous exchanges in session")
        
        # SYNC: Run Agent 2 only (web search) - NOW TRULY ASYNC
        # Pass conversation history so Agent 2 can understand follow-up questions
        web_result = await search_web_only(request.query, conversation_history=conversation_history)
        
        # Generate query ID
        query_id = str(uuid.uuid4())
        
        # Calculate response time (should now be 2-5 seconds)
        response_time_ms = int((time.time() - start_time) * 1000)
        
        # Prepare initial log data
        web_source_urls = [
            source.get('url', '') if isinstance(source, dict) else str(source)
            for source in web_result.get('web_sources', [])
        ]
        
        initial_log = {
            'id': query_id,
            'user_query': request.query,
            'user_id': request.user_id,
            'session_id': request.session_id,
            'timestamp': datetime.utcnow().isoformat(),
            'response_time_ms': response_time_ms,
            'web_only_answer': web_result['answer'],
            'web_sources': web_source_urls,
            'agent2_source_count': len(web_result['web_sources']),
            'final_answer': web_result['answer'],
            'agent_response': web_result['answer'],
            'input_moderation_passed': True,
            'output_moderation_passed': True
        }
        
        # CHANGED: Use asyncio.create_task instead of BackgroundTasks
        # Pass conversation history to admin analysis for RAG context
        asyncio.create_task(
            run_admin_analysis(query_id, request.query, web_result, initial_log, conversation_history=conversation_history)
        )
        print(f"🚀 Triggered async admin analysis for query_id = {query_id}")
        
        # Return to user immediately (only Agent 2 data)
        return {
            "answer": web_result['answer'],
            "web_sources": web_result['web_sources'],
            "query_id": query_id
        }

    except Exception as e:
        print(f"❌ Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
