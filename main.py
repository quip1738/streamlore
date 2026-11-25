
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

app = FastAPI(
    title="StreamLore API",
    description="Cloud-based GTA VI AI clipping platform",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://streamlore.prod.page"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)

BASE_DIR = Path(__file__).resolve().parent


@app.get("/")
async def home():
    return FileResponse(BASE_DIR / "index.html")


@app.get("/api/health")
async def health():
    return {
        "app": "StreamLore",
        "status": "healthy",
        "freellmapi_configured": bool(
            os.getenv("FREELLMAPI_URL")
            and os.getenv("FREELLMAPI_API_KEY")
        ),
    }
