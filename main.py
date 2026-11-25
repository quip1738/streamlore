
import os
import secrets
import httpx

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse

app = FastAPI(
    title="StreamLore API",
    version="0.1.0",
)

DASHBOARD = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>StreamLore | AI Clipper</title>
<style>
* { box-sizing: border-box; }
body {
  margin: 0;
  background: #090b10;
  color: #f4f5f8;
  font-family: Inter, system-ui, sans-serif;
}
header {
  height: 76px;
  border-bottom: 1px solid #252938;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 6%;
}
.logo { font-size: 22px; font-weight: 800; }
.logo span { color: #a78bfa; }
.status { color: #9ca3af; font-size: 12px; }
main { max-width: 1050px; margin: 65px auto; padding: 0 24px; }
.eyebrow { color: #a78bfa; font-size: 12px; letter-spacing: 2px; }
h1 { font-size: clamp(32px, 5vw, 52px); margin: 12px 0; }
.subtitle { color: #9298a8; line-height: 1.7; }
.panel {
  background: #11141d;
  border: 1px solid #252938;
  border-radius: 16px;
  padding: 28px;
  margin-top: 35px;
}
h2 { font-size: 18px; }
.hint, label { color: #9298a8; font-size: 13px; }
label { display: block; margin: 20px 0 9px; }
input {
  width: 100%;
  padding: 15px;
  border-radius: 9px;
  border: 1px solid #303647;
  background: #090b10;
  color: white;
}
button {
  margin-top: 22px;
  background: #8b5cf6;
  color: white;
  border: 0;
  border-radius: 9px;
  padding: 14px 22px;
  font-weight: 700;
  cursor: pointer;
}
.notice {
  margin-top: 18px;
  padding: 13px;
  background: #1b1b2a;
  border-radius: 8px;
  color: #c4b5fd;
  font-size: 13px;
}
.grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
  margin-top: 20px;
}
.stat {
  background: #11141d;
  border: 1px solid #252938;
  border-radius: 12px;
  padding: 20px;
}
.stat strong { display: block; font-size: 23px; }
.stat span { color: #9298a8; font-size: 12px; }
footer { color: #666d7d; text-align: center; padding: 40px; }
@media(max-width:650px) {
  .grid { grid-template-columns: 1fr; }
}
</style>
</head>
<body>
<header>
  <div class="logo">STREAM<span>LORE</span></div>
  <div class="status">● Cloud workspace</div>
</header>
<main>
  <div class="eyebrow">GTA VI CONTENT STUDIO</div>
  <h1>Turn streams into<br>viral-worthy moments.</h1>
  <p class="subtitle">
    Find the best moments from GTA VI streamers,
    analyze highlights with AI, and create vertical clips.
  </p>
  <section class="panel">
    <h2>Start a new project</h2>
    <p class="hint">Submit a public stream recording or upload a video.</p>
    <form id="projectForm">
      <label for="vodUrl">Stream or VOD URL</label>
      <input id="vodUrl" type="url"
        placeholder="Paste a YouTube, Twitch or Kick URL">
      <label for="videoFile">Or upload an MP4 video</label>
      <input id="videoFile" type="file" accept="video/mp4">
      <button type="submit">Prepare my project →</button>
    </form>
    <div class="notice" id="message">
      Cloud processing is being configured.
    </div>
  </section>
  <div class="grid">
    <div class="stat"><strong>AI</strong><span>Highlight detection</span></div>
    <div class="stat"><strong>9:16</strong><span>Vertical video output</span></div>
    <div class="stat"><strong>1080p</strong><span>Target export quality</span></div>
  </div>
</main>
<footer>STREAMLORE © 2026 · GTA VI CLIPPING STUDIO</footer>
<script>
document.getElementById("projectForm").addEventListener("submit", function(e) {
  e.preventDefault();
  document.getElementById("message").textContent =
    "Project submission is not connected yet. Coming in the next development step.";
});
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def home():
    return HTMLResponse(content=DASHBOARD)


@app.get("/api/health")
async def health():
    return {
        "app": "StreamLore",
        "status": "healthy",
        "freellmapi_configured": bool(
            os.getenv("FREELLMAPI_URL")
            and os.getenv("FREELLMAPI_API_KEY")
@app.post("/api/test-ai")
async def test_ai(x_test_token: str = Header(default="")):
    expected_token = os.getenv("STREAMLORE_TEST_TOKEN", "")

    if not expected_token or not secrets.compare_digest(
        x_test_token, expected_token
    ):
        raise HTTPException(status_code=401, detail="Unauthorized")

    base_url = os.getenv("FREELLMAPI_URL", "").rstrip("/")
    api_key = os.getenv("FREELLMAPI_API_KEY", "")

    if not base_url or not api_key:
        raise HTTPException(
            status_code=500,
            detail="FreeLLMAPI configuration missing"
        )

    payload = {
        "model": "auto",
        "messages": [
            {
                "role": "user",
                "content": "Reply with exactly: STREAMLORE AI TEST SUCCESS"
            }
        ],
        "stream": False
    }

    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload
        )

    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"FreeLLMAPI error: {response.text[:500]}"
        )

    result = response.json()

    return {
        "status": "success",
        "model": result.get("model"),
        "response": result["choices"][0]["message"]["content"]
    }
        ),
    }
