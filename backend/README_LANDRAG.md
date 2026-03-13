# landrag.py - RAG System and Vector Store Operations

Core RAG (Retrieval-Augmented Generation) system implementation. Handles document ingestion, vector store management, and query processing.

## Overview

This module provides the foundational RAG capabilities:
- Document ingestion (file uploads and Supabase documents)
- Text extraction from multiple file formats
- Document chunking and embedding
- Vector store operations (ChromaDB)
- Query processing with LLM synthesis
- Document listing and metadata management

## Vector Store Setup

### ChromaDB Configuration

- **Embedding Model**: OpenAI text-embedding-3-large (via OpenRouter)
- **Vector Store**: ChromaDB with persistent storage in `./chroma_db`
- **Retriever**: Returns top 5 most relevant chunks per query

### LLM Configuration

- **Model**: Claude 3.5 Sonnet (via OpenRouter)
- **Temperature**: 0 (deterministic responses)
- **Base URL**: OpenRouter API endpoint

## Document Ingestion

### `add_document(file_path: str, filename: str)`
Adds a document from file upload to the vector store.

**Process:**
1. Extracts text from file (supports PDF, DOCX, TXT, XLSX, CSV, HTML, XML)
2. Creates Document object with metadata
3. Splits into chunks (1000 chars, 200 overlap)
4. Adds chunks to ChromaDB in batches (batch size: 25)
5. Returns success status and chunk count

**Supported Formats:**
- `.pdf` - PDF documents (with OCR fallback for scanned PDFs)
- `.docx` - Microsoft Word documents
- `.txt` - Plain text files
- `.xlsx` - Excel spreadsheets
- `.csv` - CSV files
- `.html` - HTML files
- `.xml` - XML files

**Metadata Stored:**
- `filename`: Original filename

### `add_document_from_supabase(document_text: str, metadata: Dict)`
Adds a document from Supabase to the vector store with full metadata.

**Process:**
1. Takes document text and metadata dictionary from Supabase
2. Builds comprehensive Chroma metadata from all Supabase fields
3. Creates Document object with full metadata
4. Splits into chunks (1000 chars, 200 overlap)
5. Adds chunks to ChromaDB in batches (batch size: 25)
6. Returns success status and chunk count

**Metadata Fields Stored:**
- `document_id`: UUID from Supabase
- `title`: Document title
- `source`: "supabase"
- `filename`: Document title (for consistency)
- `summary`: Document summary (if available)
- `key_terms`: Comma-separated key terms
- `main_topics`: Comma-separated main topics
- `geographic_scope`: Comma-separated geographic scope
- `effective_date`: Effective date (if available)
- `created_at`: Creation timestamp (if available)

**Used by:** `document_worker.py` for automatic document ingestion

## Text Extraction

### `extract_text_from_file(file_path: str) -> str`
Extracts text from various file formats.

**Features:**
- Multi-format support (PDF, DOCX, TXT, XLSX, CSV, HTML, XML)
- Automatic OCR fallback for scanned PDFs
- Error handling for corrupted files

### `extract_pdf_with_mistral_ocr(file_path: str) -> str`
Uses Mistral Pixtral for OCR on image-based/scanned PDFs.

**Process:**
1. Converts PDF pages to images (200 DPI)
2. Uses Mistral Pixtral model for OCR
3. Extracts text from each page
4. Combines into full document text

**Requires:** `MISTRAL_API_KEY` environment variable

## Query Processing

### `query_rag(question: str, conversation_history: List[Dict] = None)`
Queries the RAG system and returns answer with source documents.

**Process:**
1. Builds conversation context from history (if provided)
2. Extracts key terms from conversation for query expansion
3. Retrieves relevant documents from ChromaDB (top 5 chunks)
4. Formats documents for context
5. Uses LLM to synthesize answer
6. Returns answer with source document filenames

**Input:**
- `question`: The current question to answer
- `conversation_history`: Optional list of previous Q&A pairs

**Output:**
```python
{
  "answer": "Synthesized answer",
  "sources": ["document1.pdf", "document2.pdf"],
  "source_documents": [...]  # Full document objects
}
```

**Features:**
- Conversation context awareness
- Query expansion using conversation key terms
- Source citation in response
- Handles empty results gracefully

### `format_docs(docs)`
Formats retrieved documents for LLM context (concatenates page content).

## Document Management

### `list_documents()`
Lists all documents in the vector store with structured metadata.

**Output:**
```python
{
  "total_chunks": 1234,
  "unique_documents": 45,
  "sources": {
    "supabase": {
      "documents": [
        {
          "title": "Document Title",
          "document_id": "uuid",
          "chunk_count": 42,
          "metadata": {...}
        }
      ],
      "total_chunks": 100,
      "unique_document_count": 10
    },
    "file_upload": {...}
  },
  "documents": [...]  # Legacy flat list
}
```

**Features:**
- Groups documents by source (supabase vs file_upload)
- Includes full metadata for each document
- Provides chunk counts per document
- Backwards compatible with flat list format

## Utility Functions

### `strip_markdown(text: str) -> str`
Strips markdown formatting from text. Used to prevent formatting corruption in conversation history.

### `extract_key_terms_from_conversation(conversation_history: List[Dict]) -> str`
Extracts key terms from conversation history for query expansion. Used to improve RAG retrieval by expanding queries with relevant terms from previous exchanges.

## Configuration

### Environment Variables

Required:
- `OPENROUTER_API_KEY` - OpenRouter API key for embeddings and LLM
- `MISTRAL_API_KEY` - Mistral API key for OCR (optional, only needed for scanned PDFs)

### Chunking Configuration

- **Chunk Size**: 1000 characters
- **Chunk Overlap**: 200 characters
- **Batch Size**: 25 chunks per batch (for ingestion)

### Vector Store Configuration

- **Persist Directory**: `./chroma_db`
- **Embedding Model**: `openai/text-embedding-3-large`
- **Retrieval Count**: Top 5 chunks per query

## Error Handling

All functions include comprehensive error handling:
- Returns structured error responses
- Logs errors with tracebacks
- Handles empty/invalid inputs gracefully
- Continues processing even if individual operations fail

## Dependencies

- `langchain_community` - ChromaDB vector store
- `langchain_openai` - OpenAI embeddings (via OpenRouter)
- `langchain_text_splitters` - Text chunking
- `langchain_core` - Document and prompt abstractions
- `PyPDFLoader` - PDF text extraction
- `python-docx` - DOCX file handling
- `pandas` - Excel/CSV handling
- `mistralai` - OCR for scanned PDFs
- `pdf2image` - PDF to image conversion for OCR

## See Also

- `main.py` - API endpoints that use these functions
- `document_worker.py` - Automatic document ingestion using `add_document_from_supabase`
- `simple_agent.py` - Agent functions that use `query_rag`
- `BACKEND_WORKFLOW_DIAGRAM.txt` - Detailed workflow documentation

