import logging
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router
from app.core.config import settings
from app.services.scheduler import start_scheduler, stop_scheduler

import os

LOG_DIR = Path("/app/logs") if Path("/app").is_dir() else Path("logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)
try:
    os.chmod(LOG_DIR, 0o777)
except OSError:
    pass
LOG_FILE = LOG_DIR / "error.log"
if not LOG_FILE.exists():
    LOG_FILE.touch()
try:
    os.chmod(LOG_FILE, 0o666)
except OSError:
    pass

_file_handler = RotatingFileHandler(
    LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
)
_file_handler.setFormatter(
    logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
)

error_logger = logging.getLogger("b2cagent.errors")
error_logger.setLevel(logging.ERROR)
if not error_logger.handlers:
    error_logger.addHandler(_file_handler)
    error_logger.propagate = False

otp_logger = logging.getLogger("b2cagent.otp")
otp_logger.setLevel(logging.INFO)
if not otp_logger.handlers:
    otp_logger.addHandler(_file_handler)
    otp_logger.propagate = False

app = FastAPI(title="b2cagent API", version="0.1.0")


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    error_logger.error(
        "Unhandled error on %s %s\n%s",
        request.method,
        request.url.path,
        tb,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": f"{type(exc).__name__}: {exc}"},
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if settings.STORAGE_BACKEND == "local":
    upload_dir = Path(settings.LOCAL_UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    app.mount(
        "/uploads", StaticFiles(directory=str(upload_dir)), name="uploads"
    )

app.include_router(api_router)


@app.on_event("startup")
async def _on_startup() -> None:
    start_scheduler()


@app.on_event("shutdown")
async def _on_shutdown() -> None:
    await stop_scheduler()


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": "b2cagent", "status": "running"}
