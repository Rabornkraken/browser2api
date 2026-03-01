<div align="center">

# browser2api

将浏览器 UI 转化为可编程的图像和视频生成 API。

通过 Playwright + Chrome CDP 自动化网页 UI — 无需 API 密钥或逆向工程。

[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://www.python.org)
[![Playwright](https://img.shields.io/badge/Playwright-2EAD33?logo=playwright&logoColor=white)](https://playwright.dev)
[![Chrome CDP](https://img.shields.io/badge/Chrome_CDP-4285F4?logo=googlechrome&logoColor=white)](https://chromedevtools.github.io/devtools-protocol/)

**[English](README.md)** | **[中文](README_CN.md)**

</div>

---

## 支持的平台

<table>
<tr>
<td><img src="https://jimeng.jianying.com/favicon.ico" width="16" height="16" alt="即梦"> <a href="https://jimeng.jianying.com">即梦AI</a></td>
<td>

**图片生成**: 最多4张，支持2K/4K分辨率<br>
**视频生成**: 5秒/10秒，最高1080p

</td>
</tr>
<tr>
<td><img src="https://www.gstatic.com/lamda/images/gemini_favicon_f069958c85030456e93de685481c559f160ea06b.png" width="16" height="16" alt="Google"> <a href="https://labs.google/fx/tools/flow">Google Flow</a></td>
<td>

**图片生成**: 最多4张 (Imagen 4, Nano Banana)<br>
**视频生成**: Veo 3.1 / Veo 2

</td>
</tr>
</table>

## 安装

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
playwright install chromium
```

需要 Python 3.11+ 和本地安装的 Google Chrome。

## 快速开始

### 即梦 — 图片生成

```bash
python examples/generate.py "一只穿着宇航服的猫咪站在月球表面"
python examples/generate.py "提示词" --model jimeng-5.0 --ratio 1:1 --resolution "超清 4K"
```

可用模型: `jimeng-3.0` `jimeng-3.1` `jimeng-4.0` `jimeng-4.1` `jimeng-4.5` `jimeng-4.6` `jimeng-5.0`

### 即梦 — 视频生成

```bash
python examples/generate_video.py "一只猫在花园里散步"
python examples/generate_video.py "城市夜景" --ratio 16:9 --duration 10s --model video-3.0-fast
```

可用模型: `seedance-2.0-fast` `seedance-2.0` `video-3.5-pro` `video-3.0-pro` `video-3.0-fast` `video-3.0`

### Google Flow — 图片生成

```bash
python examples/generate_flow.py "A sunset over mountains, digital art"
python examples/generate_flow.py "prompt" --model imagen-4 --orientation portrait --count 4
```

可用模型: `nano-banana-pro` `nano-banana-2` `imagen-4`

### Google Flow — 视频生成

```bash
python examples/generate_flow_video.py "A cat walking through a garden"
python examples/generate_flow_video.py "prompt" --model veo-3.1-quality --orientation portrait --count 1
```

可用模型: `veo-3.1-fast` `veo-3.1-quality` `veo-2-fast` `veo-2-quality`

## 工作原理

1. **启动** — 通过 CDP 打开真实的 Chrome 浏览器（非 Playwright 内置 Chromium），用于反检测
2. **登录** — 检查有效会话。如未登录，打开有界面的浏览器供手动登录。会话持久化保存在 `~/.browser2api/browser_data/`
3. **生成** — 导航到生成页面，通过 UI 自动化配置模型/设置，填写提示词，点击提交
4. **捕获** — 拦截网络响应并轮询 DOM 获取生成的内容
5. **下载** — 将结果下载到本地

## 编程接口

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
    print(f"状态: {result.status.value}")
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
    print(f"视频: {result.video.local_path} ({result.video.size_bytes:,} bytes)")

    await bm.close()
```

## 注意事项

### 即梦AI

- **建议开通会员** — 视频生成需要会员，图片生成的每日额度也会更高。
- **登录方式** — 首次运行时会打开 Chrome 浏览器窗口，需手动登录。登录状态会保存并在后续运行中复用。
- **4K 分辨率** — 需要会员。免费账户限制为 2K。
- **视频生成耗时** — 根据模型和时长，通常需要 30-120 秒。

### Google Flow

- **需要 Google 账号** — 必须在浏览器中登录 Google 账号。
- **地区限制** — 部分地区可能无法使用，可能需要 VPN。
- **视频生成耗时** — 根据模型不同，通常需要 60-120+ 秒。

## 项目结构

```
src/browser2api/
├── config.py              # 共享常量 (DATA_DIR)
├── types.py               # Platform, GenerationStatus, GeneratedImage, GeneratedVideo 等
├── base.py                # 抽象基类
├── browser.py             # BrowserManager, ChromeLauncher, CDP 连接
└── platforms/
    ├── jimeng/
    │   ├── client.py      # JimengBaseClient, JimengClient, JimengVideoClient
    │   ├── enums.py       # 模型, 比例, 分辨率, 时长
    │   ├── selectors.py   # CSS 选择器和 URL 常量
    │   └── login.py       # 基于 Cookie 的登录处理
    └── flow/
        ├── client.py      # FlowBaseClient, FlowClient, FlowVideoClient
        ├── enums.py       # 模型, 方向, 视频模型
        ├── selectors.py   # CSS 选择器和 URL 常量
        └── login.py       # 登录处理
```

## 免责声明

本项目通过自动化浏览器与第三方平台交互，使用风险自负。

- **速率限制** — 避免过于频繁的使用，请遵守平台的速率限制和额度。
- **会话数据** — 浏览器会话数据（Cookie、本地存储）保存在 `~/.browser2api/`，请妥善保管。
- **仅供个人/研究使用** — 未经平台许可，请勿用于商业用途或大规模使用。
