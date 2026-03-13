"""
Background worker for processing approved documents from Supabase

This worker continuously polls Supabase for documents with status='approved'
and processed_at IS NULL, ingests them into Chroma, and updates processed_at timestamp.
"""

import asyncio
import os
from datetime import datetime
from typing import Optional
from supabase import create_client, Client
from dotenv import load_dotenv
from landrag import add_document_from_supabase

load_dotenv()

# Initialize Supabase client
supabase: Client = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY")
)

# Worker configuration
POLL_INTERVAL_SECONDS = int(os.getenv("DOCUMENT_WORKER_POLL_INTERVAL", "60"))  # Default: 60 seconds
MAX_DOCUMENTS_PER_POLL = int(os.getenv("DOCUMENT_WORKER_BATCH_SIZE", "5"))  # Default: process 5 at a time

# Global flag to control worker execution
_worker_running = False
_worker_task: Optional[asyncio.Task] = None


async def process_approved_documents():
    """Process a batch of approved documents from Supabase"""
    try:
        # Query for approved documents that haven't been processed yet
        # Use .is_() with None to check for NULL processed_at
        try:
            result = supabase.table('documents_and_metadata')\
                .select('*')\
                .eq('status', 'approved')\
                .is_('processed_at', None)\
                .limit(MAX_DOCUMENTS_PER_POLL)\
                .execute()
            approved_docs = result.data if result.data else []
        except Exception as e:
            # Fallback: if .is_() doesn't work, query all approved and filter in Python
            print(f"[WORKER] ⚠️ .is_() query failed, using fallback: {e}")
            result = supabase.table('documents_and_metadata')\
                .select('*')\
                .eq('status', 'approved')\
                .limit(MAX_DOCUMENTS_PER_POLL * 2)\
                .execute()
            approved_docs = [
                doc for doc in (result.data if result.data else [])
                if doc.get('processed_at') is None
            ][:MAX_DOCUMENTS_PER_POLL]
        
        if not approved_docs:
            return 0
        
        print(f"[WORKER] Found {len(approved_docs)} approved document(s) to process")
        
        processed_count = 0
        
        for doc_data in approved_docs:
            doc_id = doc_data.get('id')
            title = doc_data.get('title', 'Untitled')
            
            try:
                # Extract document text
                document_text = doc_data.get('document')
                
                if not document_text:
                    print(f"[WORKER] ⚠️ Document {doc_id} has no document text, marking processed_at anyway")
                    # Set processed_at even if no text (to avoid reprocessing)
                    supabase.table('documents_and_metadata')\
                        .update({
                            'processed_at': datetime.utcnow().isoformat()
                        })\
                        .eq('id', doc_id)\
                        .execute()
                    processed_count += 1
                    continue
                
                print(f"[WORKER] Processing document {doc_id}: {title[:50]}...")
                
                # Add to Chroma with full metadata
                result = await add_document_from_supabase(document_text, doc_data)
                
                if result.get('success'):
                    # Update processed_at timestamp to mark as processed
                    supabase.table('documents_and_metadata')\
                        .update({
                            'processed_at': datetime.utcnow().isoformat()
                        })\
                        .eq('id', doc_id)\
                        .execute()
                    
                    chunks_processed = result.get('chunks_processed', 0)
                    print(f"[WORKER] ✅ Successfully processed document {doc_id} ({chunks_processed} chunks)")
                    processed_count += 1
                else:
                    print(f"[WORKER] ❌ Failed to process document {doc_id}: {result.get('message', 'Unknown error')}")
                    # Leave document as 'approved' with NULL processed_at so it can be retried on next poll
                    
            except Exception as e:
                print(f"[WORKER] ❌ Error processing document {doc_id}: {str(e)}")
                import traceback
                traceback.print_exc()
                # Leave document as 'approved' with NULL processed_at for retry on next poll
        
        return processed_count
    
    except Exception as e:
        print(f"[WORKER] ❌ Error in process_approved_documents: {str(e)}")
        import traceback
        traceback.print_exc()
        return 0


async def document_worker_loop():
    """Main worker loop that polls and processes documents"""
    global _worker_running
    
    print(f"[WORKER] 🚀 Document ingestion worker started (polling every {POLL_INTERVAL_SECONDS}s)")
    _worker_running = True
    
    while _worker_running:
        try:
            await process_approved_documents()
        except Exception as e:
            print(f"[WORKER] ❌ Error in worker loop: {str(e)}")
            import traceback
            traceback.print_exc()
        
        # Wait before next poll
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def start_worker():
    """Start the background worker"""
    global _worker_task, _worker_running
    
    if _worker_task and not _worker_task.done():
        print("[WORKER] ⚠️ Worker is already running")
        return
    
    _worker_running = True
    _worker_task = asyncio.create_task(document_worker_loop())
    print("[WORKER] ✅ Document worker task started")
    return _worker_task


async def stop_worker():
    """Stop the background worker"""
    global _worker_running, _worker_task
    
    print("[WORKER] 🛑 Stopping document worker...")
    _worker_running = False
    
    if _worker_task and not _worker_task.done():
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
    
    print("[WORKER] ✅ Document worker stopped")


def is_worker_running() -> bool:
    """Check if worker is currently running"""
    return _worker_running and _worker_task is not None and not _worker_task.done()

