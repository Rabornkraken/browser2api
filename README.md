<div align="center">

# browser2api

Turn browser UIs into programmatic image and video generation APIs.

Automates web UIs via Playwright + Chrome CDP — no API keys or reverse engineering needed.

[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://www.python.org)
[![Playwright](https://img.shields.io/badge/Playwright-2EAD33?logo=playwright&logoColor=white)](https://playwright.dev)
[![Chrome CDP](https://img.shields.io/badge/Chrome_CDP-4285F4?logo=googlechrome&logoColor=white)](https://chromedevtools.github.io/devtools-protocol/)

**[English](README.md)** | **[中文](README_CN.md)**

</div>

---

## Supported Platforms

<table>
<tr>
<td><img src="https://www.google.com/s2/favicons?domain=jimeng.jianying.com&sz=32" width="16" height="16" alt="Jimeng"> <a href="https://jimeng.jianying.com">Jimeng (即梦AI)</a></td>
<td>

**Image**: Seedream 5.0 — up to 4 images, 2K/4K<br>
**Video**: Seedance 2.0 — 5s/10s, up to 1080p

</td>
</tr>
<tr>
<td><img src="https://www.gstatic.com/lamda/images/gemini_favicon_f069958c85030456e93de685481c559f160ea06b.png" width="16" height="16" alt="Google"> <a href="https://labs.google/fx/tools/flow">Google Flow</a></td>
<td>

**Image**: Imagen 4, Nano Banana 2 — up to 4 images<br>
**Video**: Veo 3.1 — Fast / Quality

</td>
</tr>
</table>

## Demo

> Jimeng — Image Generation with **Seedream 5.0** · *"A Shiba Inu eating ramen in a ramen shop, anime style"*

https://github.com/user-attachments/assets/jimeng_image_gen.mp4

> Google Flow — Image Generation with **Nano Banana 2** · *"Shiba eating ramen, anime style"*

https://github.com/user-attachments/assets/flow_image_gen.mp4

> Google Flow — Video Generation with **Veo 3.1 Fast** · *"A cat walking through a garden"*

https://github.com/user-attachments/assets/flow_video_gen.mp4

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
python examples/generate.py "A cat in an astronaut suit standing on the moon"
python examples/generate.py "prompt" --model jimeng-5.0 --ratio 1:1 --resolution "超清 4K"
```

Models: `jimeng-3.0` `jimeng-3.1` `jimeng-4.0` `jimeng-4.1` `jimeng-4.5` `jimeng-4.6` `jimeng-5.0`

### Jimeng — Video Generation

```bash
python examples/generate_video.py "A cat walking through a garden"
python examples/generate_video.py "City night skyline" --ratio 16:9 --duration 10s --model video-3.0-fast
```

Models: `seedance-2.0-fast` `seedance-2.0` `video-3.5-pro` `video-3.0-pro` `video-3.0-fast` `video-3.0`

### Google Flow — Image Generation

```bash
python examples/generate_flow.py "A sunset over mountains, digital art"
python examples/generate_flow.py "prompt" --model nano-banana-2 --orientation portrait --count 4
```

Models: `nano-banana-pro` `nano-banana-2` `imagen-4`

### Google Flow — Video Generation

```bash
python examples/generate_flow_video.py "A cat walking through a garden"
python examples/generate_flow_video.py "prompt" --model veo-3.1-quality --orientation portrait --count 1
```

Models: `veo-3.1-fast` `veo-3.1-quality` `veo-2-fast` `veo-2-quality`

## How It Works

1. **Launch** — Opens a real Chrome browser via CDP (not Playwright's bundled Chromium) for anti-detection
2. **Login** — Checks for a valid session. If not logged in, opens a headed browser for manual login. Session persists in `~/.browser2api/browser_data/`
3. **Generate** — Navigates to the generation page, configures model/settings via UI automation, fills the prompt, clicks submit
4. **Capture** — Intercepts network responses and polls the DOM for generated content
5. **Download** — Downloads results locally

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

## Notes

### Jimeng (即梦AI)

- **Member subscription recommended** — Required for video generation and higher daily image quotas.
- **Login** — First run opens a headed Chrome window for manual login. Session is saved and reused.
- **4K resolution** — Requires membership. Free accounts are limited to 2K.
- **Video generation** — 30-120s depending on model/duration.

### Google Flow

- **Google account required** — Must be logged in via the headed browser.
- **Regional availability** — May require a VPN in some regions.
- **Video generation** — 60-120+s depending on model.

## Project Structure

```
src/browser2api/
├── config.py              # Shared constants (DATA_DIR)
├── types.py               # Platform, GenerationStatus, GeneratedImage, GeneratedVideo, etc.
├── base.py                # Abstract base classes
├── browser.py             # BrowserManager, ChromeLauncher, CDP connection
└── platforms/
    ├── jimeng/
    │   ├── client.py      # JimengBaseClient, JimengClient, JimengVideoClient
    │   ├── enums.py       # Models, ratios, resolutions, durations
    │   ├── selectors.py   # CSS selectors and URL constants
    │   └── login.py       # Cookie-based login handler
    └── flow/
        ├── client.py      # FlowBaseClient, FlowClient, FlowVideoClient
        ├── enums.py       # Models, orientations, video models
        ├── selectors.py   # CSS selectors and URL constants
        └── login.py       # Login handler
```

## Disclaimer

This project automates browser interactions with third-party platforms. Use at your own risk.

- **Rate limits** — Avoid aggressive usage. Respect platform rate limits and credit quotas.
- **Session data** — Stored locally in `~/.browser2api/`. Keep this directory secure.
- **For personal/research use only** — Do not use for commercial purposes or at scale without permission from the respective platforms.
