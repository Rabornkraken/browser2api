"""Test video generation in headed mode to check if headless is the issue."""

import asyncio
import logging

from browser2api import BrowserManager, Platform
from browser2api.platforms.jimeng.client import JimengVideoClient
from browser2api.platforms.jimeng.enums import JimengRatio, JimengVideoDuration, JimengVideoModel, JimengVideoResolution
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

OUTPUT = Path(__file__).resolve().parent.parent / "output"


async def test():
    bm = BrowserManager()
    try:
        # Use launch_for_login which is headed
        context, page = await bm.launch_for_login(Platform.JIMENG)

        client = JimengVideoClient(
            page, context,
            output_dir=OUTPUT,
            model=JimengVideoModel.VIDEO_3_0_FAST,
            ratio=JimengRatio.RATIO_16_9,
            resolution=JimengVideoResolution.RES_720P,
            duration=JimengVideoDuration.FIVE,
        )

        prompt = "一朵花慢慢绽放"
        print(f"Generating video (HEADED mode): {prompt}")

        result = await client.generate_video(prompt, timeout_seconds=300)

        print(f"\nStatus: {result.status.value}")
        if result.error:
            print(f"Error: {result.error}")
        print(f"Duration: {result.duration_ms}ms")
        if result.video:
            print(f"Video: {result.video.filename} ({result.video.size_bytes} bytes)")
            print(f"       {result.video.local_path}")
        else:
            print("Video: None")
    finally:
        await bm.close()


asyncio.run(test())
