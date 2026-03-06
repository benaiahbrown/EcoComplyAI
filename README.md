# Land Compliance RAG System

A web + RAG (Retrieval-Augmented Generation) search tool that provides compliance and regulatory information for landowners. The system combines internal document search (RAG) with real-time web search to provide comprehensive, up-to-date answers.

## Overview

This system helps landowners maintain environmental compliance by:
- Searching internal document database (federal/state regulations, manuals, handbooks)
- Searching current web sources for latest regulatory updates
- Identifying knowledge gaps between internal and external sources
- Recommending URLs for RAG database updates
- Processing documents automatically from Supabase

## Architecture

### Components

1. **FastAPI Backend** (`backend/main.py`)
   - REST API server
   - Request routing and handling
   - Background worker management

2. **RAG System** (`backend/landrag.py`)
   - ChromaDB vector store management
   - Document ingestion and chunking
   - Query processing with LLM synthesis

3. **Multi-Agent System** (`backend/simple_agent.py`)
   - Agent 1: RAG search (internal documents)
   - Agent 2: Web search (current sources)
   - Agent 3: Gap analysis (RAG vs Web comparison)
   - Agent 4: URL recommendation (for RAG updates)

4. **Document Worker** (`backend/document_worker.py`)
   - Background worker for automatic document ingestion
   - Polls Supabase for approved documents
   - Ingests documents into ChromaDB

5. **Frontend** (Lovable)
   - User interface
   - Query submission
   - Result display
   - Admin dashboard

### Data Flow

```
User Query
    │
    ├─► FastAPI (/agent endpoint)
    │   ├─► Agent 2 (Web Search) - SYNC, returns fast (2-5s)
    │   └─► Trigger async admin analysis
    │
    └─► Background Admin Analysis (async)
        ├─► Agent 1 (RAG Search)
        ├─► Agent 3 (Gap Analysis)
        ├─► Agent 4 (URL Selection) - conditional
        └─► Update Supabase + Queue URLs
```

## Features

### Query Processing
- **Fast User Response**: Web-only search returns in 2-5 seconds
- **Comprehensive Analysis**: Full RAG + gap analysis in background
- **Conversation Context**: Maintains conversation history for follow-up questions
- **Source Citations**: All answers include source documents/URLs

### Document Management
- **File Upload**: Support for PDF, DOCX, TXT, XLSX, CSV, HTML, XML
- **Automatic Ingestion**: Background worker processes approved documents from Supabase
- **Full Metadata**: Documents stored with title, summary, key terms, geographic scope, etc.
- **Structured Listing**: Documents grouped by source with metadata

### Gap Analysis
- **Knowledge Gap Detection**: Compares RAG vs Web answers
- **Alert Levels**: GREEN (no gaps), YELLOW (minor gaps), RED (major gaps)
- **URL Recommendations**: Suggests URLs for RAG database updates
- **Priority Queue**: URLs queued with priority based on alert level

## Technology Stack

### Backend
- **FastAPI**: Web framework
- **ChromaDB**: Vector database
- **LangChain**: RAG framework
- **OpenRouter**: LLM access (Claude 3.5 Sonnet)
- **Google Gemini**: Web search with grounding
- **Supabase**: Database and authentication

### Models
- **Embeddings**: OpenAI text-embedding-3-large (via OpenRouter)
- **LLM**: Claude 3.5 Sonnet (via OpenRouter)
- **Web Search**: Google Gemini 2.5 Flash

## Getting Started

### Prerequisites

- Python 3.8+
- Supabase account and project
- OpenRouter API key
- Google API key (for Gemini)
- Optional: Mistral API key (for OCR on scanned PDFs)

### Installation

1. Clone the repository:
```bash
git clone https://github.com/benaiahbrown/EcoComplyAI.git
cd EcoComplyAI
```

2. Create virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Configure environment variables (create `backend/.env`):
```bash
# Supabase
SUPABASE_URL=https://xxxxx.supabase.co
SUPABASE_KEY=your_service_role_key

# LLM APIs
OPENROUTER_API_KEY=your_openrouter_key
GOOGLE_API_KEY=your_google_api_key

# Optional
MISTRAL_API_KEY=your_mistral_key  # For OCR on scanned PDFs
ALLOW_ALL_ORIGINS=true  # CORS setting
DOCUMENT_WORKER_POLL_INTERVAL=60  # Poll interval in seconds
DOCUMENT_WORKER_BATCH_SIZE=5  # Documents per poll
```

5. Start the backend server:
```bash
cd backend
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

The server will start on `http://localhost:8000` and the document worker will begin polling Supabase automatically.

### Testing

Test the health endpoint:
```bash
curl http://localhost:8000/health
```

Test a query:
```bash
curl -X POST http://localhost:8000/agent \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What are wetland regulations?",
    "user_id": "test-user",
    "session_id": "test-session"
  }'
```

## API Endpoints

### User Endpoints
- `POST /agent` - Main query endpoint (fast response, async analysis)
- `POST /query` - Basic RAG query (testing)
- `GET /documents` - List all documents in RAG system

### Admin Endpoints
- `GET /admin/analysis/{query_id}` - Get admin analysis results
- `POST /upload` - Upload documents to RAG system

### Utility Endpoints
- `GET /health` - Health check
- `GET /history` - Query history
- `GET /conversation/{session_id}` - Conversation history

See `backend/README_MAIN.md` for detailed endpoint documentation.

## Document Ingestion

### Manual Upload

Use the `/upload` endpoint to upload documents directly:
```bash
curl -X POST http://localhost:8000/upload \
  -F "file=@document.pdf"
```

### Automatic Ingestion (Supabase)

Documents are automatically ingested from Supabase via the background worker:

1. Add document to `documents_and_metadata` table in Supabase
2. Set `status = 'approved'`
3. Ensure `processed_at IS NULL`
4. Worker will process within 60 seconds (default poll interval)

See `backend/DOCUMENT_WORKER_README.md` for details.

## Project Structure

```
rag-system/
├── backend/
│   ├── main.py              # FastAPI server
│   ├── simple_agent.py      # Multi-agent orchestration
│   ├── landrag.py           # RAG system
│   ├── document_worker.py   # Background document ingestion
│   ├── chroma_db/           # Vector store data
│   └── legal_docs/          # Legal documents directory
├── frontend/                # Frontend application (Lovable)
├── requirements.txt         # Python dependencies
└── README.md               # This file
```

## Documentation

- `backend/README_MAIN.md` - FastAPI server documentation
- `backend/README_SIMPLE_AGENT.md` - Agent system documentation
- `backend/README_LANDRAG.md` - RAG system documentation
- `backend/DOCUMENT_WORKER_README.md` - Document worker documentation
- `BACKEND_WORKFLOW_DIAGRAM.txt` - Detailed workflow diagram
- `LOVABLE_INTEGRATION_CHECKLIST.md` - Frontend integration guide

## Development

### Running in Development

```bash
cd backend
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Running in Production

```bash
cd backend
uvicorn main:app --host 0.0.0.0 --port 8000
```

### Background Worker

The document worker starts automatically when the FastAPI app starts. It:
- Polls Supabase every 60 seconds (configurable)
- Processes up to 5 documents per poll (configurable)
- Updates `processed_at` timestamp on completion
- Continues running until server shutdown

## Contributing

Contributions are welcome! Please open an issue or submit a pull request.

## License

MIT License
