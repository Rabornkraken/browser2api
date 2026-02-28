"""Interactive login flow for a platform.

Usage:
    python examples/login.py          # defaults to jimeng
    python examples/login.py gemini
"""

import asyncio
import logging
import sys

from browser2api import BrowserManager, Platform
from browser2api.platforms.jimeng import JimengLoginHandler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

HANDLERS = {
    Platform.JIMENG: JimengLoginHandler,
}


async def login(platform: Platform):
    handler_cls = HANDLERS.get(platform)
    if handler_cls is None:
        print(f"Login not yet implemented for {platform.value}")
        return

    bm = BrowserManager()
    handler = handler_cls()

    try:
        print(f"\nLaunching browser for {platform.value} login...")
        context, page = await bm.launch_for_login(platform)

        success = await handler.login(page)
        if success:
            print(f"\n[OK] {platform.value} login successful! Session saved.")
        else:
            print(f"\n[FAIL] {platform.value} login failed or timed out.")
    finally:
        await bm.close()


if __name__ == "__main__":
    platform_name = sys.argv[1] if len(sys.argv) > 1 else "jimeng"
    try:
        platform = Platform(platform_name)
    except ValueError:
        print(f"Unknown platform: {platform_name}")
        print(f"Available: {', '.join(p.value for p in Platform)}")
        sys.exit(1)

    asyncio.run(login(platform))
