# Technical Implementation: D&D 5e Rules Assistant

## 1. Introduction

This document describes the technical implementation of the D&D 5e Rules Assistant, a lightweight retrieval-augmented generation (RAG) system for question answering over a Dungeons & Dragons 5e rules corpus.

The system was developed as a minimal end-to-end prototype and later deployed on AWS EC2. It includes:

- raw data acquisition from the D&D 5e API
- local preprocessing and embedding generation
- local vector storage with Qdrant
- FastAPI-based serving layer
- a lightweight static frontend for interaction
- role-based prompt selection (Player vs. Dungeon Master)
- source traceback and evidence display
- a persistent EC2 service setup using `systemd`

## 2. System Architecture

The application has three major layers:

### A. Data Acquisition Layer
Responsible for downloading and organizing the raw corpus.

### B. Retrieval / Indexing Layer
Responsible for preprocessing, chunking, embedding, and storing vectorized content.

### C. Serving Layer
Responsible for API exposure, retrieval at query time, role-aware LLM prompting, and returning structured responses to the frontend.

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
- follow each item's `url` to retrieve the full object when available
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
QdrantClient(path="./qdrant_local", force_disable_check_same_thread=True)
```

This choice was convenient for MVP development because it avoided provisioning a separate vector database service, while the extra flag was needed to work around SQLite thread-check behavior on the deployed EC2 environment.

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
6. defines role-specific prompt templates
7. exposes the API routes

### Models used

- **Embedding model:** `text-embedding-3-small`
- **Chat model:** `gpt-4o-mini`

### Vector store configuration

The app currently uses a local Qdrant collection named:

```text
damage_types
```

This means the live retrieval scope is narrower than a full SRD-wide assistant, but it is sufficient for demonstrating the end-to-end architecture.

## 6. Role-Based Prompt Design

### Overview

The backend maintains two separate prompt templates, one for each supported role:

- `"player"` — intended for D&D players asking about what their character can do
- `"dm"` — intended for Dungeon Masters adjudicating rules at the table

The role is passed in as part of the API request and controls which prompt template is used. The retrieval step is identical for both roles. Only the prompt framing changes.

### Player prompt framing

The player prompt instructs the LLM to:

- focus on practical gameplay advice
- describe what the character can do
- use simple, action-oriented language

### DM prompt framing

The DM prompt instructs the LLM to:

- focus on rule details and edge cases
- explain how to make fair rulings
- be precise about the specific mechanics involved

### Implementation

```python
PROMPTS = {
    "player": PromptTemplate(...),
    "dm": PromptTemplate(...),
}

def rag_pipeline(query, k=3, role="player"):
    docs = retrieve_chunks(query, k)
    context = build_context(docs)
    prompt_template = PROMPTS.get(role, PROMPTS["player"])
    prompt = prompt_template.format(context=context, question=query)
    ...
```

### Why this design

Separating prompts by role is a lightweight way to make the same retrieved content more useful to different types of users without changing the retrieval architecture. It also demonstrates a practical pattern for role-aware or persona-aware LLM applications.

## 7. Retrieval-Augmented Generation Flow

The core query flow works like this:

### Step 1: Receive a question
The frontend sends a POST request to `/api/qa` with:

```json
{
  "question": "user question",
  "k": 3,
  "role": "player"
}
```

### Step 2: Similarity search
The backend calls vector similarity search over the local Qdrant collection.

### Step 3: Build retrieved context
The retrieved chunks are formatted into a prompt-ready context string.

### Step 4: Select prompt by role
The backend selects the appropriate prompt template based on the `role` field.

### Step 5: Prompt the LLM
The backend uses the selected prompt template that tells the model to:

- answer only from retrieved context
- say it does not know if the answer is absent from context
- output JSON with:
  - `short`
  - `steps`

### Step 6: Parse and return
The response is parsed into:

- `short`
- `steps`
- `sources`

Each source includes the original chunk text and metadata, with a corrected URL pointing to the original D&D 5e API entry.

## 8. Source URL Construction

### Problem

The raw `url` field stored in Qdrant metadata was constructed incorrectly during indexing. The endpoint name and item index were concatenated without a `/` separator, producing malformed URLs such as:

```text
https://www.dnd5eapi.co/api/2014/conditionsgrappled
```

### Solution

The backend reconstructs the URL at serve time using the `chunk_id` field, which follows a reliable `category_index` format:

```python
def build_url(doc) -> str:
    chunk_id = doc.metadata.get("chunk_id", "")
    parts = chunk_id.split("_", 1)
    if len(parts) == 2:
        return f"https://www.dnd5eapi.co/api/{parts[0]}/{parts[1]}"
    return doc.metadata.get("url", "")
```

This produces correctly formed URLs such as:

```text
https://www.dnd5eapi.co/api/conditions/grappled
```

### Engineering note

This is an example of a data quality issue that only surfaces at serving time. Fixing it in the serving layer rather than re-indexing was the pragmatic choice for a demo, but a production system should fix it at the indexing stage.

## 9. API Design

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
  "k": 3,
  "role": "player"
}
```

`role` defaults to `"player"` if not provided.

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

The inclusion of `sources` was intentional and supports the second project goal: traceback to original retrieved content. The `role` field supports the third goal: role-aware answer framing.

## 10. Frontend Integration

### File: `2.0website.html`

The frontend is a static HTML interface served by the backend.

### Responsibilities

- collect a user question
- allow the user to select their role (Player or Dungeon Master)
- submit the question and role to the backend
- display:
  - short answer
  - step-by-step explanation
  - optionally retrieved evidence with source links

### Role selector

The frontend includes two toggle buttons for role selection. The selected role is tracked in a JavaScript variable and included in every API request:

```javascript
let currentRole = "player";

document.querySelectorAll(".role-btn").forEach(btn => {
    btn.addEventListener("click", () => {
        document.querySelectorAll(".role-btn").forEach(b => b.classList.remove("active-role"));
        btn.classList.add("active-role");
        currentRole = btn.dataset.role;
    });
});
```

### Evidence panel behavior

When a new question is submitted, the frontend now clears any existing `evidencePanel` before rendering the next answer. This prevents stale evidence cards from remaining on screen after the short answer and step list have already changed.

When evidence is available, the frontend displays a collapsible panel showing the retrieved passages and a direct link to the original source entry on the D&D 5e API.

### UX direction

The current UI is intentionally lightweight. It prioritizes showing the RAG pipeline working end to end rather than providing a polished production experience.

## 11. AWS Deployment

The project was later deployed to AWS EC2.

### Deployed components

- FastAPI app
- static HTML frontend
- local `qdrant_local/` directory
- local corpus files
- environment file

### Service model

The deployed app runs as a `systemd` service (`dndbot`) so it continues serving after terminal disconnects, SSH logout, or local IDE shutdown.

Typical commands:

```bash
sudo systemctl status dndbot --no-pager
sudo systemctl restart dndbot
sudo journalctl -u dndbot -n 50 --no-pager
```

### Why this deployment model was chosen

This deployment strategy kept the system simple:

- one server
- one Python process
- one local vector store bundled with the app

It also made the project more relevant to AWS-oriented roles by demonstrating practical experience with:

- EC2
- security group configuration
- remote environment setup
- file transfer via SCP
- service startup and log inspection
- persistent service management with `systemd`

## 12. Real Engineering Challenges Encountered

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
Qdrant local persistence also interacted with the host SQLite version in ways that required special handling during deployment. In this project, the deployed app used `force_disable_check_same_thread=True` to avoid the SQLite pragma/thread-check failure encountered on EC2.

### E. LLM JSON formatting
The LLM occasionally wrapped its JSON response in markdown code fences or added extra text, causing parse failures. This was handled by extracting the JSON block with a regex before parsing:

```python
match = re.search(r'\{.*\}', raw, re.DOTALL)
parsed = json.loads(match.group()) if match else {}
```

### F. Browser caching during frontend updates
After frontend edits, stale browser cache sometimes made it look like the evidence panel fix was not working. A hard refresh was needed to confirm the new HTML was actually being served.

### Engineering takeaway

These issues reinforced an important lesson: local mode is excellent for demos and prototypes, but a production-ready system should use a standalone vector database service instead of sharing one local persistence directory across processes.

## 13. Security Considerations

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

## 14. Known Limitations

### Limited indexed scope
The live app currently points to a collection named `damage_types`, which is narrower than a complete SRD-wide assistant.

### Notebook dependency
The indexing workflow still depends on `pipeline.ipynb`, which is convenient for development but not ideal for reproducibility or deployment.

### Local vector store architecture
Using local Qdrant mode introduces operational constraints and file-locking risks.

### Simple frontend
The current frontend is designed as an MVP and does not yet include a richer citation or interaction experience.

## 15. Future Improvements

### Data / indexing
- move notebook logic into a standalone indexing script
- make ingestion reproducible from a single command
- expand the indexed corpus beyond the current collection

### Retrieval / generation
- tune chunking and retrieval parameters
- improve structured answer formatting
- add better prompt robustness and failure handling

### Role system
- add more role types beyond Player and DM (e.g. new player, rules lawyer)
- allow per-role retrieval weighting or re-ranking

### Frontend
- improve evidence rendering
- support inline citations or expandable source cards
- improve UX and responsiveness

### Infrastructure
- replace local Qdrant mode with a standalone Qdrant service
- add containerization
- add deployment automation
- use managed secret storage instead of local env files

## 16. Summary

The D&D 5e Rules Assistant is a compact but realistic applied AI system.

It demonstrates how to go from:
- raw external data
- to local preprocessing
- to vector retrieval
- to role-aware structured LLM answers
- to an interactive deployed application

Although the current implementation is intentionally lightweight, it captures many of the practical concerns that appear in real-world AI application development, including environment management, retrieval architecture, role-aware prompt design, source grounding, deployment tradeoffs, frontend state management, and repository security.
