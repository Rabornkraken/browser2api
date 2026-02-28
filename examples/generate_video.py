"""Generate a video via Jimeng and save to a local directory.

Usage:
    python test/generate_video.py
    python test/generate_video.py "一只猫在花园里散步"
    python test/generate_video.py "城市夜景" --ratio 16:9 --duration 10s
"""

import argparse
import asyncio
import logging
from pathlib import Path

from browser2api import BrowserManager, Platform
from browser2api.platforms.jimeng import (
    JimengRatio,
    JimengVideoDuration,
    JimengVideoModel,
    JimengVideoResolution,
)
from browser2api.platforms.jimeng.client import JimengVideoClient
from browser2api.platforms.jimeng.enums import VIDEO_MODEL_NAMES

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

DEFAULT_PROMPT = "一只猫在花园里散步，阳光明媚，微风吹过花丛"
DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "output"

# CLI-friendly duration labels
DURATION_MAP = {
    "5s": JimengVideoDuration.FIVE,
    "10s": JimengVideoDuration.TEN,
}


async def generate(
    prompt: str,
    output_dir: Path,
    model: JimengVideoModel,
    ratio: JimengRatio,
    resolution: JimengVideoResolution,
    duration: JimengVideoDuration,
    timeout: int,
):
    bm = BrowserManager()

    try:
        print("Launching browser...")
        context, page = await bm.launch_for_login(Platform.JIMENG)

        client = JimengVideoClient(
            page, context,
            output_dir=output_dir,
            model=model,
            ratio=ratio,
            resolution=resolution,
            duration=duration,
        )

        duration_label = f"{duration.value // 1000}s"
        print(f"Prompt: {prompt}")
        print(f"Model: {model.name}")
        print(f"Ratio: {ratio.value}")
        print(f"Resolution: {resolution.value}")
        print(f"Duration: {duration_label}")
        print(f"Timeout: {timeout}s")
        print(f"Output: {output_dir}")
        print("Generating via browser automation...\n")

        result = await client.generate_video(prompt, timeout_seconds=timeout)

        print(f"\nStatus: {result.status.value}")
        if result.error:
            print(f"Error: {result.error}")
        print(f"Model: {result.model}")
        print(f"Generation time: {result.duration_ms}ms")
        if result.video:
            v = result.video
            size = ""
            if v.size_bytes:
                size = f"  ({v.size_bytes:,} bytes)"
            print(f"Video: {v.filename}{size}")
            print(f"       {v.local_path}")
        else:
            print("Video: None")
    finally:
        await bm.close()


if __name__ == "__main__":
    model_choices = list(VIDEO_MODEL_NAMES.keys())
    ratio_choices = [r.value for r in JimengRatio]
    duration_choices = list(DURATION_MAP.keys())
    resolution_choices = [r.value for r in JimengVideoResolution]

    parser = argparse.ArgumentParser(description="Generate video via Jimeng")
    parser.add_argument("prompt", nargs="?", default=DEFAULT_PROMPT, help="Text prompt")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output directory (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--model",
        choices=model_choices,
        default="video-3.0-fast",
        help=f"Model (default: video-3.0-fast). Choices: {', '.join(model_choices)}",
    )
    parser.add_argument(
        "--ratio",
        choices=ratio_choices,
        default="16:9",
        help=f"Aspect ratio (default: 16:9). Choices: {', '.join(ratio_choices)}",
    )
    parser.add_argument(
        "--resolution",
        choices=resolution_choices,
        default="720p",
        help=f"Resolution (default: 720p). Choices: {', '.join(resolution_choices)}",
    )
    parser.add_argument(
        "--duration",
        choices=duration_choices,
        default="5s",
        help=f"Video duration (default: 5s). Choices: {', '.join(duration_choices)}",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Timeout in seconds (default: 300)",
    )
    args = parser.parse_args()

    model = VIDEO_MODEL_NAMES[args.model]
    ratio = JimengRatio(args.ratio)
    resolution = JimengVideoResolution(args.resolution)
    duration = DURATION_MAP[args.duration]

    asyncio.run(generate(
        args.prompt, args.output_dir, model, ratio, resolution, duration, args.timeout,
    ))
