from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from backend.app.api.adviser import AdviserHandleRequest, dispatch_adviser_request
from backend.app.api.journey import router as journey_router
from backend.app.core.config import get_settings
from backend.app.core.rate_limit import SimpleRateLimitMiddleware


settings = get_settings()

app = FastAPI(
    title="Ashlar Orchestrator",
    version="1.0.0",
    description=(
        "Dedicated Adviser OS coordination service. It owns workflow routing and "
        "specialist sequencing but never calls an LLM directly."
    ),
)

app.add_middleware(
    SimpleRateLimitMiddleware,
    limited_prefixes=("/v1/handle", "/v1/journey"),
    max_requests=30,
    window_seconds=60,
)

app.include_router(journey_router, prefix="/v1")


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "ashlar-orchestrator",
        "specialists": [
            "hal_adviser",
            "document_analyst",
            "proposal_writer",
            "health_navigator",
        ],
        "deterministic_engines": [
            "quote_engine",
            "document_evidence_engine",
            "fact_ledger",
            "policy_engine",
        ],
        "case_store": "process_local",
        "independent_deployment_ready": False,
        "independent_deployment_note": (
            "The FastAPI boundary is standalone, but cases remain process-local. "
            "Use shared durable persistence before running HAL and the orchestrator "
            "as separate production services."
        ),
    }


@app.post("/v1/handle")
async def handle(req: AdviserHandleRequest):
    result = await dispatch_adviser_request(req)
    return JSONResponse(
        content=result.model_dump(mode="json"),
        headers={"Cache-Control": "no-store"},
    )
