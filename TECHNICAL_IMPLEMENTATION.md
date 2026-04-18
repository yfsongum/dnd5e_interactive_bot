# Technical Implementation: D&D 5e Rules Assistant

## 1. Introduction

This document describes the technical implementation of the D&D 5e Rules Assistant, a lightweight retrieval-augmented generation (RAG) system for question answering over a Dungeons & Dragons 5e rules corpus.

The system was developed as a minimal end-to-end prototype and later deployed on AWS EC2. It includes:

- raw data acquisition from the D&D 5e API
- local preprocessing and embedding generation
- local vector storage with Qdrant
- FastAPI-based serving layer
- a lightweight static frontend for interaction
- early support for source traceback / evidence display

## 2. System Architecture

The application has three major layers:

### A. Data Acquisition Layer
Responsible for downloading and organizing the raw corpus.

### B. Retrieval / Indexing Layer
Responsible for preprocessing, chunking, embedding, and storing vectorized content.

### C. Serving Layer
Responsible for API exposure, retrieval at query time, LLM prompting, and returning structured responses to the frontend.

At a conceptual level:

```text
D&D 5e API
   ↓
get_data.py
   ↓
local JSON corpus (dnd5eapi_dump/)
   ↓
pipeline.ipynb
   ↓
qdrant_local/ vector store
   ↓
FastAPI app (app.py)
   ↓
static frontend (2.0website.html)
```

## 3. Data Acquisition

### Script: `get_data.py`

The `get_data.py` script downloads all available data from the public D&D 5e API into local JSON files.

### Responsibilities

- fetch the top-level API index from `/api`
- enumerate all top-level endpoints
- walk paginated results using the `next` field
- follow each item’s `url` to retrieve the full object when available
- save one JSON file per endpoint
- save a master metadata file for reproducibility and debugging

### Key implementation details

- retry handling with backoff
- optional throttling between requests
- normalization of relative vs. absolute URLs
- endpoint-level metadata tracking
- one output directory: `dnd5eapi_dump/`

### Output

The script produces:

- endpoint files such as `spells.json`, `conditions.json`, etc.
- `_api_index.json`
- `_dump_meta.json`

This forms the raw local corpus used for later preprocessing.

## 4. Retrieval and Indexing Pipeline

### Notebook: `pipeline.ipynb`

The retrieval/indexing logic was initially developed in a notebook for rapid experimentation.

### Responsibilities

- load locally dumped D&D data
- transform structured JSON records into retrieval-friendly text chunks
- attach metadata to each chunk
- generate embeddings
- store embeddings and metadata in local Qdrant
- test RAG behavior with example queries

### Typical metadata stored per chunk

- `name`
- `category`
- `chunk_id`
- `url`
- `index`

This metadata is important because it allows the backend to return sources and support traceback.

### Embedding model

The current implementation uses:

- `OpenAIEmbeddings(model="text-embedding-3-small")`

### Vector store

The current implementation uses Qdrant in local persistence mode:

```python
QdrantClient(path="./qdrant_local")
```

This choice was convenient for MVP development because it avoided provisioning a separate vector database service.

## 5. Backend Implementation

### File: `app.py`

The backend is implemented with FastAPI.

### Startup behavior

At startup, the application:

1. loads environment variables from `si699.env`
2. initializes the embedding model
3. opens the local Qdrant store
4. loads a Qdrant vector store wrapper
5. initializes the LLM
6. exposes the API routes

### Models used

- **Embedding model:** `text-embedding-3-small`
- **Chat model:** `gpt-4o-mini`

### Vector store configuration

The app currently uses a local Qdrant collection named:

```text
damage_types
```

This means the live retrieval scope is narrower than a full SRD-wide assistant, but it is sufficient for demonstrating the end-to-end architecture.

## 6. Retrieval-Augmented Generation Flow

The core query flow works like this:

### Step 1: Receive a question
The frontend sends a POST request to `/api/qa` with:

```json
{
  "question": "user question",
  "k": 3
}
```

### Step 2: Similarity search
The backend calls vector similarity search over the local Qdrant collection.

### Step 3: Build retrieved context
The retrieved chunks are formatted into a prompt-ready context string.

### Step 4: Prompt the LLM
The backend uses a strict prompt template that tells the model to:

- answer only from retrieved context
- say it does not know if the answer is absent from context
- output JSON with:
  - `short`
  - `steps`

### Step 5: Parse and return
The response is parsed into:

- `short`
- `steps`
- `sources`

Each source includes the original chunk text and metadata.

## 7. API Design

### `GET /`
Returns the frontend HTML file.

Used to serve the interactive demo interface from the same FastAPI process.

### `GET /health`
Simple liveness endpoint.

Used to verify that the backend is up and responding.

Example:

```json
{"status":"ok"}
```

### `POST /api/qa`
Main question-answering endpoint.

### Request schema

```json
{
  "question": "What is fire damage?",
  "k": 3
}
```

### Response schema

```json
{
  "short": "One-sentence answer",
  "steps": ["step 1", "step 2", "step 3"],
  "sources": [
    {
      "name": "Fire",
      "chunk_id": "damage-types_fire",
      "category": "damage-types",
      "url": "https://www.dnd5eapi.co/api/2014/damage-types/fire",
      "text": "..."
    }
  ]
}
```

### Design note

The inclusion of `sources` was intentional and supports the second project goal: traceback to original retrieved content.

## 8. Frontend Integration

### File: `2.0website.html`

The frontend is a static HTML interface served by the backend.

### Responsibilities

- collect a user question
- submit it to the backend
- display:
  - short answer
  - step-by-step explanation
  - optionally retrieved evidence

### UX direction

The current UI is intentionally lightweight. It prioritizes showing the RAG pipeline working end to end rather than providing a polished production experience.

The presence of evidence/source handling makes it easy to extend into a richer citation or traceback interface in future iterations.

## 9. AWS Deployment

The project was later deployed to AWS EC2.

### Deployed components

- FastAPI app
- static HTML frontend
- local `qdrant_local/` directory
- local corpus files
- environment file

### Why this deployment model was chosen

This deployment strategy kept the system simple:

- one server
- one Python process
- one local vector store bundled with the app

It also made the project more relevant to AWS-oriented roles by demonstrating practical experience with:

- EC2
- remote environment setup
- file transfer
- service startup
- testing through API endpoints

## 10. Real Engineering Challenges Encountered

This project involved several practical issues beyond the ideal architecture.

### A. Package compatibility on Amazon Linux 2
The default Python version on the EC2 instance was too old for the required dependency set, so a newer Python had to be installed manually.

### B. Dependency version conflicts
There were compatibility issues between newer LangChain package lines and the Qdrant integration package, requiring a version combination that matched the older `langchain-core` line.

### C. Local Qdrant file locking
Qdrant local mode created repeated file-locking issues whenever multiple processes attempted to access the same `qdrant_local/` directory.

This happened during:
- notebook usage
- FastAPI app startup
- development reload workflows

### D. SQLite compatibility on EC2
Qdrant local persistence also interacted with the host SQLite version in ways that required special handling during deployment.

### Engineering takeaway
These issues reinforced an important lesson: local mode is excellent for demos and prototypes, but a production-ready system should use a standalone vector database service instead of sharing one local persistence directory across processes.

## 11. Security Considerations

### Secrets management
The application loads the OpenAI API key from `si699.env`.

This file must remain local and should never be committed to the repository.

### GitHub push protection
At one point, GitHub blocked a push because an OpenAI API key was included in `si699.env`. This highlighted the importance of:

- keeping secrets out of source control
- using `.gitignore`
- committing `.env.example` instead
- rotating exposed secrets immediately

Recommended `.gitignore` entries:

```gitignore
si699.env
.venv/
__pycache__/
```

## 12. Known Limitations

### Limited indexed scope
The live app currently points to a collection named `damage_types`, which is narrower than a complete SRD-wide assistant.

### Notebook dependency
The indexing workflow still depends on `pipeline.ipynb`, which is convenient for development but not ideal for reproducibility or deployment.

### Local vector store architecture
Using local Qdrant mode introduces operational constraints and file-locking risks.

### Simple frontend
The current frontend is designed as an MVP and does not yet include a richer citation or interaction experience.

## 13. Future Improvements

### Data / indexing
- move notebook logic into a standalone indexing script
- make ingestion reproducible from a single command
- expand the indexed corpus beyond the current collection

### Retrieval / generation
- tune chunking and retrieval parameters
- improve structured answer formatting
- add better prompt robustness and failure handling

### Frontend
- improve evidence rendering
- support inline citations or expandable source cards
- improve UX and responsiveness

### Infrastructure
- replace local Qdrant mode with a standalone Qdrant service
- add containerization
- add deployment automation
- use managed secret storage instead of local env files

## 14. Summary

The D&D 5e Rules Assistant is a compact but realistic applied AI system.

It demonstrates how to go from:
- raw external data
- to local preprocessing
- to vector retrieval
- to structured LLM answers
- to an interactive deployed application

Although the current implementation is intentionally lightweight, it captures many of the practical concerns that appear in real-world AI application development, including environment management, retrieval architecture, source grounding, deployment tradeoffs, and repository security.
