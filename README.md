# EcoComply AI

[![Python](https://img.shields.io/badge/Python-3.11-blue)]()
[![FastAPI](https://img.shields.io/badge/FastAPI-Backend-009688)]()
[![ChromaDB](https://img.shields.io/badge/ChromaDB-Vector_DB-orange)]()
[![Supabase](https://img.shields.io/badge/Supabase-Database-3ECF8E)]()
[![License](https://img.shields.io/badge/License-MIT-green)]()

> :warning: This repository contains project documentation only.
> Source code is maintained in a private repository.

An AI-powered environmental compliance assistant that combines RAG (Retrieval-Augmented Generation) with real-time web search to help landowners navigate federal and state environmental regulations.

## Architecture

```mermaid
flowchart TD
    User([User]) --> Frontend[Lovable Frontend]
    Frontend --> API[FastAPI Backend]
    API --> A2[Web Search Agent]
    API --> BG[Background Analysis]
    BG --> A1[RAG Search Agent]
    BG --> A3[Gap Analysis Agent]
    BG --> A4[URL Recommendation Agent]
    A1 --> ChromaDB[(ChromaDB\nVector Store)]
    A2 --> Gemini[Google Gemini\nGrounded Search]
    A3 --> Supabase[(Supabase)]
    A4 --> Supabase
    Worker[Document Worker] --> Supabase
    Worker --> ChromaDB
    Admin([Admin]) --> Frontend
    Frontend --> Upload[Document Upload]
    Upload --> Worker
```

![Home](assets/home.png)

![Chat Interface](assets/chat_conversation_ui.jpg)

## What It Does

EcoComply AI helps landowners maintain environmental compliance by searching an internal database of 67 federal and state regulatory documents alongside real-time web sources. A multi-agent system performs gap analysis between internal knowledge and current regulations, automatically flagging when the knowledge base needs updating. The admin dashboard surfaces these gaps with priority-ranked URL recommendations for database expansion.

## Why This Exists

Environmental compliance is a moving target. Regulations change, court decisions alter what's enforceable, and the documents that govern what a landowner can or can't do are scattered across dozens of federal and state agencies.

EcoComply was built for a real estate team that needed to get smarter about environmental compliance — faster than reading every existing regulatory document. But the deeper goal wasn't just to answer questions. It was to build a system that improves as the team uses it.

Every query the system can't answer well becomes a signal. The gap analysis agents automatically identify what's missing from the knowledge base and surface the exact sources needed to fill it. **The more the team asks, the more complete the system becomes. The knowledge builds itself.**

## Tech Stack

- **FastAPI** — REST API backend with async background processing
- **ChromaDB** — Vector database for document embeddings and semantic search
- **LangChain** — RAG framework for document ingestion and query synthesis
- **OpenRouter** — LLM access (Claude 3.5 Sonnet)
- **Google Gemini 2.5 Flash** — Web search with grounding
- **OpenAI text-embedding-3-large** — Document embeddings (via OpenRouter)
- **Supabase** — Database, authentication, and document management
- **Lovable** — Frontend UI with user query interface and admin dashboard

## How It Works

The `/agent` endpoint runs two paths in parallel:

- **Fast path** — Google Gemini 2.5 Flash performs a live web search and returns a response in 2–5 seconds
- **Background path** — Searches the local ChromaDB vector store (~77k indexed regulatory document chunks), runs a gap analysis comparing RAG vs. web results, and queues recommended documents for admin review if gaps are found

A background worker polls Supabase every 60 seconds for newly approved documents and ingests them into ChromaDB automatically.

**Key files:**
- `backend/main.py` — FastAPI server & endpoints
- `backend/simple_agent.py` — 4-agent orchestration
- `backend/landrag.py` — RAG system & vector store
- `backend/document_worker.py` — Background ingestion worker

## Usage Examples

![RAG Agent Analytics](assets/rag_agent_analytics.png)

![Search Agent Evals](assets/search_agent_evals.png)

![Query-by-Query Diagnostics](assets/query-by-query-diagnostics.jpg)

![Document Queue](assets/document_queue.jpg)

**Sample query and response:**

```json
{
  "query": "What wetland permits do I need for construction near a stream in Georgia?",
  "user_id": "user-123",
  "session_id": "session-456"
}
```

```json
{
  "status": "success",
  "response": "For construction near streams in Georgia, you typically need: (1) A Section 404 permit from the U.S. Army Corps of Engineers under the Clean Water Act for any discharge of dredged or fill material into waters of the U.S., (2) A Section 401 Water Quality Certification from Georgia EPD...",
  "sources": [
    "33 CFR Part 323 - Permits for Discharges of Dredged or Fill Material",
    "Georgia Water Quality Standards (Aug 2022)",
    "1987 Corps Wetland Delineation Manual"
  ],
  "response_time_ms": 6200
}
```

**Multi-agent gap analysis (admin view):**

```json
{
  "alert_level": "YELLOW",
  "gap_summary": "RAG database covers federal CWA requirements but is missing Georgia's 2024 updated 303(d) list and recent EPD guidance on stream buffer variances.",
  "recommended_urls": [
    {
      "url": "https://epd.georgia.gov/watershed-protection-branch/water-quality-georgia",
      "priority": "high",
      "reason": "Georgia 2024 impaired waters list not in RAG database"
    }
  ]
}
```

## Video Walkthrough

[Watch the full demo on Loom](https://www.loom.com/share/470bba944dd74130a011e82f03b449b4)

## Results / Outcomes

- **76,914 document chunks** indexed from 67 federal and state regulatory documents
- **5–10 second response time** for user-facing web search queries
- **95% excellent-to-perfect** search agent evaluation scores (assessed by Google Gemini 3 Pro)
- **128 test runs** completed during development and validation
- **3-tier gap detection** (GREEN / YELLOW / RED) automatically identifies knowledge base gaps

## Local Setup

**Prerequisites**
- Python 3.10+
- API keys for: OpenRouter, Mistral, Google (Gemini), and Supabase project credentials

**1. Install dependencies**

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**2. Configure environment**

```bash
cp .env.example .env
```

Fill in `.env` with your credentials:

```env
OPENROUTER_API_KEY=...
MISTRAL_API_KEY=...
GOOGLE_API_KEY=...
SUPABASE_URL=...
SUPABASE_KEY=...
```

**3. Start the backend**

```bash
cd backend
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

You should see:

```
🚀 Starting Land Compliance RAG API...
[WORKER] 🚀 Document ingestion worker started
INFO:     Uvicorn running on http://0.0.0.0:8000
```

**4. Verify it's running**

```bash
curl http://localhost:8000/health
# {"status": "ok"}
```

**5. Send a query**

```bash
curl -X POST http://localhost:8000/agent \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What wetland permits do I need for construction near a stream?",
    "user_id": "user-123",
    "session_id": "session-456"
  }'
```

## Roadmap / Future Improvements

- Add support for additional state regulatory databases (currently covers Georgia, Florida, South Carolina)
- Implement scheduled regulatory update monitoring with automated alerts
- Add document versioning to track regulatory changes over time
- Expand OCR capabilities for scanned historical documents
- Build batch query mode for compliance audits across multiple parcels
