"""
Policy Agent exposed as its own FastAPI microservice - this is the one
agent-to-agent call that goes over real HTTP instead of an in-process
function call, so it's the concrete example for the "agent communication
protocol" requirement and the target for the "IR and Security" individual
assessment (Student 4): auth, authorization, API security, retrieval
accuracy/manipulation can all be tested directly against this service.

Run with:
    uvicorn src.policy_service.main:app --port 8002
"""

import time
from collections import defaultdict

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from src.config import POLICY_API_KEY
from src.policy_service.rag import retrieve_and_answer
from src.utils.logger import log_agent_event

app = FastAPI(title="SmartLogix Policy Agent")

# Very small in-memory rate limiter: max 20 requests per key per 60 seconds.
_RATE_LIMIT = 20
_RATE_WINDOW_SECONDS = 60
_request_log: dict[str, list[float]] = defaultdict(list)


class RetrieveRequest(BaseModel):
    query: str
    session_id: str = "-"


def _check_rate_limit(api_key: str):
    now = time.time()
    recent = [t for t in _request_log[api_key] if now - t < _RATE_WINDOW_SECONDS]
    recent.append(now)
    _request_log[api_key] = recent
    if len(recent) > _RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")


@app.post("/retrieve")
def retrieve(req: RetrieveRequest, x_api_key: str = Header(default="")):
    if x_api_key != POLICY_API_KEY:
        log_agent_event("policy_agent", "auth_failed",
                         {"provided_key_prefix": x_api_key[:6]}, session_id=req.session_id)
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

    _check_rate_limit(x_api_key)

    result = retrieve_and_answer(req.query)
    log_agent_event("policy_agent", "retrieval", {"query": req.query, "result": result},
                     session_id=req.session_id)
    return result


@app.get("/health")
def health():
    return {"status": "ok"}
