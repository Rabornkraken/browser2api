# browser2api

Turn browser UIs into programmatic image and video generation APIs via Playwright and Chrome DevTools Protocol (CDP).

Instead of reverse-engineering internal APIs (auth tokens, signatures, anti-bot params), browser2api automates the actual web UI — filling prompts, clicking buttons, and intercepting generated content.

## Supported Platforms

| Platform | Image | Video | Status |
|----------|-------|-------|--------|
| [Jimeng (即梦AI)](https://jimeng.jianying.com) | 4 images, up to 4K | 5s/10s, up to 1080p | Fully implemented |
| [Google Flow](https://labs.google/fx/tools/flow) | 4 images | Veo 3.1 / Veo 2 | Fully implemented |

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
playwright install chromium
```

Requires Python 3.11+ and Google Chrome installed locally.

## Quick Start

### Jimeng — Image Generation

```bash
python examples/generate.py "一只穿着宇航服的猫咪站在月球表面"
python examples/generate.py "prompt" --model jimeng-5.0 --ratio 1:1 --resolution "超清 4K"
```

Available models: `jimeng-3.0`, `jimeng-3.1`, `jimeng-4.0`, `jimeng-4.1`, `jimeng-4.5`, `jimeng-4.6`, `jimeng-5.0`

### Jimeng — Video Generation

```bash
python examples/generate_video.py "一只猫在花园里散步"
python examples/generate_video.py "城市夜景" --ratio 16:9 --duration 10s --model video-3.0-fast
```

Available models: `seedance-2.0-fast`, `seedance-2.0`, `video-3.5-pro`, `video-3.0-pro`, `video-3.0-fast`, `video-3.0`

### Google Flow — Image Generation

```bash
python examples/generate_flow.py "A sunset over mountains, digital art"
python examples/generate_flow.py "prompt" --model nano-banana-2
```

### Google Flow — Video Generation

```bash
python examples/generate_flow_video.py "A cat walking through a garden"
python examples/generate_flow_video.py "prompt" --model veo-3.1-quality --orientation portrait --count 1
```

Available models: `veo-3.1-fast`, `veo-3.1-quality`, `veo-2-fast`, `veo-2-quality`

## Notes

### Jimeng (即梦AI)

- **Member subscription recommended** — A paid membership is required for video generation and provides higher daily quotas for image generation. Free accounts have limited credits and some models/features may not be available.
- **Login** — On first run, a headed Chrome window opens for you to log in manually. The session is saved and reused for subsequent runs. If the session expires, you'll be prompted to log in again automatically.
- **4K resolution** — Requires a member subscription. Free accounts are limited to 2K.
- **Video generation** takes 30-120 seconds depending on the model and duration. The `seedance-2.0` and `video-3.5-pro` models produce higher quality but take longer and cost more credits.

### Google Flow

- **Google account required** — You must be logged into a Google account in the headed browser before generation works.
- **Regional availability** — Google Flow may not be available in all regions. A VPN may be needed.
- **Video generation** takes 60-120+ seconds depending on the model. `veo-3.1-quality` produces higher quality but takes longer.

## How It Works

1. **Launch** — Opens a real Chrome browser via CDP (not Playwright's Chromium) for anti-detection
2. **Login** — Checks for a valid session. If not logged in, prompts you to log in manually in the browser window. Session persists in `~/.browser2api/browser_data/` and is reused for subsequent runs
3. **Generate** — Navigates to the generation page, selects model/settings via UI automation, fills the prompt, clicks submit
4. **Capture** — Intercepts network responses and polls the DOM for generated content (images or video)
5. **Download** — Downloads high-resolution results locally

## Programmatic Usage

```python
import asyncio
from browser2api import BrowserManager, Platform
from browser2api.platforms.jimeng import JimengClient, JimengModel, JimengRatio

async def main():
    bm = BrowserManager()
    context, page = await bm.launch_for_login(Platform.JIMENG)

    client = JimengClient(
        page, context,
        output_dir="./output",
        model=JimengModel.JIMENG_5_0,
        ratio=JimengRatio.RATIO_1_1,
    )

    result = await client.generate_images("一只猫", count=4, timeout_seconds=120)
    print(f"Status: {result.status.value}")
    for img in result.images:
        print(f"  {img.local_path} ({img.width}x{img.height})")

    await bm.close()

asyncio.run(main())
```

```python
from browser2api.platforms.jimeng import (
    JimengVideoClient, JimengVideoModel, JimengVideoDuration
)

async def generate_video():
    bm = BrowserManager()
    context, page = await bm.launch_for_login(Platform.JIMENG)

    client = JimengVideoClient(
        page, context,
        output_dir="./output",
        model=JimengVideoModel.VIDEO_3_0_FAST,
        duration=JimengVideoDuration.FIVE,
    )

    result = await client.generate_video("一只猫在花园里散步", timeout_seconds=300)
    print(f"Video: {result.video.local_path} ({result.video.size_bytes:,} bytes)")

    await bm.close()
```

```python
from browser2api.platforms.flow import FlowVideoClient, FlowVideoModel, FlowOrientation

async def generate_flow_video():
    bm = BrowserManager()
    context, page = await bm.launch_for_login(Platform.FLOW)

    client = FlowVideoClient(
        page, context,
        output_dir="./output",
        model=FlowVideoModel.VEO_3_1_FAST,
        orientation=FlowOrientation.LANDSCAPE,
    )

    result = await client.generate_video("A cat walking through a garden", timeout_seconds=300)
    print(f"Video: {result.video.local_path} ({result.video.size_bytes:,} bytes)")

    await bm.close()
```

## Project Structure

```
src/browser2api/
├── config.py              # Shared constants (DATA_DIR)
├── types.py               # Platform, GenerationStatus, GeneratedImage, GeneratedVideo, etc.
├── base.py                # Abstract base classes (AbstractImageClient, AbstractLoginHandler)
├── browser.py             # BrowserManager, ChromeLauncher, CDP connection
└── platforms/
    ├── jimeng/
    │   ├── client.py      # JimengBaseClient, JimengClient (images), JimengVideoClient (video)
    │   ├── enums.py       # Models, ratios, resolutions, durations
    │   ├── selectors.py   # CSS selectors and URL constants
    │   └── login.py       # Cookie-based login handler
    └── flow/
        ├── client.py      # FlowBaseClient, FlowClient (images), FlowVideoClient (video)
        ├── enums.py       # Models, orientations, video models
        ├── selectors.py   # CSS selectors and URL constants
        └── login.py       # Login handler
```

## Adding a New Platform

1. Create `src/browser2api/platforms/<name>/` with `__init__.py`, `client.py`, `enums.py`, `login.py`
2. Add platform to `Platform` enum in `types.py`
3. Implement client inheriting from `JimengBaseClient` or `AbstractImageClient`
4. Use `BrowserManager.launch_for_login()` for browser lifecycle

## Disclaimer

This project automates browser interactions with third-party platforms. Use at your own risk.

- **Rate limits** — Avoid aggressive usage. Respect platform rate limits and credit quotas.
- **Session data** — Browser session data (cookies, local storage) is stored locally in `~/.browser2api/`. Keep this directory secure as it contains your login sessions.
- **For personal/research use only** — This tool is intended for personal experimentation and research. Do not use it for commercial purposes or at scale without explicit permission from the respective platforms.
