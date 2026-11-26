
import os
import re
import json
import base64
import subprocess
from pathlib import Path
from urllib.parse import quote

import httpx


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

API_URL = os.getenv(
    "STREAMLORE_API_URL",
    "https://streamlore.prod.page"
).rstrip("/")

INTERNAL_TOKEN = os.environ["STREAMLORE_INTERNAL_TOKEN"]
VOD_URL = os.environ["VOD_URL"]
JOB_ID = os.environ["JOB_ID"]

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

BUCKET = "streamlore-clips"

SCAN_DURATION_SECONDS = int(
    os.getenv("STREAMLORE_SCAN_SECONDS", "1200")
)

SAMPLE_INTERVAL_SECONDS = int(
    os.getenv("STREAMLORE_SAMPLE_INTERVAL", "45")
)

CLIP_LENGTH = 30
MIN_HIGHLIGHT_SCORE = 5
MIN_FACECAM_CONFIDENCE = 0.70
MAX_UPLOAD_BYTES = 50 * 1024 * 1024

WORK_DIR = Path("work")
OUTPUT_DIR = Path("output")

SOURCE_FILE = WORK_DIR / "source.mp4"
OUTPUT_FILE = OUTPUT_DIR / "streamlore-vertical.mp4"


# --------------------------------------------------
# HELPERS
# --------------------------------------------------

def run(command):
    subprocess.run(
        command,
        check=True,
        text=True
    )


def supabase_headers(content_type="application/json"):
    return {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": content_type,
    }


def update_job(values):
    url = f"{SUPABASE_URL}/rest/v1/jobs"

    response = httpx.patch(
        url,
        params={"id": f"eq.{JOB_ID}"},
        headers={
            **supabase_headers(),
            "Prefer": "return=minimal",
        },
        json=values,
        timeout=30,
    )

    response.raise_for_status()


def upload_clip():
    size = OUTPUT_FILE.stat().st_size

    if size > MAX_UPLOAD_BYTES:
        raise RuntimeError(
            f"Generated clip is {size / 1024 / 1024:.1f} MB. "
            "The configured upload limit is 50 MB."
        )

    storage_path = f"{JOB_ID}/streamlore-vertical.mp4"

    encoded_path = quote(storage_path, safe="/")
    url = (
        f"{SUPABASE_URL}/storage/v1/object/"
        f"{BUCKET}/{encoded_path}"
    )

    with OUTPUT_FILE.open("rb") as clip:
        response = httpx.post(
            url,
            headers={
                **supabase_headers("video/mp4"),
                "x-upsert": "true",
            },
            content=clip,
            timeout=300,
        )

    response.raise_for_status()
    return storage_path


def download_vod():
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    run([
        "yt-dlp",
        "--no-playlist",
        "--download-sections",
        f"*0-{SCAN_DURATION_SECONDS}",
        "--force-keyframes-at-cuts",
        "--merge-output-format",
        "mp4",
        "-f",
        "best[height<=720][ext=mp4]/best[height<=720]/best",
        "-o",
        str(SOURCE_FILE),
        VOD_URL,
    ])

    if not SOURCE_FILE.exists():
        raise RuntimeError("VOD download did not produce a video file.")

    if SOURCE_FILE.stat().st_size == 0:
        raise RuntimeError("Downloaded video is empty.")


# --------------------------------------------------
# FRAME ANALYSIS
# --------------------------------------------------

def extract_frame(timestamp, destination):
    run([
        "ffmpeg",
        "-y",
        "-ss",
        str(timestamp),
        "-i",
        str(SOURCE_FILE),
        "-frames:v",
        "1",
        "-q:v",
        "3",
        str(destination),
    ])

    if not destination.exists():
        raise RuntimeError(
            f"Could not extract frame at {timestamp} seconds."
        )


def analyze_frame(frame_path, timestamp):
    image_data = base64.b64encode(
        frame_path.read_bytes()
    ).decode("utf-8")

    response = httpx.post(
        f"{API_URL}/api/internal/analyze-frame",
        headers={
            "X-Internal-Token": INTERNAL_TOKEN,
        },
        json={
            "image_base64": image_data,
            "mime_type": "image/jpeg",
        },
        timeout=120,
    )

    response.raise_for_status()

    result = response.json()
    raw_analysis = result.get("analysis", "")

    if isinstance(raw_analysis, dict):
        analysis = raw_analysis
    else:
        text = str(raw_analysis).strip()
        text = re.sub(r"^```(?:json)?", "", text)
        text = re.sub(r"```$", "", text).strip()

        try:
            analysis = json.loads(text)
        except json.JSONDecodeError:
            print(f"Could not parse analysis at {timestamp}s")
            return None

    if not isinstance(analysis, dict):
        return None

    analysis["timestamp"] = timestamp
    return analysis


def scan_vod():
    frame_dir = WORK_DIR / "frames"
    frame_dir.mkdir(parents=True, exist_ok=True)

    candidates = []

    timestamps = range(
        SAMPLE_INTERVAL_SECONDS,
        SCAN_DURATION_SECONDS,
        SAMPLE_INTERVAL_SECONDS,
    )

    for timestamp in timestamps:
        frame_path = frame_dir / f"frame_{timestamp}.jpg"

        print(f"Analyzing VOD at {timestamp}s")

        try:
            extract_frame(timestamp, frame_path)
            result = analyze_frame(frame_path, timestamp)

            if result:
                candidates.append(result)

        except Exception as exc:
            print(
                f"Skipping frame at {timestamp}s: "
                f"{str(exc)[:300]}"
            )

    if not candidates:
        raise RuntimeError(
            "No usable frame analyses were returned."
        )

    return candidates


# --------------------------------------------------
# HIGHLIGHT SELECTION
# --------------------------------------------------

def select_highlight(candidates):
    valid = []

    for item in candidates:
        try:
            score = float(item.get("highlight_score", 0))
        except (TypeError, ValueError):
            continue

        if score < MIN_HIGHLIGHT_SCORE:
            continue

        facecam = item.get("facecam_detected", False)

        if facecam is not True:
            continue

        try:
            confidence = float(
                item.get("facecam_confidence", 0)
            )
        except (TypeError, ValueError):
            continue

        if confidence < MIN_FACECAM_CONFIDENCE:
            continue

        bbox = item.get("facecam_bbox")

        if not isinstance(bbox, dict):
            continue

        try:
            x = float(bbox["x"])
            y = float(bbox["y"])
            width = float(bbox["width"])
            height = float(bbox["height"])
        except (KeyError, TypeError, ValueError):
            continue

        if not (
            0 <= x < 1
            and 0 <= y < 1
            and 0 < width <= 1
            and 0 < height <= 1
            and x + width <= 1
            and y + height <= 1
        ):
            continue

        item["_score"] = score
        item["_bbox"] = {
            "x": x,
            "y": y,
            "width": width,
            "height": height,
        }

        valid.append(item)

    if not valid:
        raise RuntimeError(
            "No highlight met the score and facecam "
            "detection requirements."
        )

    valid.sort(
        key=lambda item: item["_score"],
        reverse=True
    )

    return valid[0]


# --------------------------------------------------
# VERTICAL VIDEO COMPOSITION
# --------------------------------------------------

def render_vertical(highlight):
    timestamp = int(highlight["timestamp"])
    bbox = highlight["_bbox"]

    start = max(0, timestamp - CLIP_LENGTH // 2)

    x = bbox["x"]
    y = bbox["y"]
    width = bbox["width"]
    height = bbox["height"]

    # Convert normalized facecam coordinates to pixels.
    probe = subprocess.run(
        [
            "ffprobe",
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "json",
            str(SOURCE_FILE),
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    dimensions = json.loads(probe.stdout)["streams"][0]

    video_width = int(dimensions["width"])
    video_height = int(dimensions["height"])

    cam_x = int(x * video_width)
    cam_y = int(y * video_height)
    cam_w = int(width * video_width)
    cam_h = int(height * video_height)

    if cam_w < 80 or cam_h < 60:
        raise RuntimeError(
            "Detected facecam region is too small."
        )

    # The gameplay crop must not include the detected facecam.
    # This uses the opposite side of the facecam where possible.
    candidates = [
        (0, 0, cam_x),
        (cam_x + cam_w, 0, video_width - (cam_x + cam_w)),
    ]

    candidates = [
        candidate
        for candidate in candidates
        if candidate[2] >= video_width * 0.35
    ]

    if not candidates:
        raise RuntimeError(
            "Could not find a gameplay crop that avoids "
            "the detected facecam."
        )

    crop_x, _, crop_w = max(
        candidates,
        key=lambda item: item[2]
    )

    # Crop gameplay from the full video height.
    # Facecam is independently cropped from its detected box.
    filter_complex = (
        f"[0:v]split=2[game][cam];"
        f"[game]crop={crop_w}:{video_height}:{crop_x}:0,"
        f"scale=1080:960:force_original_aspect_ratio=increase,"
        f"crop=1080:960[gameplay];"
        f"[cam]crop={cam_w}:{cam_h}:{cam_x}:{cam_y},"
        f"scale=1080:960:force_original_aspect_ratio=decrease,"
        f"pad=1080:960:(ow-iw)/2:(oh-ih)/2[facecam];"
        f"[facecam][gameplay]vstack=inputs=2[outv]"
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    run([
        "ffmpeg",
        "-y",
        "-ss", str(start),
        "-i", str(SOURCE_FILE),
        "-t", str(CLIP_LENGTH),
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-map", "0:a?",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "27",
        "-maxrate", "3500k",
        "-bufsize", "7000k",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "96k",
        "-movflags", "+faststart",
        str(OUTPUT_FILE),
    ])

    if not OUTPUT_FILE.exists():
        raise RuntimeError("FFmpeg did not create the output clip.")

    if OUTPUT_FILE.stat().st_size == 0:
        raise RuntimeError("Rendered clip is empty.")


# --------------------------------------------------
# MAIN WORKFLOW
# --------------------------------------------------

def main():
    try:
        print(f"Starting StreamLore job: {JOB_ID}")

        update_job({
            "status": "processing",
            "error_message": None,
        })

        download_vod()

        candidates = scan_vod()
        highlight = select_highlight(candidates)

        print(
            "Selected highlight at "
            f"{highlight['timestamp']}s "
            f"with score {highlight['_score']}"
        )

        render_vertical(highlight)

        storage_path = upload_clip()

        reason = str(
            highlight.get("reason", "")
        ).strip()

        description = (
            reason[:500]
            if reason
            else "GTA VI highlight generated by StreamLore."
        )

        update_job({
            "status": "completed",
            "clip_path": storage_path,
            "title": "GTA VI Highlight",
            "description": description,
            "error_message": None,
        })

        print("StreamLore job completed successfully.")

    except Exception as exc:
        error_message = str(exc)[:1000]

        print(f"StreamLore job failed: {error_message}")

        try:
            update_job({
                "status": "failed",
                "error_message": error_message,
            })
        except Exception as update_error:
            print(
                "Could not update failed job status: "
                f"{str(update_error)[:300]}"
            )

        raise


if __name__ == "__main__":
    main()
