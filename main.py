
import os
import secrets
import httpx

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse

app = FastAPI(
    title="StreamLore API",
    version="0.2.0",
)

DASHBOARD = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>StreamLore</title>
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
            padding: 25px 8%;
            border-bottom: 1px solid #242735;
            font-size: 22px;
            font-weight: bold;
        }
        header span { color: #a78bfa; }
        main {
            max-width: 850px;
            margin: 90px auto;
            padding: 25px;
        }
        .tag {
            color: #a78bfa;
            font-size: 13px;
            letter-spacing: 2px;
            text-transform: uppercase;
        }
        h1 { font-size: 48px; margin-bottom: 12px; }
        p { color: #a1a1aa; line-height: 1.7; }
        .panel {
            background: #141722;
            border: 1px solid #292d3d;
            border-radius: 15px;
            padding: 25px;
            margin-top: 35px;
        }
        .status { color: #4ade80; font-weight: bold; }
        a { color: #a78bfa; }
        footer {
            margin-top: 70px;
            color: #71717a;
            font-size: 13px;
        }
    </style>
</head>
<body>
    <header>Stream<span>Lore</span></header>
    <main>
        <div class="tag">AI Gaming Highlights</div>
        <h1>Your stream.<br>Our intelligence.</h1>
        <p>
            StreamLore is building an AI-powered gaming highlight
            platform focused on discovering the best moments from
            GTA VI livestreams.
        </p>
        <div class="panel">
            <h2>System Status</h2>
            <p class="status">● StreamLore API Online</p>
            <p>AI gateway: Connected configuration</p>
            <p>Video processing: Coming soon</p>
        </div>
        <footer>StreamLore © 2026</footer>
    </main>
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
        ),
    }


@app.post("/api/test-ai")
async def test_ai(
    x_test_token: str = Header(default="")
):
    expected_token = os.getenv("STREAMLORE_TEST_TOKEN", "")

    if not expected_token or not secrets.compare_digest(
        x_test_token, expected_token
    ):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized"
        )

    base_url = os.getenv(
        "FREELLMAPI_URL", ""
    ).rstrip("/")

    api_key = os.getenv(
        "FREELLMAPI_API_KEY", ""
    )

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
                "content": (
                    "Reply with exactly: "
                    "STREAMLORE AI TEST SUCCESS"
                )
            }
        ],
        "stream": False
    }

    try:
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json=payload
            )

        if response.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail="FreeLLMAPI returned an error: "
                       + response.text[:500]
            )

        result = response.json()

        return {
            "status": "success",
            "model": result.get("model"),
            "response": result["choices"][0]["message"]["content"]
        }

    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="FreeLLMAPI request timed out"
        )

    except httpx.RequestError:
        raise HTTPException(
            status_code=502,
            detail="Could not connect to FreeLLMAPI"
        )
