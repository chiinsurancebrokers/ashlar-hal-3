from __future__ import annotations

from fastapi import FastAPI, Header
from backend.app.core.broker_access import broker_authorized
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
        "case_store": __import__("backend.app.core.durable_store", fromlist=["storage_status"]).storage_status(),
        "independent_deployment_ready": False,
        "independent_deployment_note": (
            "The FastAPI boundary is standalone. SQLite persistence is single-volume. "
            "Use shared durable persistence before running HAL and the orchestrator "
            "as separate production services."
        ),
    }


@app.post("/v1/handle")
async def handle(req: AdviserHandleRequest, x_admin_password: str | None = Header(default=None, alias="X-Admin-Password")):
    result = await dispatch_adviser_request(req, is_broker=broker_authorized(x_admin_password))
    return JSONResponse(
        content=result.model_dump(mode="json"),
        headers={"Cache-Control": "no-store"},
    )
