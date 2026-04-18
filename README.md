# D&D 5e Rules Assistant

A lightweight retrieval-augmented generation (RAG) demo for Dungeons & Dragons 5e rules question answering.

This project combines a static frontend, a FastAPI backend, a local Qdrant vector store, and OpenAI models to answer rules questions over a D&D rules corpus. It was built as an end-to-end MVP to demonstrate corpus collection, vector search, LLM-based response generation, and lightweight deployment on AWS EC2.

## Project Goals

This project was built with three main goals:

1. **Build and deploy a minimal working D&D rules bot**
   - collect domain data
   - build a local retrieval pipeline
   - serve a working QA interface through a web app

2. **Support traceback to original source content**
   - return retrieved passages from the backend
   - enable source/evidence display in the frontend
   - make answers more inspectable and grounded

3. **Support role-based answer framing**
   - allow users to select their role (Player or Dungeon Master)
   - adjust the LLM prompt based on role context
   - give players action-oriented answers and DMs ruling-oriented answers

## Demo Features

- Ask natural-language D&D 5e rules questions
- Select your role: **Player** or **Dungeon Master**
- Retrieve relevant passages from a local vector store
- Generate a short answer plus a step-by-step breakdown tailored to the selected role
- Return supporting source snippets for evidence display
- Link directly to original source entries on the D&D 5e API
- Serve frontend and backend from a single FastAPI application
- Validate deployment through a simple health check endpoint

## Tech Stack

- **Backend:** FastAPI
- **Frontend:** static HTML / JavaScript
- **Embeddings:** OpenAI `text-embedding-3-small`
- **LLM:** OpenAI `gpt-4o-mini`
- **Vector Store:** Qdrant local mode
- **Retrieval Layer:** LangChain + QdrantVectorStore
- **Corpus Source:** D&D 5e API dump
- **Deployment:** AWS EC2

## Project Structure

```text
.
├── app.py
├── 2.0website.html
├── get_data.py
├── pipeline.ipynb
├── dnd5eapi_dump/
├── qdrant_local/
├── si699.env
├── README.md
└── TECHNICAL_IMPLEMENTATION.md
```

## How It Works

At a high level, the system works as follows:

1. `get_data.py` downloads D&D 5e API data into local JSON files.
2. `pipeline.ipynb` preprocesses the corpus, creates embeddings, and stores them in a local Qdrant collection.
3. `app.py` loads the embedding model, local Qdrant store, and chat model at startup.
4. When a user submits a question, the backend:
   - embeds the query
   - retrieves top-k similar chunks from Qdrant
   - builds a context string from the retrieved chunks
   - selects a prompt template based on the user's role
   - prompts the LLM to answer in a strict JSON format
   - returns the answer plus supporting sources

## Current API

### `GET /`

Serves the static frontend HTML page.

### `GET /health`

Simple health check endpoint.

Example response:

```json
{"status":"ok"}
```

### `POST /api/qa`

Accepts a question, optional retrieval count `k`, and optional `role`.

`role` can be `"player"` (default) or `"dm"`.

Example request:

```json
{
  "question": "What is fire damage?",
  "k": 3,
  "role": "player"
}
```

Example response:

```json
{
  "short": "Fire damage is a type of damage associated with flames, commonly dealt by red dragons and various spells.",
  "steps": [
    "Identify the source of fire damage, such as red dragons or fire spells.",
    "Recognize that it involves flames causing harm.",
    "Understand that it is one of the damage types in Dungeons & Dragons."
  ],
  "sources": [
    {
      "name": "Fire",
      "chunk_id": "damage-types_fire",
      "category": "damage-types",
      "url": "https://www.dnd5eapi.co/api/2014/damage-types/fire",
      "text": "Red dragons breathe fire, and many spells conjure flames to deal fire damage."
    }
  ]
}
```

### Role-based prompting

When `role` is `"player"`, the LLM is instructed to focus on practical gameplay advice and what the character can do.

When `role` is `"dm"`, the LLM is instructed to focus on rule details, edge cases, and how to make fair rulings at the table.

The retrieved context is the same in both cases. Only the prompt framing changes.

## Data Pipeline

### 1. Download raw corpus

The `get_data.py` script downloads all data from the D&D 5e API into local JSON files.

What it does:

- fetches the API index at `/api`
- walks each endpoint, including pagination
- follows item-level `url` fields to retrieve full objects
- saves one JSON file per endpoint under `dnd5eapi_dump/`
- saves metadata files for reproducibility

### 2. Build embeddings and vector store

The notebook `pipeline.ipynb` is used to:

- read local dumped JSON data
- transform objects into text chunks
- attach metadata such as `name`, `category`, `chunk_id`, and `url`
- embed the chunks
- insert them into a local Qdrant collection
- test retrieval with example queries

### 3. Run the app

The FastAPI app loads the vector store and answers questions through `/api/qa`.

## Local Setup

### 1. Create a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install fastapi uvicorn python-dotenv
pip install langchain-openai langchain-qdrant qdrant-client
pip install requests tqdm pandas jupyter
```

Depending on your environment, you may also want to pin versions for compatibility.

### 3. Add environment variables

Create a local file named `si699.env`:

```env
OPENAI_API_KEY=your_openai_api_key
```

### 4. Download the raw corpus

```bash
python get_data.py
```

### 5. Build the local vector store

Open and run:

```bash
jupyter notebook pipeline.ipynb
```

This should create the local `qdrant_local/` directory.

### 6. Start the backend

```bash
python app.py
```

Then visit:

```text
http://127.0.0.1:8000
```

## Deployment

This project was deployed as a small AWS EC2 demo.

### Deployment layout

Files uploaded to the server included:

- `app.py`
- `2.0website.html`
- `qdrant_local/`
- `dnd5eapi_dump/`
- `si699.env`

### Why EC2

AWS EC2 was chosen because it keeps the deployment simple while also making the project more relevant for cloud-focused roles. The app runs as a small Python service, and the local Qdrant persistence is bundled with the project files.

## Current Limitations

- The current live collection is limited in scope relative to a full SRD-wide assistant.
- The indexing workflow still depends on a notebook rather than a production ingestion script.
- Qdrant local mode is convenient for demos but can cause file-locking issues during development.
- The frontend is intentionally lightweight and optimized for MVP/demo use.

## Future Improvements

- expand the indexed corpus beyond the current scope
- move notebook logic into a standalone indexing script
- improve source traceback UX in the frontend
- add inline evidence rendering instead of a basic evidence panel
- replace local Qdrant mode with a standalone Qdrant service
- add automated deployment and better secret management
- add more role types beyond Player and DM

## Security Notes

Do **not** commit secrets.

The project uses a local `si699.env` file for API credentials. This file should be kept local and excluded from Git.

Recommended `.gitignore` entries:

```gitignore
si699.env
.venv/
__pycache__/
```

You can also add an example env file for collaborators:

```env
OPENAI_API_KEY=your_key_here
```

## Why This Project Matters

This project is intentionally small, but it demonstrates an end-to-end applied AI workflow:

- data ingestion
- preprocessing
- embeddings
- vector retrieval
- structured LLM prompting
- role-aware prompt design
- backend API design
- frontend integration
- cloud deployment

It is a practical example of how to turn a prototype notebook into a working interactive application.
