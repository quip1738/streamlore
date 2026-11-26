
import os
import json
import base64
import secrets
import httpx

from urllib.parse import urlparse, quote

from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import HTMLResponse
from pydantic import BaseModel


app = FastAPI(title="StreamLore", version="0.6.0")


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

VISION_MODEL = os.getenv(
    "STREAMLORE_VISION_MODEL",
    "nemotron-3-nano-omni-reasoning",
)

FREELLMAPI_URL = os.getenv(
    "FREELLMAPI_URL",
    "https://freellmapi.streamlore.prod.page/v1",
).rstrip("/")

FREELLMAPI_KEY = os.getenv("FREELLMAPI_KEY", "")
INTERNAL_TOKEN = os.getenv("STREAMLORE_INTERNAL_TOKEN", "")

GITHUB_TOKEN = os.getenv("STREAMLORE_GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("STREAMLORE_GITHUB_REPO", "")
ACCESS_CODE = os.getenv("STREAMLORE_ACCESS_CODE", "")

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

BUCKET = "streamlore-clips"


# --------------------------------------------------
# REQUEST MODELS
# --------------------------------------------------

class JobRequest(BaseModel):
    video_url: str
    access_code: str


class JobStatusRequest(BaseModel):
    job_id: str
    access_code: str


class FrameRequest(BaseModel):
    image_base64: str
    mime_type: str = "image/jpeg"


# --------------------------------------------------
# SUPABASE HELPERS
# --------------------------------------------------

def supabase_headers(prefer=None):
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }

    if prefer:
        headers["Prefer"] = prefer

    return headers


async def update_job(job_id, values):
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError("Supabase is not configured.")

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.patch(
            f"{SUPABASE_URL}/rest/v1/jobs",
            params={"id": f"eq.{job_id}"},
            headers=supabase_headers(),
            json=values,
        )

    response.raise_for_status()


async def get_job(job_id):
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{SUPABASE_URL}/rest/v1/jobs",
            params={
                "id": f"eq.{job_id}",
                "select": (
                    "id,status,clip_path,title,"
                    "description,error_message,created_at"
                ),
            },
            headers=supabase_headers(),
        )

    response.raise_for_status()

    rows = response.json()

    if not rows:
        return None

    return rows[0]


async def create_clip_link(storage_path):
    if not storage_path:
        return None

    # Only allow paths belonging to this application's bucket.
    if not storage_path.startswith(""):
        raise RuntimeError("Invalid clip storage path.")

    encoded_path = quote(storage_path, safe="/")

    url = (
        f"{SUPABASE_URL}/storage/v1/object/sign/"
        f"{BUCKET}/{encoded_path}"
    )

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            url,
            headers=supabase_headers(),
            json={"expiresIn": 3600},
        )

    response.raise_for_status()

    data = response.json()
    signed_url = data.get("signedURL") or data.get("signedUrl")

    if not signed_url:
        raise RuntimeError("Supabase did not return a signed clip URL.")

    if signed_url.startswith("http://") or signed_url.startswith("https://"):
        return signed_url

    if signed_url.startswith("/storage/v1/"):
        return SUPABASE_URL + signed_url

    if signed_url.startswith("/"):
        return SUPABASE_URL + "/storage/v1" + signed_url

    return SUPABASE_URL + "/storage/v1/" + signed_url.lstrip("/")


def verify_access_code(code):
    return bool(
        ACCESS_CODE
        and code
        and secrets.compare_digest(code, ACCESS_CODE)
    )


# --------------------------------------------------
# HEALTH
# --------------------------------------------------

@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "service": "StreamLore",
        "version": "0.6.0",
        "github_configured": bool(GITHUB_TOKEN and GITHUB_REPO),
        "vision_configured": bool(FREELLMAPI_KEY and VISION_MODEL),
        "internal_token_configured": bool(INTERNAL_TOKEN),
        "supabase_configured": bool(SUPABASE_URL and SUPABASE_KEY),
    }


# --------------------------------------------------
# DASHBOARD
# --------------------------------------------------

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
* {
    box-sizing: border-box;
}

body {
    margin: 0;
    min-height: 100vh;
    background: #090b12;
    color: #f5f5f7;
    font-family: Arial, sans-serif;
    padding: 30px 18px;
}

main {
    width: 100%;
    max-width: 760px;
    margin: 30px auto;
    background: #121622;
    border: 1px solid #252c3c;
    border-radius: 18px;
    padding: 32px;
}

h1 {
    margin-top: 15px;
    font-size: 36px;
}

p {
    color: #aab2c5;
    line-height: 1.6;
}

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

button:disabled {
    opacity: .5;
    cursor: wait;
}

.tag {
    display: inline-block;
    padding: 6px 10px;
    border-radius: 20px;
    background: #211b3d;
    color: #c4b5fd;
    font-size: 12px;
}

.panel {
    margin-top: 24px;
    padding: 18px;
    border: 1px solid #252c3c;
    border-radius: 12px;
    background: #090d17;
    display: none;
}

.status {
    display: inline-block;
    padding: 6px 10px;
    border-radius: 20px;
    background: #211b3d;
    color: #c4b5fd;
    font-size: 13px;
    text-transform: capitalize;
}

.error {
    color: #fca5a5;
}

video {
    display: block;
    width: 100%;
    max-height: 650px;
    margin-top: 16px;
    border-radius: 10px;
    background: black;
}

.small {
    font-size: 12px;
    color: #778198;
    overflow-wrap: anywhere;
}

.divider {
    border: 0;
    border-top: 1px solid #252c3c;
    margin: 28px 0;
}
</style>
</head>

<body>
<main>

<span class="tag">GTA VI CLIP GENERATOR</span>

<h1>StreamLore</h1>

<p>
Turn gaming VODs into vertical highlight clips.
Submit a Twitch, YouTube, or Kick VOD and let
StreamLore process it in the cloud.
</p>

<form id="clipForm">

<label for="video">VOD URL</label>
<input
    id="video"
    type="url"
    placeholder="Paste your Twitch, YouTube, or Kick VOD link"
    required
>

<label for="code">Beta access code</label>
<input
    id="code"
    type="password"
    placeholder="Enter your access code"
    required
>

<button id="submit" type="submit">
Generate Clips
</button>

</form>

<section class="panel" id="jobPanel">

<h2>Your Clip Job</h2>

<p>
<span class="status" id="jobStatus">Queued</span>
</p>

<p id="jobMessage">Waiting for updates...</p>

<p class="small" id="jobId"></p>

<div id="clipArea"></div>

</section>

<hr class="divider">

<p class="small">
StreamLore beta · GTA VI highlights · Cloud processing
</p>

</main>

<script>
const form = document.getElementById("clipForm");
const button = document.getElementById("submit");
const panel = document.getElementById("jobPanel");
const statusLabel = document.getElementById("jobStatus");
const message = document.getElementById("jobMessage");
const jobIdLabel = document.getElementById("jobId");
const clipArea = document.getElementById("clipArea");

let polling = false;

function showError(text) {
    message.textContent = text;
    message.className = "error";
}

async function checkJob(jobId, accessCode) {
    const response = await fetch("/api/jobs/status", {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({
            job_id: jobId,
            access_code: accessCode
        })
    });

    const data = await response.json();

    if (!response.ok) {
        throw new Error(data.detail || "Could not retrieve job status.");
    }

    statusLabel.textContent = data.status;
    jobIdLabel.textContent = "Job ID: " + data.job_id;

    if (data.status === "queued") {
        message.textContent = "Your job is waiting for a cloud worker.";
    }

    if (data.status === "processing") {
        message.textContent = "Your VOD is being analyzed and processed.";
    }

    if (data.status === "failed") {
        showError(data.error_message || "The job could not be completed.");
        return true;
    }

    if (data.status === "completed") {
        message.textContent = "Your GTA VI highlight is ready.";

        if (data.clip_url) {
            clipArea.innerHTML = "";

            const video = document.createElement("video");
            video.controls = true;
            video.playsInline = true;
            video.src = data.clip_url;

            clipArea.appendChild(video);

            const note = document.createElement("p");
            note.className = "small";
            note.textContent =
                "This private clip link expires after one hour. " +
                "Refresh the job status to request another link.";

            clipArea.appendChild(note);
        } else {
            message.textContent =
                "The job completed, but a playable clip link " +
                "could not be created. Please refresh the job status.";
        }

        return true;
    }

    return false;
}

async function pollJob(jobId, accessCode) {
    if (polling) return;
    polling = true;

    try {
        while (true) {
            const finished = await checkJob(jobId, accessCode);

            if (finished) break;

            await new Promise(resolve => setTimeout(resolve, 10000));
        }
    } catch (error) {
        showError(error.message);
    } finally {
        polling = false;
    }
}

form.addEventListener("submit", async (event) => {
    event.preventDefault();

    button.disabled = true;
    button.textContent = "Submitting...";

    panel.style.display = "block";
    clipArea.innerHTML = "";
    message.className = "";
    message.textContent = "Submitting your VOD...";

    const videoUrl = document.getElementById("video").value;
    const accessCode = document.getElementById("code").value;

    try {
        const response = await fetch("/api/jobs", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                video_url: videoUrl,
                access_code: accessCode
            })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || "Unable to submit job.");
        }

        statusLabel.textContent = data.status;
        jobIdLabel.textContent = "Job ID: " + data.job_id;
        message.textContent = "Your VOD was submitted successfully.";

        button.textContent = "Job Submitted";

        pollJob(data.job_id, accessCode);

    } catch (error) {
        showError(error.message);
        button.disabled = false;
        button.textContent = "Generate Clips";
    }
});
</script>

</body>
</html>
"""


# --------------------------------------------------
# CREATE JOB
# --------------------------------------------------

@app.post("/api/jobs")
async def create_job(request: JobRequest):

    if not verify_access_code(request.access_code):
        raise HTTPException(
            status_code=401,
            detail="Invalid access code.",
        )

    if not SUPABASE_URL or not SUPABASE_KEY:
        raise HTTPException(
            status_code=503,
            detail="Supabase is not configured.",
        )

    if not GITHUB_TOKEN or not GITHUB_REPO:
        raise HTTPException(
            status_code=503,
            detail="Cloud worker is not configured.",
        )

    parsed = urlparse(request.video_url)
    host = (parsed.hostname or "").lower()

    allowed_hosts = (
        "twitch.tv",
        "youtube.com",
        "youtu.be",
        "kick.com",
    )

    if parsed.scheme not in ("http", "https") or not any(
        host == domain or host.endswith("." + domain)
        for domain in allowed_hosts
    ):
        raise HTTPException(
            status_code=400,
            detail="Only Twitch, YouTube, and Kick VOD links are supported.",
        )

    # Create persistent job record.
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            db_response = await client.post(
                f"{SUPABASE_URL}/rest/v1/jobs",
                headers=supabase_headers("return=representation"),
                json={
                    "source_url": request.video_url,
                    "status": "queued",
                },
            )

        db_response.raise_for_status()
        rows = db_response.json()

        if not rows:
            raise RuntimeError("Supabase did not return a job record.")

        job_id = rows[0]["id"]

    except Exception:
        raise HTTPException(
            status_code=502,
            detail="Could not create the job in Supabase.",
        )

    # Dispatch GitHub Actions workflow.
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
        "inputs": {
            "video_url": request.video_url,
            "job_id": str(job_id),
        },
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                endpoint,
                headers=headers,
                json=payload,
            )

        if response.status_code != 204:
            await update_job(
                job_id,
                {
                    "status": "failed",
                    "error_message": "GitHub could not start the worker.",
                },
            )

            raise HTTPException(
                status_code=502,
                detail="GitHub could not start the cloud worker.",
            )

    except HTTPException:
        raise

    except Exception:
        await update_job(
            job_id,
            {
                "status": "failed",
                "error_message": "Could not dispatch the cloud worker.",
            },
        )

        raise HTTPException(
            status_code=502,
            detail="Could not dispatch the cloud worker.",
        )

    return {
        "status": "queued",
        "job_id": str(job_id),
        "message": "VOD submitted to the cloud worker.",
    }


# --------------------------------------------------
# JOB STATUS AND PRIVATE CLIP LINK
# --------------------------------------------------

@app.post("/api/jobs/status")
async def job_status(request: JobStatusRequest):

    if not verify_access_code(request.access_code):
        raise HTTPException(
            status_code=401,
            detail="Invalid access code.",
        )

    if not SUPABASE_URL or not SUPABASE_KEY:
        raise HTTPException(
            status_code=503,
            detail="Supabase is not configured.",
        )

    try:
        job = await get_job(request.job_id)

    except Exception:
        raise HTTPException(
            status_code=502,
            detail="Could not retrieve job status.",
        )

    if not job:
        raise HTTPException(
            status_code=404,
            detail="Job not found.",
        )

    clip_url = None

    if job["status"] == "completed" and job.get("clip_path"):
        expected_prefix = f"{request.job_id}/"

        if not job["clip_path"].startswith(expected_prefix):
            raise HTTPException(
                status_code=500,
                detail="Invalid clip storage path.",
            )

        try:
            clip_url = await create_clip_link(job["clip_path"])

        except Exception:
            clip_url = None

    return {
        "job_id": job["id"],
        "status": job["status"],
        "title": job.get("title"),
        "description": job.get("description"),
        "error_message": job.get("error_message"),
        "clip_url": clip_url,
    }


# --------------------------------------------------
# INTERNAL VISION ANALYSIS
# --------------------------------------------------

@app.post("/api/internal/analyze-frame")
async def analyze_frame(
    request: FrameRequest,
    x_internal_token: str = Header(default=""),
):

    if not INTERNAL_TOKEN or not secrets.compare_digest(
        x_internal_token,
        INTERNAL_TOKEN,
    ):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized.",
        )

    if not FREELLMAPI_KEY:
        raise HTTPException(
            status_code=503,
            detail="Vision API is not configured.",
        )

    if request.mime_type not in (
        "image/jpeg",
        "image/png",
        "image/webp",
    ):
        raise HTTPException(
            status_code=400,
            detail="Unsupported image type.",
        )

    try:
        image_bytes = base64.b64decode(
            request.image_base64,
            validate=True,
        )
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Invalid base64 image.",
        )

    if not image_bytes or len(image_bytes) > 5 * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail="Image must be between 1 byte and 5 MB.",
        )

    image_data = (
        f"data:{request.mime_type};base64,{request.image_base64}"
    )

    prompt = """
You are analyzing a frame from a GTA VI livestream VOD.

Return ONLY one valid JSON object.
Do not use markdown or code fences.

Evaluate BOTH:
1. Whether a streamer facecam is visible.
2. Whether this frame appears to show an exciting or potentially
   engaging moment worth examining as a short-form gaming clip.

Use this exact JSON structure:

{
  "highlight_score": 0,
  "reason": "Brief explanation of the visual moment",
  "facecam_detected": false,
  "facecam_bbox": null,
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
- If detected, facecam_bbox must use normalized coordinates from
  0 to 1, measured relative to the full image:
  {"x":0.0,"y":0.0,"width":0.0,"height":0.0}
- The box must tightly contain the facecam panel, not just the face.
- If no facecam is visible, set facecam_bbox to null.
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
                    {
                        "type": "text",
                        "text": prompt,
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": image_data,
                        },
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
            detail="Vision provider returned an error.",
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
            detail="Vision provider returned invalid JSON.",
        )

    return {
        "status": "success",
        "model": VISION_MODEL,
        "analysis": json.dumps(parsed_result),
    }
