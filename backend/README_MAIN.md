# main.py - FastAPI Backend Server

Main FastAPI application server for the Land Compliance RAG system. Handles HTTP requests, routes to agent functions, and manages background workers.

## Overview

This module serves as the entry point for the backend API, providing REST endpoints for query processing, document management, and admin functions. It also manages the document ingestion worker lifecycle.

## Key Features

- FastAPI REST API server
- CORS configuration for frontend integration
- Supabase integration for data persistence
- Background document worker lifecycle management
- Async request handling
- URL resolution for web sources

## Application Lifecycle

The application uses FastAPI's lifespan context manager to start and stop the background document worker:

- **Startup**: Starts the document ingestion worker (polls Supabase for approved documents)
- **Runtime**: Handles HTTP requests and routes to appropriate handlers
- **Shutdown**: Gracefully stops the document worker

## API Endpoints

### User Endpoints

#### `POST /agent`
Main query endpoint for user queries. Returns fast web-only response, triggers async admin analysis.

**Request:**
```json
{
  "query": "What are wetland regulations?",
  "user_id": "uuid-from-supabase-auth",
  "session_id": "uuid-generated-by-frontend"
}
```

**Response:**
```json
{
  "answer": "...",
  "web_sources": [{"url": "...", "title": "..."}],
  "query_id": "uuid"
}
```

**Flow:**
1. Fetches conversation history (last 7 exchanges)
2. Runs Agent 2 (web search) synchronously
3. Logs initial response to Supabase
4. Triggers async admin analysis (non-blocking)
5. Returns immediately to user (2-5 seconds)

#### `POST /query`
Basic RAG query endpoint (no agents, for testing).

**Request:**
```json
{
  "question": "What are the regulations?"
}
```

#### `GET /documents`
List all documents in the RAG system, grouped by source.

**Response:**
```json
{
  "total_chunks": 1234,
  "unique_documents": 45,
  "sources": {
    "supabase": {
      "documents": [...],
      "total_chunks": 100,
      "unique_document_count": 10
    },
    "file_upload": {...}
  }
}
```

### Admin Endpoints

#### `GET /admin/analysis/{query_id}`
Get admin analysis results for a query (requires admin authentication).

**Headers:**
```
X-User-ID: uuid-from-supabase-auth
```

**Response:**
```json
{
  "status": "processing" | "complete",
  "web_answer": "...",
  "web_sources": [...],
  "rag_answer": "...",
  "rag_sources": [...],
  "gaps": [...],
  "alert_level": "GREEN" | "YELLOW" | "RED",
  "recommended_urls": [...]
}
```

### History & Conversation Endpoints

#### `GET /history`
Fetch recent query history (last 50 queries across all users).

#### `GET /conversation/{session_id}`
Fetch full conversation history for a session, including RAG analysis data.

**Headers (optional):**
```
X-User-ID: uuid-from-supabase-auth
```

#### `POST /upload`
Upload documents to RAG system (admin only).

**Request:** Multipart form data with file

### Utility Endpoints

#### `GET /`
Root endpoint - returns API status message.

#### `GET /health`
Health check endpoint - returns `{"status": "ok"}`.

## Background Workers

### Document Ingestion Worker

The document worker is started automatically when the FastAPI app starts and stopped on shutdown. It:

- Polls Supabase every 60 seconds (configurable)
- Processes documents with `status='approved'` and `processed_at IS NULL`
- Ingests documents into Chroma vector store
- Updates `processed_at` timestamp on completion

See `document_worker.py` for implementation details.

## Configuration

### Environment Variables

Required:
- `SUPABASE_URL` - Supabase project URL
- `SUPABASE_KEY` - Supabase service_role key (not anon key)
- `OPENROUTER_API_KEY` - OpenRouter API key for LLM
- `GOOGLE_API_KEY` - Google API key for Gemini web search

Optional:
- `ALLOW_ALL_ORIGINS` - Set to `"true"` to allow all CORS origins (default: true)
- `DOCUMENT_WORKER_POLL_INTERVAL` - Poll interval in seconds (default: 60)
- `DOCUMENT_WORKER_BATCH_SIZE` - Documents per poll (default: 5)

### CORS Configuration

CORS is configured in the code:
- Development: Allows all origins by default
- Production: Can restrict to specific origins via `LOVABLE_ORIGINS` list
- Set `ALLOW_ALL_ORIGINS=false` in `.env` to restrict to `LOVABLE_ORIGINS`

## Dependencies

- `fastapi` - Web framework
- `supabase` - Supabase client
- `landrag` - RAG system functions
- `simple_agent` - Agent orchestration
- `document_worker` - Background worker
- `httpx` - HTTP client for async requests

## Key Functions

### `resolve_redirect_url(url: str) -> str`
Resolves Google redirect URLs to actual destinations (async).

### `resolve_web_sources(sources: List[Dict]) -> List[Dict]`
Resolves all redirect URLs in web sources list (async).

### `log_query_to_supabase(request, result: dict, response_time_ms: int)`
Logs query results to Supabase `compliance_queries` table and adds URLs to `rag_update_queue` if needed.

### `get_conversation_history(session_id: str, limit: int = 5) -> List[Dict]`
Fetches recent conversation history for a session from Supabase.

## Running the Server

```bash
# Development (with auto-reload)
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Production
uvicorn main:app --host 0.0.0.0 --port 8000
```

## See Also

- `simple_agent.py` - Agent functions and orchestration
- `landrag.py` - RAG system and vector store operations
- `document_worker.py` - Background document ingestion worker
- `BACKEND_WORKFLOW_DIAGRAM.txt` - Detailed workflow documentation

