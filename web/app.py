"""FastAPI backend: wraps orchestrator.Orchestrator so a browser can generate (and,
from Phase 3 on, chat-edit) a report over HTTP instead of the one-shot CLI.

A single Orchestrator instance is shared across requests -- it holds the long-lived
MCP server connections (stdio subprocesses) and the in-memory report_sessions dict.
That's fine for a single-user education project; a production multi-tenant version
would need per-connection isolation and a real session store instead.
"""

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from dashboard.render import sections_to_payload
from orchestrator import Orchestrator

orch = Orchestrator()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await orch.connect()
    try:
        yield
    finally:
        await orch.close()


app = FastAPI(title="C360", lifespan=lifespan)

# Dev-only: the Vite dev server (Phase 1) runs on a different origin than uvicorn.
# From Phase 2 on, the built frontend is served by FastAPI itself (same origin),
# so this only matters for local `npm run dev` + `uvicorn --reload` workflows.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ReportRequest(BaseModel):
    query: str


@app.post("/api/reports")
async def create_report(req: ReportRequest):
    session_id = str(uuid.uuid4())
    reply_text, state = await orch.run_turn(session_id, req.query)
    return {
        "session_id": session_id,
        "reply": reply_text,
        "sections": sections_to_payload(state.sections),
    }


@app.get("/api/reports/{session_id}")
async def get_report(session_id: str):
    state = orch.report_sessions.get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session_id": session_id, "sections": sections_to_payload(state.sections)}
