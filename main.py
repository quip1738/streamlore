import os
import json
import base64
import secrets
import httpx

from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from urllib.parse import urlparse

app = FastAPI(title="StreamLore", version="0.4.0")

VISION_MODEL = os.getenv(
    "STREAMLORE_VISION_MODEL",
    "nemotron-3-nano-omni-reasoning"
)

FREELLMAPI_URL = os.getenv(
    "FREELLMAPI_URL",
    "https://freellmapi.streamlore.prod.page/v1"
).rstrip("/")

FREELLMAPI_KEY = os.getenv("FREELLMAPI_KEY", "")
INTERNAL_TOKEN = os.getenv("STREAMLORE_INTERNAL_TOKEN", "")

GITHUB_TOKEN = os.getenv("STREAMLORE_GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("STREAMLORE_GITHUB_REPO", "")
ACCESS_CODE = os.getenv("STREAMLORE_ACCESS_CODE", "")

app_url = os.getenv("STREAMLORE_PUBLIC_URL", "https://streamlore.prod.page")


class JobRequest(BaseModel):
    video_url: str
    access_code: str


class FrameRequest(BaseModel):
    image_base64: str
    mime_type: str = "image/jpeg"


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "service": "StreamLore",
        "version": "0.4.0",
        "github_configured": bool(GITHUB_TOKEN and GITHUB_REPO),
        "vision_configured": bool(FREELLMAPI_KEY and VISION_MODEL),
        "internal_token_configured": bool(INTERNAL_TOKEN),
    }


@app.get("/", response_class=HTMLResponse)
async def home():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>StreamLore — AI Gaming Clips</title>
      <style>
        * { box-sizing: border-box; }
        body {
          margin: 0;
          min-height: 100vh;
          background: #090b12;
          color: #f5f5f7;
          font-family: Arial, sans-serif;
          display: flex;
          align-items: center;
          justify-content: center;
          padding: 24px;
        }
        main {
          width: 100%;
          max-width: 620px;
          background: #121622;
          border: 1px solid #252c3c;
          border-radius: 18px;
          padding: 32px;
        }
        h1 { margin-top: 0; font-size: 34px; }
        p { color: #aab2c5; line-height: 1.6; }
        label {
          display: block;
          margin: 20px 0 8px;
          color: #dce1ed;
          font-size: 14px;
        }
        input {
          width: 100%;
          padding: 14px;
          border-radius: 9px;
          border: 1px solid #343d51;
          background: #090d17;
          color: white;
          font-size: 15px;
        }
        button {
          width: 100%;
          margin-top: 22px;
          padding: 15px;
          border: 0;
          border-radius: 9px;
          background: #8b5cf6;
          color: white;
          font-weight: bold;
          font-size: 16px;
          cursor: pointer;
        }
        button:disabled { opacity: .5; cursor: wait; }
        #result {
          margin-top: 20px;
          padding: 14px;
          border-radius: 9px;
          background: #090d17;
          white-space: pre-wrap;
          color: #cbd5e1;
          display: none;
        }
        .tag {
          display: inline-block;
          padding: 6px 10px;
          border-radius: 20px;
          background: #211b3d;
          color: #c4b5fd;
          font-size: 12px;
        }
      </style>
    </head>
    <body>
      <main>
        <span class="tag">GTA VI CLIP GENERATOR</span>
        <h1>StreamLore</h1>
        <p>
          Turn gaming VODs into vertical highlight clips.
          Paste a Twitch, YouTube, or Kick VOD link to submit a job.
        </p>

        <form id="clipForm">
          <label for="video">VOD URL</label>
          <input id="video" type="url" placeholder="Paste your VOD link" required>

          <label for="code">Beta access code</label>
          <input id="code" type="password" placeholder="Enter your access code" required>

          <button id="submit" type="submit">Generate Clips</button>
        </form>

        <div id="result"></div>
      </main>

      <script>
        const form = document.getElementById("clipForm");
        const button = document.getElementById("submit");
        const result = document.getElementById("result");

        form.addEventListener("submit", async (event) => {
          event.preventDefault();
          button.disabled = true;
          button.textContent = "Submitting...";
          result.style.display = "block";
          result.textContent = "Submitting your VOD to the cloud worker...";

          try {
            const response = await fetch("/api/jobs", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                video_url: document.getElementById("video").value,
                access_code: document.getElementById("code").value
              })
            });

            const data = await response.json();

            if (!response.ok) {
              throw new Error(data.detail || "Unable to submit job.");
            }

            result.textContent =
              "Your VOD was submitted.\\nJob ID: " + data.job_id +
              "\\n\\nThis early version does not yet provide live job tracking or a clip dashboard.";
          } catch (error) {
            result.textContent = "Error: " + error.message;
          } finally {
            button.disabled = false;
            button.textContent = "Generate Clips";
          }
        });
      </script>
    </body>
    </html>
    """


@app.post("/api/jobs")
async def create_job(request: JobRequest):
    if not ACCESS_CODE or not secrets.compare_digest(
        request.access_code, ACCESS_CODE
    ):
        raise HTTPException(status_code=401, detail="Invalid access code.")

    if not GITHUB_TOKEN or not GITHUB_REPO:
        raise HTTPException(
            status_code=503,
            detail="Cloud worker is not configured."
        )

    parsed = urlparse(request.video_url)
    host = (parsed.hostname or "").lower()

    allowed_hosts = (
        "twitch.tv",
        "youtube.com",
        "youtu.be",
        "kick.com",
    )

    if not any(host == domain or host.endswith("." + domain)
               for domain in allowed_hosts):
        raise HTTPException(
            status_code=400,
            detail="Only Twitch, YouTube, and Kick VOD links are supported."
        )

    endpoint = (
        f"https://api.github.com/repos/{GITHUB_REPO}"
        "/actions/workflows/streamlore-worker.yml/dispatches"
    )

    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    payload = {
        "ref": "main",
        "inputs": {"video_url": request.video_url},
    }

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            endpoint,
            headers=headers,
            json=payload,
        )

    if response.status_code != 204:
        raise HTTPException(
            status_code=502,
            detail="GitHub could not start the cloud worker."
        )

    return {
        "status": "submitted",
        "job_id": secrets.token_hex(8),
        "message": "VOD submitted to the cloud worker.",
    }


@app.post("/api/internal/analyze-frame")
async def analyze_frame(
    request: FrameRequest,
    x_internal_token: str = Header(default=""),
):
    if not INTERNAL_TOKEN or not secrets.compare_digest(
        x_internal_token, INTERNAL_TOKEN
    ):
        raise HTTPException(status_code=401, detail="Unauthorized.")

    if not FREELLMAPI_KEY:
        raise HTTPException(
            status_code=503,
            detail="Vision API is not configured."
        )

    if request.mime_type not in (
        "image/jpeg",
        "image/png",
        "image/webp",
    ):
        raise HTTPException(
            status_code=400,
            detail="Unsupported image type."
        )

    try:
        image_bytes = base64.b64decode(
            request.image_base64,
            validate=True,
        )
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Invalid base64 image."
        )

    if not image_bytes or len(image_bytes) > 5 * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail="Image must be between 1 byte and 5 MB."
        )

    image_data = (
        f"data:{request.mime_type};base64,{request.image_base64}"
    )

    prompt = """
You are analyzing a frame from a GTA VI livestream VOD.

Return ONLY one valid JSON object. Do not use markdown or code fences.

Evaluate BOTH:
1. Whether a streamer facecam is visible.
2. Whether this frame appears to show an exciting or potentially
   engaging moment worth examining as a short-form gaming clip.

Use this exact JSON structure:

{
  "highlight_score": 0,
  "reason": "Brief explanation of the visual moment",
  "facecam_detected": false,
  "facecam_box": null,
  "facecam_confidence": 0.0,
  "description": "Brief description of the facecam or why none is visible"
}

Rules:
- highlight_score must be an integer from 0 to 10.
- Score only what is visually supported by this single frame.
- Do not invent action, dialogue, reactions, or events outside the frame.
- A static menu, loading screen, starting soon screen, or ordinary
  uneventful gameplay should receive a low score.
- High scores should be reserved for visually clear, unusual,
  intense, dramatic, or potentially entertaining gameplay moments.
- facecam_detected must be true only when a real streamer webcam
  panel is visibly present.
- If detected, facecam_box must use normalized coordinates from
  0 to 1, measured relative to the full image:
  {"x":0.0,"y":0.0,"width":0.0,"height":0.0}
- The box must tightly contain the facecam panel, not just the face.
- If no facecam is visible, set facecam_box to null.
- facecam_confidence must be a number from 0 to 1.
- Do not guess a facecam location.
"""

    api_url = (
        FREELLMAPI_URL + "/chat/completions"
        if FREELLMAPI_URL.endswith("/v1")
        else FREELLMAPI_URL + "/v1/chat/completions"
    )

    headers = {
        "Authorization": f"Bearer {FREELLMAPI_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": VISION_MODEL,
        "temperature": 0.1,
        "max_tokens": 500,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": image_data},
                    },
                ],
            }
        ],
    }

    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.post(
            api_url,
            headers=headers,
            json=payload,
        )

    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail="Vision provider returned an error."
        )

    try:
        result = response.json()
        content = result["choices"][0]["message"]["content"]

        if isinstance(content, list):
            content = "".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict)
            )

        content = content.strip()

        if content.startswith("```"):
            content = content.split("\n", 1)[-1]
            content = content.rsplit("```", 1)[0].strip()

        parsed_result = json.loads(content)

    except Exception:
        raise HTTPException(
            status_code=502,
            detail="Vision provider returned invalid JSON."
        )

    return {
        "status": "success",
        "model": VISION_MODEL,
        "analysis": json.dumps(parsed_result),
    }
