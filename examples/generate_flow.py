"""Generate images via Google Flow and save to a local directory.

Usage:
    python test/generate_flow.py
    python test/generate_flow.py "A sunset over mountains"
    python test/generate_flow.py "prompt" --model imagen-4 --orientation portrait --count 4
    python test/generate_flow.py "prompt" --output-dir ./my_images
"""

import argparse
import asyncio
import logging
from pathlib import Path

from browser2api import BrowserManager, Platform
from browser2api.platforms.flow import FlowClient, FlowCount, FlowModel, FlowOrientation
from browser2api.platforms.flow.enums import MODEL_NAMES

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

DEFAULT_PROMPT = "A cute cat sitting in a garden with colorful flowers, digital art style, vibrant colors, soft lighting"
DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "output"


async def generate(
    prompt: str,
    output_dir: Path,
    model: FlowModel,
    orientation: FlowOrientation,
    count: FlowCount,
):
    bm = BrowserManager()

    try:
        print("Launching browser...")
        context, page = await bm.launch_for_login(Platform.FLOW)

        client = FlowClient(
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
        print(f"Output: {output_dir}")
        print("Generating...\n")

        result = await client.generate_images(prompt, timeout_seconds=120)

        print(f"\nStatus: {result.status.value}")
        if result.error:
            print(f"Error: {result.error}")
        print(f"Model: {result.model}")
        print(f"Duration: {result.duration_ms}ms")
        print(f"Images: {len(result.images)}")
        for i, img in enumerate(result.images):
            size = ""
            if img.local_path:
                p = Path(img.local_path)
                if p.exists():
                    size = f"  ({p.stat().st_size:,} bytes)"
            highres = " [high-res]" if img.is_highres else ""
            dims = ""
            if img.width and img.height:
                dims = f" {img.width}x{img.height}"
            print(f"  [{i+1}] {img.filename}{highres}{dims}{size}")
            print(f"       {img.local_path}")
    finally:
        await bm.close()


if __name__ == "__main__":
    model_choices = list(MODEL_NAMES.keys())
    orientation_choices = [o.value for o in FlowOrientation]
    count_choices = [str(c.value) for c in FlowCount]

    parser = argparse.ArgumentParser(description="Generate images via Google Flow")
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
        default="nano-banana-2",
        help=f"Model to use (default: nano-banana-2). Choices: {', '.join(model_choices)}",
    )
    parser.add_argument(
        "--orientation",
        choices=orientation_choices,
        default="landscape",
        help=f"Image orientation (default: landscape). Choices: {', '.join(orientation_choices)}",
    )
    parser.add_argument(
        "--count",
        choices=count_choices,
        default="2",
        help=f"Number of images (default: 2). Choices: {', '.join(count_choices)}",
    )
    args = parser.parse_args()

    model = MODEL_NAMES[args.model]
    orientation = FlowOrientation(args.orientation)
    count = FlowCount(int(args.count))

    asyncio.run(generate(args.prompt, args.output_dir, model, orientation, count))
