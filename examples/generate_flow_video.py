"""Generate a video via Google Flow and save to a local directory.

Usage:
    python test/generate_flow_video.py
    python test/generate_flow_video.py "A cat walking through a garden"
    python test/generate_flow_video.py "A sunset timelapse" --model veo-3.1-quality --orientation portrait
    python test/generate_flow_video.py "prompt" --count 1 --timeout 600
"""

import argparse
import asyncio
import logging
from pathlib import Path

from browser2api import BrowserManager, Platform
from browser2api.platforms.flow import FlowCount, FlowOrientation, FlowVideoModel
from browser2api.platforms.flow.client import FlowVideoClient
from browser2api.platforms.flow.enums import VIDEO_MODEL_NAMES

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

DEFAULT_PROMPT = "A cat walking through a garden, soft sunlight, gentle breeze"
DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "output"


async def generate(
    prompt: str,
    output_dir: Path,
    model: FlowVideoModel,
    orientation: FlowOrientation,
    count: FlowCount,
    timeout: int,
):
    bm = BrowserManager()

    try:
        print("Launching browser...")
        context, page = await bm.launch_for_login(Platform.FLOW)

        client = FlowVideoClient(
            page, context,
            output_dir=output_dir,
            model=model,
            orientation=orientation,
            count=count,
        )

        print(f"Prompt: {prompt}")
        print(f"Model: {model.name} ({model.value})")
        print(f"Orientation: {orientation.value}")
        print(f"Count: {count.value}")
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
    orientation_choices = [o.value for o in FlowOrientation]
    count_choices = [str(c.value) for c in FlowCount]

    parser = argparse.ArgumentParser(description="Generate video via Google Flow")
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
        default="veo-3.1-fast",
        help=f"Model (default: veo-3.1-fast). Choices: {', '.join(model_choices)}",
    )
    parser.add_argument(
        "--orientation",
        choices=orientation_choices,
        default="landscape",
        help=f"Orientation (default: landscape). Choices: {', '.join(orientation_choices)}",
    )
    parser.add_argument(
        "--count",
        choices=count_choices,
        default="1",
        help=f"Number of videos (default: 1). Choices: {', '.join(count_choices)}",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Timeout in seconds (default: 300)",
    )
    args = parser.parse_args()

    model = VIDEO_MODEL_NAMES[args.model]
    orientation = FlowOrientation(args.orientation)
    count = FlowCount(int(args.count))

    asyncio.run(generate(
        args.prompt, args.output_dir, model, orientation, count, args.timeout,
    ))
