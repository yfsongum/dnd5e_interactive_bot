from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_qdrant import QdrantVectorStore
from langchain_core.prompts import PromptTemplate
from qdrant_client import QdrantClient

import os
import json

# ── Load env ──────────────────────────────────────────────────────────────────
load_dotenv("si699.env")

# ── Models & vectorstore (loaded once at startup) ─────────────────────────────
embedding_model = OpenAIEmbeddings(model="text-embedding-3-small")
qdrant_client   = QdrantClient(path="./qdrant_local")

vectorstore = QdrantVectorStore(
    client=qdrant_client,
    collection_name="damage_types",
    embedding=embedding_model,
)

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

rag_prompt = PromptTemplate(
    input_variables=["context", "question"],
    template="""
You are a helpful Dungeons & Dragons 5e rules assistant.

Use only the retrieved context below to answer the question.
If the answer is not in the context, say "I don't know based on the retrieved context."

Retrieved Context:
{context}

Question:
{question}

Reply in this exact JSON format with no extra text:
{{
  "short": "one sentence summary of the answer",
  "steps": ["step 1", "step 2", "step 3"]
}}
""".strip(),
)

# ── RAG helpers ───────────────────────────────────────────────────────────────
def retrieve_chunks(query: str, k: int = 3):
    return vectorstore.similarity_search(query, k=k)

def build_context(docs) -> str:
    parts = []
    for i, doc in enumerate(docs, 1):
        parts.append(
            f"[Chunk {i} | {doc.metadata.get('chunk_id')} | {doc.metadata.get('name')}]\n"
            f"{doc.page_content}"
        )
    return "\n\n".join(parts)

def rag_pipeline(query: str, k: int = 3):
    docs    = retrieve_chunks(query, k)
    context = build_context(docs)
    prompt  = rag_prompt.format(context=context, question=query)
    raw     = llm.invoke(prompt).content

    try:
        parsed = json.loads(raw)
        short  = parsed.get("short", raw)
        steps  = parsed.get("steps", [])
    except Exception:
        short  = raw
        steps  = []

    sources = [
        {
            "name": doc.metadata.get("name", ""),
            "chunk_id": doc.metadata.get("chunk_id", ""),
            "category": doc.metadata.get("category", ""),
            "url": doc.metadata.get("url", "").replace("/api/2014/", "/api/2014/").replace(
                doc.metadata.get("category", "") + doc.metadata.get("index", ""),
                doc.metadata.get("category", "") + "/" + doc.metadata.get("index", "")
            ),
            "text": doc.page_content,
        }
        for doc in docs
    ]

    return short, steps, sources
# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(title="D&D 5e Rules Assistant")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class QARequest(BaseModel):
    question: str
    k: int = 3

class SourceItem(BaseModel):
    name:     str
    chunk_id: str
    category: str
    url:      str
    text:     str

class QAResponse(BaseModel):
    short:   str
    steps:   list[str]
    sources: list[SourceItem]


@app.post("/api/qa", response_model=QAResponse)
def qa_endpoint(req: QARequest):
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")
    short, steps, sources = rag_pipeline(req.question, req.k)
    return QAResponse(short=short, steps=steps, sources=sources)

@app.get("/health")
def health():
    return {"status": "ok"}

# ── Serve the frontend HTML ───────────────────────────────────────────────────
import os

@app.get("/")
def serve_frontend():
    return FileResponse(os.path.join(os.path.dirname(__file__), "2.0website.html"))
# ── Run ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)