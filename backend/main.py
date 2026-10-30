
from contextlib import asynccontextmanager
from fastapi import FastAPI

from backend.database.connection import init_db
from backend.database.seed import seed_database
from backend.api.inventory import router as inventory_router
from backend.api.suppliers import router as suppliers_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    seed_database()
    yield


app = FastAPI(
    title="ChainPilot API",
    description="Autonomous Supply Chain Intelligence",
    version="0.1.0",
    lifespan=lifespan
)

app.include_router(inventory_router)
app.include_router(suppliers_router)


@app.get("/")
def home():
    return {
        "project": "ChainPilot",
        "status": "running",
        "version": "0.1.0"
    }


@app.get("/health")
def health():
    return {"status": "healthy"}
