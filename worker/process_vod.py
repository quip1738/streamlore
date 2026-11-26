
import os
import re
import json
import base64
import subprocess
from pathlib import Path

import httpx


API_URL = os.environ["STREAMLORE_API_URL"].rstrip("/")
INTERNAL_TOKEN = os.environ["STREAMLORE_INTERNAL_TOKEN"]
VOD_URL = os.environ["VOD_URL"]

VISION_MODEL = "nemotron-3-nano-omni-reasoning"

WORK = Path("work")
OUTPUT = Path("output")

WORK.mkdir(exist_ok=True)
OUTPUT.mkdir(exist_ok=True)

MAX_VOD_SECONDS = 600
CLIP_LENGTH = 30
SAMPLE_TIMES = list(range(30, 571, 45))


def run(command, timeout=1200):
    subprocess.run(
        command,
        check=True,
        timeout=timeout
    )


def download_vod():
    print("Downloading the first 10 minutes of the VOD...")

    run([
        "yt-dlp",
        "--no-playlist",
        "--download-sections",
        f"*0-{MAX_VOD_SECONDS}",
        "--force-keyframes-at-cuts",
        "-f",
        "best[ext=mp4]/best",
        "--merge-output-format",
        "mp4",
        "-o",
        str(WORK / "source.%(ext)s"),
        VOD_URL
    ])

    candidates = list(WORK.glob("source.*"))

    if not candidates:
        raise RuntimeError("VOD download produced no video.")

    return candidates[0]


def extract_frame(video, timestamp, output_path):
    run([
        "ffmpeg",
        "-y",
        "-ss",
        str(timestamp),
        "-i",
        str(video),
        "-frames:v",
        "1",
        "-q:v",
        "4",
        str(output_path)
    ])

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError(
            f"Could not extract frame at {timestamp}s."
        )

    return output_path


def parse_model_json(content):
    if isinstance(content, list):
        content = " ".join(
            item.get("text", "")
            for item in content
            if isinstance(item, dict)
        )

    if not isinstance(content, str):
        raise RuntimeError("Vision model returned an unexpected response.")

    match = re.search(r"\{.*\}", content, re.DOTALL)

    if not match:
        raise RuntimeError("Vision model did not return valid JSON.")

    return json.loads(match.group(0))


def analyze_frame(frame, prompt):
    encoded = base64.b64encode(
        frame.read_bytes()
    ).decode("ascii")

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
                            "url": f"data:image/jpeg;base64,{encoded}",
                            "detail": "high"
                        }
                    }
                ]
            }
        ],
        "stream": False
    }

    response = httpx.post(
        f"{API_URL}/api/internal/analyze-frame",
        headers={
            "X-Internal-Token": INTERNAL_TOKEN
        },
        json={
            "image_base64": encoded,
            "mime_type": "image/jpeg"
        },
        timeout=150
    )

    response.raise_for_status()

    result = response.json()
    return parse_model_json(result.get("analysis", ""))


def rank_highlights(video):
    print("Scanning GTA VI footage for exciting moments...")

    candidates = []

    prompt = """
You are an expert gaming highlight editor reviewing a GTA VI stream.

Evaluate this single frame for its potential as a short-form gaming
highlight.

Look for:
- Explosions, crashes, chases, combat and close calls.
- Unexpected or chaotic gameplay.
- Funny or surprising situations.
- Dramatic action or unusual events.

Do not give high scores to ordinary driving, menus, loading screens,
static scenes or ordinary gameplay.

Return ONLY valid JSON:

{
  "highlight_score": 0,
  "reason": "Short explanation",
  "facecam_detected": false,
  "facecam_box": null,
  "facecam_confidence": 0
}

Score must be an integer from 0 to 10.

If a clearly identifiable streamer webcam is visible, set
facecam_detected to true and provide its complete bounding box.

Coordinates must be normalized from 0 to 1:
x, y, width, height.

The bounding box must cover the entire webcam overlay, not just
the person's face.

Do not mistake an in-game character, portrait or poster for a webcam.
"""

    for index, timestamp in enumerate(SAMPLE_TIMES, start=1):
        frame = WORK / f"sample_{timestamp}.jpg"

        try:
            extract_frame(video, timestamp, frame)
            result = analyze_frame(frame, prompt)

            score = int(result.get("highlight_score", 0))
            score = max(0, min(10, score))

            candidate = {
                "timestamp": timestamp,
                "score": score,
                "reason": str(result.get("reason", "")),
                "facecam_detected": (
                    result.get("facecam_detected") is True
                ),
                "facecam_box": result.get("facecam_box"),
                "facecam_confidence": float(
                    result.get("facecam_confidence", 0)
                )
            }

            candidates.append(candidate)

            print(
                f"[{index}/{len(SAMPLE_TIMES)}] "
                f"{timestamp}s: score {score}/10 - "
                f"{candidate['reason']}"
            )

        except Exception as error:
            print(
                f"Could not analyze frame at {timestamp}s: {error}"
            )

    if not candidates:
        raise RuntimeError("No VOD frames could be analyzed.")

    candidates.sort(
        key=lambda item: item["score"],
        reverse=True
    )

    print("Highlight candidates:")
    print(json.dumps(candidates[:5], indent=2))

    best = candidates[0]

    if best["score"] < 5:
        raise RuntimeError(
            "No sufficiently exciting highlight was found "
            "in the scanned VOD section."
        )

    return best


def validate_facecam(candidate):
    if not candidate["facecam_detected"]:
        raise RuntimeError(
            "No streamer facecam was detected. "
            "Refusing to publish a badly composed clip."
        )

    if candidate["facecam_confidence"] < 0.70:
        raise RuntimeError(
            "Facecam confidence is too low."
        )

    box = candidate["facecam_box"]

    if not isinstance(box, dict):
        raise RuntimeError("Facecam bounding box is missing.")

    try:
        x = float(box["x"])
        y = float(box["y"])
        width = float(box["width"])
        height = float(box["height"])
    except (KeyError, TypeError, ValueError):
        raise RuntimeError("Invalid facecam coordinates.")

    if (
        x < 0 or y < 0 or
        width <= 0 or height <= 0 or
        x + width > 1 or y + height > 1
    ):
        raise RuntimeError("Facecam coordinates are outside the frame.")

    return {
        "x": x,
        "y": y,
        "width": width,
        "height": height
    }


def inspect_video(video):
    result = subprocess.run(
        [
            "ffprobe",
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "json",
            str(video)
        ],
        capture_output=True,
        text=True,
        check=True
    )

    streams = json.loads(result.stdout).get("streams", [])

    if not streams:
        raise RuntimeError("Could not read source video dimensions.")

    return (
        int(streams[0]["width"]),
        int(streams[0]["height"])
    )


def even(value):
    return max(2, int(value) // 2 * 2)


def render_vertical(video, candidate):
    facecam = validate_facecam(candidate)

    source_width, source_height = inspect_video(video)

    cam_x = even(facecam["x"] * source_width)
    cam_y = even(facecam["y"] * source_height)
    cam_w = even(facecam["width"] * source_width)
    cam_h = even(facecam["height"] * source_height)

    cam_w = min(cam_w, source_width - cam_x)
    cam_h = min(cam_h, source_height - cam_y)

    if cam_w < 80 or cam_h < 60:
        raise RuntimeError("Detected facecam is too small.")

    # A 1080x960 gameplay panel needs a 9:8 source crop.
    game_crop_w = even(source_height * 9 / 8)

    if game_crop_w > source_width:
        game_crop_h = even(source_width * 8 / 9)
        game_crop_w = source_width
        game_y = even((source_height - game_crop_h) / 2)
        possible_x = [0]
    else:
        game_crop_h = source_height
        game_y = 0
        possible_x = [
            0,
            even((source_width - game_crop_w) / 2),
            even(source_width - game_crop_w)
        ]

    # Choose a gameplay crop that avoids the facecam overlay.
    cam_right = cam_x + cam_w
    cam_bottom = cam_y + cam_h

    choices = []

    for game_x in possible_x:
        game_right = game_x + game_crop_w
        game_bottom = game_y + game_crop_h

        overlap_x = max(
            0,
            min(cam_right, game_right) - max(cam_x, game_x)
        )

        overlap_y = max(
            0,
            min(cam_bottom, game_bottom) - max(cam_y, game_y)
        )

        overlap = (
            overlap_x * overlap_y
        ) / (cam_w * cam_h)

        choices.append((overlap, game_x))

    overlap, game_x = min(choices)

    if overlap > 0.05:
        raise RuntimeError(
            "Could not find a gameplay crop that avoids the facecam. "
            "This stream needs a different composition strategy."
        )

    start = max(
        0,
        candidate["timestamp"] - CLIP_LENGTH // 2
    )

    output = OUTPUT / "streamlore-vertical.mp4"

    filter_graph = (
        f"[0:v]crop={cam_w}:{cam_h}:{cam_x}:{cam_y},"
        "scale=1080:960:force_original_aspect_ratio=increase,"
        "crop=1080:960[cam];"
        f"[0:v]crop={game_crop_w}:{game_crop_h}:{game_x}:{game_y},"
        "scale=1080:960[game];"
        "[cam][game]vstack=inputs=2[v]"
    )

    print("Rendering selected highlight...")
    print("Timestamp:", candidate["timestamp"])
    print("Gameplay crop:", game_x, game_y, game_crop_w, game_crop_h)
    print("Facecam:", facecam)

    run([
        "ffmpeg",
        "-y",
        "-ss", str(start),
        "-i", str(video),
        "-t", str(CLIP_LENGTH),
        "-filter_complex", filter_graph,
        "-map", "[v]",
        "-map", "0:a?",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        str(output)
    ])

    if not output.exists() or output.stat().st_size == 0:
        raise RuntimeError("Vertical rendering failed.")

    print("Created:", output)


def main():
    if not INTERNAL_TOKEN:
        raise RuntimeError("Internal API token is missing.")

    video = download_vod()

    best = rank_highlights(video)

    print("Selected highlight:")
    print(json.dumps(best, indent=2))

    render_vertical(video, best)

    print("STREAMLORE HIGHLIGHT PROCESSING COMPLETE")


if __name__ == "__main__":
    main()
