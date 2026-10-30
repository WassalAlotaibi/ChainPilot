
import logging
import os

from fastapi import APIRouter, HTTPException

from backend.agents.supply_agent import run_supply_agent

router = APIRouter(prefix="/agent", tags=["AI Agent"])
logger = logging.getLogger(__name__)


@router.post("/run")
def run_agent():
    if not os.getenv("GEMINI_API_KEY"):
        raise HTTPException(
            status_code=503,
            detail="GEMINI_API_KEY is not configured"
        )

    try:
        return run_supply_agent()

    except Exception:
        logger.exception("Gemini agent failed")
        raise HTTPException(
            status_code=502,
            detail=(
                "Gemini agent failed. "
                "Check the backend terminal for details."
            )
        )
