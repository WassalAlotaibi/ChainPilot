
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.database.connection import (
    init_db,
    get_db
)
from backend.database.seed import seed_database

from backend.api.inventory import (
    router as inventory_router
)
from backend.api.suppliers import (
    router as suppliers_router
)
from backend.api.policies import (
    router as policies_router
)
from backend.api.procurement import (
    router as procurement_router
)
from backend.api.agent import (
    router as agent_router
)
from backend.api.supplier_events import (
    router as supplier_events_router
)
from backend.api.demo import (
    router as demo_router
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    seed_database()
    yield


app = FastAPI(
    title="ChainPilot API",
    description=(
        "Policy-Aware Autonomous "
        "Supply Chain Intelligence"
    ),
    version="0.4.0",
    lifespan=lifespan
)


app.include_router(inventory_router)
app.include_router(suppliers_router)
app.include_router(policies_router)
app.include_router(procurement_router)
app.include_router(agent_router)
app.include_router(supplier_events_router)
app.include_router(demo_router)


@app.get("/")
def home():
    return {
        "project": "ChainPilot",
        "version": "0.4.0",
        "status": "running"
    }


@app.get("/health")
def health():
    return {
        "status": "healthy"
    }


@app.get("/activity")
def get_activity():
    with get_db() as db:
        rows = db.execute(
            """
            SELECT *
            FROM agent_logs
            ORDER BY id DESC
            LIMIT 200
            """
        ).fetchall()

        return [
            dict(row)
            for row in rows
        ]
