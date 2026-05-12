import time
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from database import database
from route import router

# 1. Setup terminal logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Orchestrator")

@asynccontextmanager
async def lifespan(app: FastAPI):
    await database.connect()
    yield
    await database.disconnect()

app = FastAPI(title="MFI Orchestrator V1", lifespan=lifespan)

# 2. Middleware for logging requests
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = (time.time() - start_time) * 1000
    
    # Logs Method, Path, Status, and Time (e.g., GET /client/BT776655 200 45ms)
    logger.info(
        f"Method: {request.method} Path: {request.url.path} "
        f"Status: {response.status_code} Time: {process_time:.2f}ms"
    )
    return response

app.include_router(router)