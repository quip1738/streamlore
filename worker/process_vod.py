
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

WORK = Path("work")
OUTPUT = Path("output")

WORK.mkdir(exist_ok=True)
OUTPUT.mkdir(exist_ok=True)


def run(command):
    subprocess.run(
        command,
        check=True,
        timeout=1200
    )


def download_vod():
    print("Downloading a bounded VOD section...")

    run([
        "yt-dlp",
        "--no-playlist",
        "--download-sections", "*0-600",
        "--force-keyframes-at-cuts",
        "-f", "best[ext=mp4]/best",
        "--merge-output-format", "mp4",
        "-o", str(WORK / "source.%(ext)s"),
        VOD_URL
    ])

    candidates = list(WORK.glob("source.*"))

    if not candidates:
        raise RuntimeError("VOD download did not produce a video.")

    return candidates[0]


def extract_frame(video):
    frame = WORK / "analysis.jpg"

    print("Extracting a frame for facecam analysis...")

    run([
        "ffmpeg", "-y",
        "-ss", "300",
        "-i", str(video),
        "-frames:v", "1",
        "-q:v", "3",
        str(frame)
    ])

    if not frame.exists() or frame.stat().st_size == 0:
        raise RuntimeError("Could not extract an analysis frame.")

    return frame


def analyze_frame(frame):
    print("Sending frame to StreamLore vision API...")

    encoded = base64.b64encode(frame.read_bytes()).decode("ascii")

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
    content = result.get("analysis", "")

    if isinstance(content, list):
        content = " ".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict)
        )

    # Extract JSON even if the model wraps it in Markdown.
    match = re.search(r"\{.*\}", content, re.DOTALL)

    if not match:
        raise RuntimeError(
            "Vision model did not return valid facecam JSON."
        )

    analysis = json.loads(match.group(0))

    if analysis.get("facecam_detected") is not True:
        raise RuntimeError(
            "No reliable facecam was detected. "
            "Refusing to create a badly composed clip."
        )

    box = analysis.get("facecam_box")

    if not isinstance(box, dict):
        raise RuntimeError("Facecam bounding box is missing.")

    x = float(box["x"])
    y = float(box["y"])
    width = float(box["width"])
    height = float(box["height"])
    confidence = float(analysis.get("confidence", 0))

    if confidence < 0.70:
        raise RuntimeError(
            "Facecam detection confidence is too low."
        )

    if (
        x < 0 or y < 0 or
        width <= 0 or height <= 0 or
        x + width > 1 or y + height > 1
    ):
        raise RuntimeError("Invalid facecam coordinates.")

    return {
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "confidence": confidence
    }


def render_vertical(video, facecam):
    print("Rendering streamer-over-gameplay composition...")

    # Inspect source dimensions.
    probe = subprocess.run(
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

    dimensions = json.loads(probe.stdout)["streams"][0]
    source_width = int(dimensions["width"])
    source_height = int(dimensions["height"])

    # Convert normalized facecam coordinates to even pixel values.
    def even(value):
        return max(2, int(value) // 2 * 2)

    cam_x = even(facecam["x"] * source_width)
    cam_y = even(facecam["y"] * source_height)
    cam_w = even(facecam["width"] * source_width)
    cam_h = even(facecam["height"] * source_height)

    cam_w = min(cam_w, source_width - cam_x)
    cam_h = min(cam_h, source_height - cam_y)

    if cam_w < 80 or cam_h < 60:
        raise RuntimeError("Detected facecam region is too small.")

    # The lower gameplay panel is a 9:8 landscape crop.
    # The facecam panel is kept separately above it.
    game_crop_w = even(source_height * 9 / 8)

    if game_crop_w > source_width:
        game_crop_h = even(source_width * 8 / 9)
        game_x = 0
        game_y = even((source_height - game_crop_h) / 2)
        game_crop_w = source_width
    else:
        game_crop_h = source_height
        game_x = even((source_width - game_crop_w) / 2)
        game_y = 0

    # Prevent an embedded facecam from being duplicated in gameplay:
    # if the detected box overlaps the gameplay crop, reject this
    # composition rather than silently showing the streamer twice.
    cam_right = cam_x + cam_w
    cam_bottom = cam_y + cam_h
    game_right = game_x + game_crop_w
    game_bottom = game_y + game_crop_h

    overlap_x = max(0, min(cam_right, game_right) - max(cam_x, game_x))
    overlap_y = max(0, min(cam_bottom, game_bottom) - max(cam_y, game_y))

    overlap_area = overlap_x * overlap_y
    cam_area = cam_w * cam_h

    if cam_area and overlap_area / cam_area > 0.15:
        raise RuntimeError(
            "The facecam overlaps the gameplay crop. "
            "This source needs a separate camera/gameplay layout "
            "strategy before it can be rendered safely."
        )

    output = OUTPUT / "streamlore-vertical.mp4"

    filter_graph = (
        f"[0:v]crop={cam_w}:{cam_h}:{cam_x}:{cam_y},"
        f"scale=1080:960:force_original_aspect_ratio=increase,"
        f"crop=1080:960[cam];"
        f"[0:v]crop={game_crop_w}:{game_crop_h}:{game_x}:{game_y},"
        f"scale=1080:960[game];"
        f"[cam][game]vstack=inputs=2[v]"
    )

    run([
        "ffmpeg", "-y",
        "-ss", "300",
        "-i", str(video),
        "-t", "30",
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
        raise RuntimeError("Vertical clip rendering failed.")

    print("Vertical clip created:", output)


def main():
    if not INTERNAL_TOKEN:
        raise RuntimeError("Internal API token is missing.")

    video = download_vod()
    frame = extract_frame(video)
    facecam = analyze_frame(frame)

    print(
        "Facecam detected:",
        json.dumps(facecam, indent=2)
    )

    render_vertical(video, facecam)

    print("STREAMLORE PROCESSING COMPLETE")


if __name__ == "__main__":
    main()
