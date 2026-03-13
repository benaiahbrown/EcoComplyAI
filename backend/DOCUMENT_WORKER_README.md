# Background Worker for Supabase Document Ingestion

## Overview

This document describes the background worker system that automatically ingests documents from Supabase into the Chroma vector store for RAG (Retrieval-Augmented Generation).

## Architecture

### Components

1. **`add_document_from_supabase()`** (`landrag.py`)
   - Function that takes document text and metadata from Supabase
   - Chunks the document using RecursiveCharacterTextSplitter
   - Adds chunks to Chroma with full metadata (title, summary, key_terms, etc.)
   - Returns success status and chunk count

2. **`document_worker.py`**
   - Background worker module that polls Supabase for pending documents
   - Processes documents in batches
   - Updates document status in Supabase after successful ingestion
   - Runs continuously in a background asyncio task

3. **FastAPI Integration** (`main.py`)
   - Uses FastAPI's lifespan context manager to start/stop worker
   - Worker starts automatically when FastAPI app starts
   - Worker stops gracefully when app shuts down

## How It Works

### Workflow

1. **Document Approval in Supabase**
   - Documents are added to `documents_and_metadata` table
   - Status must be set to `'approved'` for the worker to process them
   - `processed_at` remains `NULL` until processed

2. **Worker Polling**
   - Worker polls Supabase every 60 seconds (configurable via `DOCUMENT_WORKER_POLL_INTERVAL`)
   - Queries for documents where `status = 'approved'` AND `processed_at IS NULL`
   - Processes up to 5 documents per poll (configurable via `DOCUMENT_WORKER_BATCH_SIZE`)

3. **Document Processing**
   - For each approved document:
     - Extracts document text from `document` field
     - Builds comprehensive metadata dictionary from all fields
     - Calls `add_document_from_supabase()` to chunk and add to Chroma
     - Updates Supabase row: sets `processed_at = current_timestamp` (status remains unchanged)

4. **Error Handling**
   - If processing fails, document remains `'approved'` with `processed_at = NULL` for retry on next poll
   - Errors are logged to console with full stack traces
   - Worker continues processing other documents even if one fails

## Configuration

### Environment Variables

Add these to your `.env` file (optional, defaults shown):

```bash
# Poll interval in seconds (default: 60)
DOCUMENT_WORKER_POLL_INTERVAL=60

# Number of documents to process per poll (default: 5)
DOCUMENT_WORKER_BATCH_SIZE=5
```

### Supabase Table Schema

The worker expects a table `documents_and_metadata` with these columns:

- `id` (uuid, primary key)
- `document` (text) - The full text content to ingest
- `status` (text) - Must be `'approved'` for worker to process. Status is NOT changed by worker.
- `processed_at` (timestamp) - NULL when not yet processed, set to timestamp when processed
- `title` (text) - Document title
- `summary` (text) - Document summary (optional)
- `key_terms` (jsonb/text array) - Key terms (optional)
- `main_topics` (jsonb/text array) - Main topics (optional)
- `geographic_scope` (jsonb/text array) - Geographic coverage (optional)
- `effective_date` (text/date) - Effective date (optional)
- `created_at` (timestamp) - When document was added (optional)

## Metadata Handling

The worker converts Supabase metadata into Chroma-compatible format:

- **Arrays/Lists**: Converted to comma-separated strings (e.g., `['term1', 'term2']` → `'term1, term2'`)
- **All metadata fields** are preserved and stored with each chunk in Chroma
- **Required fields**: `document_id`, `title`, `source='supabase'`, `filename` (uses title)
- **Optional fields**: All other fields from Supabase row are included if present

## Usage

### Automatic Operation

The worker starts automatically when you start the FastAPI server:

```bash
cd backend
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

You should see:
```
🚀 Starting Land Compliance RAG API...
[WORKER] 🚀 Document ingestion worker started (polling every 60s)
```

### Monitoring

Watch the console logs for worker activity:

- `[WORKER] Found N pending document(s) to process` - Worker found pending documents
- `[INGEST] Processing document from Supabase: id=...` - Processing started
- `[WORKER] ✅ Successfully processed document ... (N chunks)` - Success
- `[WORKER] ❌ Error processing document ...` - Error (will retry)

### Manual Testing

To test the worker:

1. Insert a test document into Supabase with status='approved':
```sql
INSERT INTO documents_and_metadata (
  id,
  document,
  status,
  title,
  summary,
  key_terms
) VALUES (
  gen_random_uuid(),
  'This is a test document about environmental compliance regulations...',
  'approved',
  'Test Document',
  'A test document for ingestion',
  ARRAY['test', 'compliance', 'environmental']
);
```

2. Watch the logs - the worker should pick it up within 60 seconds

3. Verify in Supabase - `processed_at` should be set to current timestamp (status remains `'approved'`)

4. Verify in Chroma - Query the RAG system and the document should be retrievable

## Troubleshooting

### Worker Not Starting

- Check that Supabase credentials are set in `.env`:
  - `SUPABASE_URL`
  - `SUPABASE_KEY`

### Documents Not Processing

- Check Supabase table name is exactly `documents_and_metadata`
- Verify documents have `status = 'approved'` AND `processed_at IS NULL`
- Check worker logs for errors

### Documents Not Being Processed

- Check logs for error messages
- Verify document status is set to `'approved'` (not 'pending' or other status)
- Verify `document` field contains text (not NULL or empty)
- Verify Chroma vector store is accessible and writable
- Check that embeddings API key is set (`OPENROUTER_API_KEY`)

## Code Structure

```
backend/
├── main.py                  # FastAPI app with lifespan integration
├── landrag.py              # add_document_from_supabase() function
├── document_worker.py      # Background worker module
└── DOCUMENT_WORKER_README.md  # This file
```

## Future Enhancements

Potential improvements:

1. **Retry Logic**: Add exponential backoff for failed documents
2. **Dead Letter Queue**: Move permanently failed documents to a separate table
3. **Metrics**: Add Prometheus metrics or logging to external service
4. **Priority Queue**: Process high-priority documents first
5. **Webhook Mode**: Use Supabase real-time subscriptions instead of polling
6. **Worker Status Endpoint**: Add `/admin/worker/status` endpoint for monitoring

