
import os
import re
import base64
import binascii
import secrets
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field


app = FastAPI(
    title="StreamLore API",
    version="0.3.0",
)

VISION_MODEL = os.getenv(
    "STREAMLORE_VISION_MODEL",
    "nemotron-3-nano-omni-reasoning"
)

ALLOWED_HOSTS = {
    "twitch.tv",
    "www.twitch.tv",
    "youtube.com",
    "www.youtube.com",
    "youtu.be",
    "m.youtube.com",
    "kick.com",
    "www.kick.com",
}

DASHBOARD = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>StreamLore — AI Gaming Highlights</title>
<style>
* { box-sizing: border-box; }

body {
    margin: 0;
    background: #090b12;
    color: #f5f5f7;
    font-family: Arial, sans-serif;
    min-height: 100vh;
}

header {
    padding: 22px 7%;
    border-bottom: 1px solid #242735;
    font-size: 23px;
    font-weight: bold;
}

header span { color: #a78bfa; }

main {
    max-width: 850px;
    margin: 75px auto;
    padding: 24px;
}

.tag {
    color: #a78bfa;
    font-size: 13px;
    letter-spacing: 2px;
    text-transform: uppercase;
}

h1 {
    font-size: clamp(36px, 7vw, 55px);
    line-height: 1.08;
    margin: 15px 0;
}

p {
    color: #a1a1aa;
    line-height: 1.7;
}

.panel {
    background: #141722;
    border: 1px solid #292d3d;
    border-radius: 16px;
    padding: 25px;
    margin-top: 30px;
}

label {
    display: block;
    margin: 18px 0 8px;
    color: #d4d4d8;
    font-size: 14px;
}

input {
    width: 100%;
    padding: 15px;
    background: #090b12;
    color: white;
    border: 1px solid #383c4c;
    border-radius: 9px;
    font-size: 15px;
}

button {
    width: 100%;
    margin-top: 20px;
    padding: 15px;
    border: 0;
    border-radius: 9px;
    background: #8b5cf6;
    color: white;
    font-size: 16px;
    font-weight: bold;
    cursor: pointer;
}

button:disabled {
    opacity: .5;
    cursor: wait;
}

.status {
    margin-top: 18px;
    padding: 12px;
    border-radius: 8px;
    background: #090b12;
    color: #c4b5fd;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
}

.features {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 12px;
    margin-top: 25px;
}

.feature {
    padding: 17px;
    background: #141722;
    border: 1px solid #292d3d;
    border-radius: 12px;
}

.feature strong { color: #c4b5fd; }

footer {
    margin-top: 65px;
    color: #71717a;
    font-size: 13px;
    text-align: center;
}

</style>
</head>

<body>
<header>Stream<span>Lore</span></header>

<main>
    <div class="tag">AI Gaming Highlights</div>

    <h1>Your stream.<br>Our intelligence.</h1>

    <p>
        Turn GTA VI livestreams into exciting vertical gaming
        highlights. StreamLore is building an AI-powered clipping
        platform designed to find the moments worth watching.
    </p>

    <div class="features">
        <div class="feature">
            <strong>AI Detection</strong>
            <p>Find interesting moments in your VOD.</p>
        </div>
        <div class="feature">
            <strong>Vertical Clips</strong>
            <p>Streamer on top, gameplay underneath.</p>
        </div>
        <div class="feature">
            <strong>Smart Captions</strong>
            <p>Prepare clips for short-form platforms.</p>
        </div>
    </div>

    <div class="panel">
        <h2>Generate GTA VI Clips</h2>

        <p>
            Submit a Twitch, YouTube, or Kick VOD.
        </p>

        <form id="jobForm">
            <label for="videoUrl">VOD URL</label>
            <input
                id="videoUrl"
                type="url"
                placeholder="https://www.twitch.tv/videos/..."
                required
            >

            <label for="accessCode">Beta access code</label>
            <input
                id="accessCode"
                type="password"
                placeholder="Enter your access code"
                required
            >

            <button id="submitButton" type="submit">
                Generate Clips
            </button>
        </form>

        <div id="status" class="status">
            Ready to receive your VOD.
        </div>
    </div>

    <footer>
        StreamLore © 2026 · AI Gaming Highlights
    </footer>
</main>

<script>
const form = document.getElementById("jobForm");
const button = document.getElementById("submitButton");
const statusBox = document.getElementById("status");

form.addEventListener("submit", async (event) => {
    event.preventDefault();

    button.disabled = true;
    button.textContent = "Submitting...";
    statusBox.textContent = "Sending your VOD to StreamLore...";

    try {
        const response = await fetch("/api/jobs", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                video_url: document.getElementById("videoUrl").value,
                access_code: document.getElementById("accessCode").value
            })
        });

        const result = await response.json();

        if (!response.ok) {
            throw new Error(result.detail || "Could not submit job.");
        }

        statusBox.textContent =
            "Job submitted successfully.\\n" +
            "Your VOD has been sent to the cloud worker.\\n" +
            "Job ID: " + result.job_id;

        form.reset();

    } catch (error) {
        statusBox.textContent = "Error: " + error.message;
    } finally {
        button.disabled = false;
        button.textContent = "Generate Clips";
    }
});
</script>

</body>
</html>
"""


class JobRequest(BaseModel):
    video_url: str = Field(min_length=10, max_length=2048)
    access_code: str = Field(min_length=1, max_length=256)


class FrameRequest(BaseModel):
    image_base64: str = Field(min_length=20, max_length=7_000_000)
    mime_type: str = "image/jpeg"


def check_access_code(code: str):
    expected = os.getenv("STREAMLORE_ACCESS_CODE", "")

    if not expected or not secrets.compare_digest(code, expected):
        raise HTTPException(
            status_code=401,
            detail="Invalid beta access code."
        )


def validate_vod_url(value: str) -> str:
    parsed = urlparse(value.strip())

    if parsed.scheme != "https":
        raise HTTPException(
            status_code=400,
            detail="Only HTTPS video URLs are accepted."
        )

    hostname = (parsed.hostname or "").lower()

    if hostname not in ALLOWED_HOSTS:
        raise HTTPException(
            status_code=400,
            detail="Only Twitch, YouTube, and Kick URLs are supported."
        )

    return value.strip()


def get_freellmapi_url() -> str:
    base = os.getenv("FREELLMAPI_URL", "").rstrip("/")

    if not base:
        raise HTTPException(
            status_code=503,
            detail="AI service URL is not configured."
        )

    if base.endswith("/v1"):
        return base + "/chat/completions"

    return base + "/v1/chat/completions"


@app.get("/", response_class=HTMLResponse)
async def home():
    return HTMLResponse(DASHBOARD)


@app.get("/api/health")
async def health():
    return {
        "app": "StreamLore",
        "status": "healthy",
        "github_configured": bool(
            os.getenv("STREAMLORE_GITHUB_TOKEN")
            and os.getenv("STREAMLORE_GITHUB_REPO")
        ),
        "vision_configured": bool(
            os.getenv("FREELLMAPI_URL")
            and os.getenv("FREELLMAPI_API_KEY")
        ),
    }


@app.post("/api/jobs")
async def create_job(request: JobRequest):
    check_access_code(request.access_code)

    video_url = validate_vod_url(request.video_url)

    github_token = os.getenv("STREAMLORE_GITHUB_TOKEN", "")
    repository = os.getenv(
        "STREAMLORE_GITHUB_REPO",
        "quip1738/streamlore"
    )

    if not github_token:
        raise HTTPException(
            status_code=503,
            detail="Cloud worker is not configured."
        )

    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise HTTPException(
            status_code=500,
            detail="Invalid GitHub repository configuration."
        )

    owner, repo = repository.split("/", 1)

    dispatch_url = (
        f"https://api.github.com/repos/{owner}/{repo}"
        "/actions/workflows/streamlore-worker.yml/dispatches"
    )

    payload = {
        "ref": "main",
        "inputs": {
            "video_url": video_url
        }
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                dispatch_url,
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {github_token}",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                json=payload,
            )

        if response.status_code not in (200, 204):
            raise HTTPException(
                status_code=502,
                detail=(
                    "GitHub could not start the cloud worker. "
                    "Check the repository Actions permissions and workflow."
                )
            )

        return {
            "status": "submitted",
            "job_id": secrets.token_hex(8),
            "message": "Your VOD was submitted to the StreamLore cloud worker."
        }

    except httpx.RequestError:
        raise HTTPException(
            status_code=502,
            detail="Could not connect to the cloud worker."
        )


@app.post("/api/internal/analyze-frame")
async def analyze_frame(
    request: FrameRequest,
    x_internal_token: str = Header(default="")
):
    expected_token = os.getenv(
        "STREAMLORE_INTERNAL_TOKEN",
        ""
    )

    if not expected_token or not secrets.compare_digest(
        x_internal_token,
        expected_token
    ):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized."
        )

    if request.mime_type not in (
        "image/jpeg",
        "image/png",
        "image/webp"
    ):
        raise HTTPException(
            status_code=400,
            detail="Unsupported image format."
        )

    encoded = request.image_base64.strip()

    if encoded.startswith("data:"):
        try:
            header, encoded = encoded.split(",", 1)
            if request.mime_type not in header:
                raise ValueError("MIME mismatch")
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Invalid image data URL."
            )

    try:
        image_bytes = base64.b64decode(
            encoded,
            validate=True
        )
    except (binascii.Error, ValueError):
        raise HTTPException(
            status_code=400,
            detail="Invalid base64 image."
        )

    if not image_bytes or len(image_bytes) > 5_000_000:
        raise HTTPException(
            status_code=413,
            detail="Image must be smaller than 5 MB."
        )

    api_key = os.getenv("FREELLMAPI_API_KEY", "")

    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="Vision API key is not configured."
        )

    image_url = (
        f"data:{request.mime_type};base64,{encoded}"
    )

    prompt = """
You are analyzing a frame from a GTA VI livestream.

Find the streamer's facecam/webcam overlay, if one exists.

Return ONLY valid JSON with this structure:

{
  "facecam_detected": true,
  "facecam_box": {
    "x": 0.0,
    "y": 0.0,
    "width": 0.0,
    "height": 0.0
  },
  "confidence": 0.0,
  "description": "Brief description of the detected region"
}

Coordinates must be normalized from 0 to 1 relative to the
full image. The origin (0,0) is the top-left corner.

The bounding box must cover the entire facecam overlay,
not just the person's face.

If there is no clearly identifiable facecam, return
facecam_detected as false and facecam_box as null.

Do not mistake an in-game character, portrait, mirror,
or poster for the streamer.
"""

    payload = {
        "model": VISION_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": image_url,
                            "detail": "high"
                        }
                    }
                ]
            }
        ],
        "stream": False
    }

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                get_freellmapi_url(),
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json=payload
            )

        if response.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=(
                    "Vision provider returned an error. "
                    "Check the enabled vision models and provider limits."
                )
            )

        result = response.json()
        content = result["choices"][0]["message"]["content"]

        return {
            "status": "success",
            "model": result.get("model", VISION_MODEL),
            "analysis": content
        }

    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="Vision analysis timed out."
        )

    except httpx.RequestError:
        raise HTTPException(
            status_code=502,
            detail="Could not connect to FreeLLMAPI."
        )

    except (KeyError, IndexError, TypeError, ValueError):
        raise HTTPException(
            status_code=502,
            detail="Unexpected response from the vision provider."
        )
