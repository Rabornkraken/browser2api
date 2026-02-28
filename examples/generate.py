"""Generate images via Jimeng and save to a local directory.

Usage:
    python test/generate.py
    python test/generate.py "一只猫在太空中"
    python test/generate.py "prompt" --output-dir ./my_images
"""

import argparse
import asyncio
import logging
from pathlib import Path

from browser2api import BrowserManager, Platform
from browser2api.platforms.jimeng import JimengClient, JimengModel, JimengRatio, JimengResolution
from browser2api.platforms.jimeng.enums import MODEL_NAMES

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

DEFAULT_PROMPT = "3D卡通全身人物，IP盲盒风格，皮克斯动画质感，28岁女性UX设计师，浅蓝色休闲衬衫搭配卡其色工装裤，头戴彩色降噪耳机，手持平板电脑，表情好奇兴奋，开放式创意办公室背景，书架和绿植点缀，Mac电脑和创意工具散落，C4D渲染，粘土质感，柔和自然的灯光，全身站立姿态，从头到脚完整展示，正面视角，竖构图9:16比例，高细节，4K分辨率，精致渲染，糖果配色，场景与人物融合自然"
DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "output"


async def generate(
    prompt: str,
    output_dir: Path,
    model: JimengModel,
    ratio: JimengRatio,
    resolution: JimengResolution,
):
    bm = BrowserManager()

    try:
        print("Launching browser...")
        context, page = await bm.launch_for_login(Platform.JIMENG)

        client = JimengClient(
            page, context,
            output_dir=output_dir,
            model=model,
            ratio=ratio,
            resolution=resolution,
        )

        print(f"Prompt: {prompt}")
        print(f"Model: {model.name} ({model.value})")
        print(f"Ratio: {ratio.value}")
        print(f"Resolution: {resolution.value}")
        print(f"Output: {output_dir}")
        print("Generating...\n")

        result = await client.generate_images(prompt, count=4, timeout_seconds=120)

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
    ratio_choices = [r.value for r in JimengRatio]

    parser = argparse.ArgumentParser(description="Generate images via Jimeng")
    parser.add_argument("prompt", nargs="?", default=DEFAULT_PROMPT, help="Text prompt")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output directory (default: {DEFAULT_OUTPUT})",
    )
    resolution_choices = [r.value for r in JimengResolution]

    parser.add_argument(
        "--model",
        choices=model_choices,
        default="jimeng-5.0",
        help=f"Model to use (default: jimeng-5.0). Choices: {', '.join(model_choices)}",
    )
    parser.add_argument(
        "--ratio",
        choices=ratio_choices,
        default="智能",
        help=f"Aspect ratio (default: 智能/smart). Choices: {', '.join(ratio_choices)}",
    )
    parser.add_argument(
        "--resolution",
        choices=resolution_choices,
        default="高清 2K",
        help=f"Resolution (default: 高清 2K). Choices: {', '.join(resolution_choices)}",
    )
    args = parser.parse_args()

    model = MODEL_NAMES[args.model]
    ratio = JimengRatio(args.ratio)
    resolution = JimengResolution(args.resolution)

    asyncio.run(generate(args.prompt, args.output_dir, model, ratio, resolution))
