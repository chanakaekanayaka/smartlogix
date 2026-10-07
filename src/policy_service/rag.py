"""
The Policy Agent's retrieval core: ChromaDB + RAG over the policy documents.

Uses ChromaDB's built-in local embedding model (all-MiniLM-L6-v2, downloaded
once automatically) - no external embeddings API key needed.
"""

import re
from pathlib import Path

import chromadb

from src.config import DATA_DIR
from src.llm import call_llm

CHROMA_PATH = DATA_DIR / "chroma_db"
COLLECTION_NAME = "policies"

_client = chromadb.PersistentClient(path=str(CHROMA_PATH))


def get_collection():
    return _client.get_or_create_collection(COLLECTION_NAME)


def _chunk_markdown(text: str) -> list[str]:
    """Splits a policy document into paragraph-level chunks for retrieval."""
    parts = re.split(r"\n\s*\n", text.strip())
    return [p.strip() for p in parts if len(p.strip()) > 20]


def ingest_policies() -> int:
    """Reads every .md file in data/policies/ and (re)builds the vector index."""
    collection = get_collection()
    # Reset so re-running ingest.py doesn't duplicate chunks.
    existing_ids = collection.get()["ids"]
    if existing_ids:
        collection.delete(ids=existing_ids)

    ids, documents, metadatas = [], [], []
    policies_dir = DATA_DIR / "policies"
    for path in sorted(policies_dir.glob("*.md")):
        chunks = _chunk_markdown(path.read_text(encoding="utf-8"))
        for i, chunk in enumerate(chunks):
            ids.append(f"{path.stem}_{i}")
            documents.append(chunk)
            metadatas.append({"source": path.name})

    collection.add(ids=ids, documents=documents, metadatas=metadatas)
    return len(ids)


SUMMARY_SYSTEM_PROMPT = """You are the Policy Agent of a Sri Lankan logistics
assistant. Answer the customer's question using ONLY the policy excerpts
given below. If the excerpts do not contain the answer, say you are not sure
and recommend contacting human support. Cite which policy the answer comes
from by name. Keep the answer under 100 words."""


def retrieve(query: str, k: int = 3) -> tuple[list[str], list[str]]:
    """Pure vector search, no LLM - returns (chunks, sources) in rank order.
    Kept separate from retrieve_and_answer() so retrieval quality can be
    evaluated on its own (see evaluation/run_evaluation.py)."""
    results = get_collection().query(query_texts=[query], n_results=k)
    chunks = results["documents"][0] if results["documents"] else []
    sources = [m["source"] for m in results["metadatas"][0]] if results["metadatas"] else []
    return chunks, sources


def retrieve_and_answer(query: str, k: int = 3) -> dict:
    chunks, sources = retrieve(query, k)

    if not chunks:
        return {"answer": "No relevant policy found.", "sources": [], "chunks": []}

    context = "\n\n".join(f"[{src}] {chunk}" for src, chunk in zip(sources, chunks))
    answer = call_llm(SUMMARY_SYSTEM_PROMPT, f"Question: {query}\n\nPolicy excerpts:\n{context}")

    return {"answer": answer, "sources": list(dict.fromkeys(sources)), "chunks": chunks}
