"""
Run this once (and again any time the policy documents change) to build the
ChromaDB vector index used by the Policy Agent:

    python -m src.policy_service.ingest
"""

from src.policy_service.rag import ingest_policies

if __name__ == "__main__":
    count = ingest_policies()
    print(f"Indexed {count} policy chunks into ChromaDB.")
