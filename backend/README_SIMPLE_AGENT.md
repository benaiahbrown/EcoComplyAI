# simple_agent.py - Multi-Agent Orchestration System

Orchestrates a 4-agent pipeline for compliance query processing, combining RAG search, web search, gap analysis, and URL recommendation.

## Overview

This module implements a multi-agent system that processes compliance queries through parallel and sequential agent execution. The system is designed to provide fast user responses while performing comprehensive analysis in the background.

## Agent Architecture

### Agent 1: RAG Search (`search_rag_only`)
Searches the internal RAG database using ChromaDB vector store.

**Input:**
- `query`: User question
- `conversation_history`: Optional list of previous Q&A pairs for context

**Process:**
- Extracts key terms from conversation history for query expansion
- Queries ChromaDB vector store
- Uses LLM (Claude via OpenRouter) for answer synthesis
- Returns answer with source document filenames

**Output:**
```python
{
  "answer": "Synthesized answer from RAG documents",
  "sources": ["document1.pdf", "document2.pdf"],
  "confidence": "high" | "low" | "none"
}
```

### Agent 2: Web Search (`search_web_only`)
Searches the web using Google Gemini 2.5 Flash with grounding.

**Input:**
- `query`: User question
- `conversation_history`: Optional list of previous Q&A pairs for context

**Process:**
- Uses conversation context for follow-up questions
- Google Gemini 2.5 Flash with web search grounding
- Extracts web sources with URLs and titles
- Returns current, authoritative information

**Output:**
```python
{
  "answer": "Answer from web sources",
  "web_sources": [
    {"url": "https://...", "title": "Source Title"}
  ]
}
```

### Agent 3: Gap Analysis (`identify_gaps`)
Compares RAG vs Web answers to identify knowledge gaps.

**Input:**
- `query`: Original question
- `rag_result`: Results from Agent 1
- `web_result`: Results from Agent 2

**Process:**
- Compares RAG and Web answers
- Identifies knowledge gaps
- Classifies alert level: GREEN (no gaps) / YELLOW (minor gaps) / RED (major gaps)
- Uses LLM (Claude via OpenRouter) for analysis

**Output:**
```python
{
  "gaps": ["Gap 1", "Gap 2", ...],
  "alert_level": "GREEN" | "YELLOW" | "RED",
  "raw_response": "Raw LLM analysis output"
}
```

### Agent 4: URL Selection (`select_update_urls`)
Selects URLs for RAG updates based on gap analysis (conditional execution).

**Input:**
- `gaps`: List of identified gaps
- `web_sources`: Web sources from Agent 2
- `query`: Original question
- `alert_level`: GREEN / YELLOW / RED

**Process:**
- Only runs if `alert_level != 'GREEN'`
- Selects URLs from web sources based on relevance
- URL limits: RED (up to 8), YELLOW (up to 4), GREEN (0, skipped)
- Uses LLM (Claude via OpenRouter) for URL selection with reasoning

**Output:**
```python
{
  "recommended_urls": [
    {
      "url": "https://...",
      "title": "Source Title",
      "reason": "Why this URL is recommended"
    }
  ]
}
```

## Main Orchestration Functions

### `run_compliance_query(query: str, conversation_history: List[Dict] = None)`
Orchestrates the full 4-agent pipeline (legacy, used in some contexts).

**Flow:**
1. Phase 1: Agents 1 & 2 run in PARALLEL (RAG + Web)
2. Phase 2: Agent 3 runs sequentially (Gap analysis)
3. Phase 3: Agent 4 runs conditionally (URL selection if gaps exist)

**Output:**
```python
{
  "rag_only_answer": "...",
  "rag_sources": [...],
  "web_only_answer": "...",
  "web_sources": [...],
  "gaps_identified": [...],
  "alert_level": "GREEN" | "YELLOW" | "RED",
  "recommended_urls": [...],
  "status": "COMPLETE"
}
```

### `run_admin_analysis(query_id: str, query: str, web_result: dict, initial_log: dict, conversation_history: List[Dict] = None)`
Background admin analysis function called asynchronously from main.py.

**Flow:**
1. Resolves web source URLs (async)
2. Runs Agent 1 (RAG search) with conversation history
3. Runs Agent 3 (Gap analysis)
4. Runs Agent 4 (URL selection) conditionally
5. Updates Supabase record with analysis results
6. Adds URLs to `rag_update_queue` if alert_level != GREEN

**Used by:** `main.py` POST `/agent` endpoint (async background task)

### `search_web_only(query: str, conversation_history: List[Dict] = None)`
Standalone web search agent (Agent 2). Used by main.py for fast user responses.

**Used by:** `main.py` POST `/agent` endpoint (synchronous, returns fast)

## System Message

The system uses a comprehensive system message for all LLM interactions that emphasizes:
- Always use up-to-date external sources
- Distinguish clearly between legal states (final rules vs proposed vs guidance)
- Prioritize precision over speculation
- Handle time sensitivity explicitly
- Source transparency
- User-focused, cautious guidance

## Configuration

### Environment Variables

Required:
- `OPENROUTER_API_KEY` - OpenRouter API key for LLM access (Claude)
- `GOOGLE_API_KEY` - Google API key for Gemini web search

### Models Used

- **RAG LLM**: Claude 3.5 Sonnet (via OpenRouter)
- **Web Search**: Google Gemini 2.5 Flash (with grounding)
- **Gap Analysis LLM**: Claude 3.5 Sonnet (via OpenRouter)
- **URL Selection LLM**: Claude 3.5 Sonnet (via OpenRouter)

## Utility Functions

### `strip_markdown(text: str) -> str`
Strips markdown formatting from text to prevent formatting corruption in conversation history. Used when storing conversation context.

## Error Handling

All agent functions include error handling:
- Returns empty/default results on errors
- Logs errors to console
- Continues execution even if one agent fails
- Error states are clearly indicated in output (e.g., `confidence: "none"`)

## Performance Considerations

- **Agent 1 & 2**: Run in parallel using `asyncio.gather()` for faster execution
- **Agent 2 Timeout**: 120 seconds read timeout for web search (can be slow)
- **Conversation History**: Limited to last 7 exchanges to manage context size
- **URL Resolution**: Async to avoid blocking

## Dependencies

- `openai` - OpenRouter client (OpenAI-compatible API)
- `httpx` - HTTP client for Gemini API
- `landrag` - RAG query functions (`query_rag`, `vectorstore`)
- `main` - URL resolution functions (`resolve_web_sources`)

## See Also

- `main.py` - API endpoints that use these agent functions
- `landrag.py` - RAG system implementation
- `BACKEND_WORKFLOW_DIAGRAM.txt` - Detailed workflow documentation

