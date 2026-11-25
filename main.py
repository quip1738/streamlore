
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="StreamLore API",
    description="Cloud-based GTA VI AI clipping platform",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://streamlore.prod.page",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)


@app.get("/")
async def home():
    return {
        "app": "StreamLore",
        "status": "online",
        "purpose": "GTA VI AI clipping platform",
    }


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "freellmapi_configured": bool(
            os.getenv("FREELLMAPI_URL")
            and os.getenv("FREELLMAPI_API_KEY")
        ),
    }
