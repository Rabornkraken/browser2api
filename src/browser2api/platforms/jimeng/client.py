"""
即梦AI (Jimeng) image and video generation clients using browser automation.

Instead of calling Jimeng's internal API directly (which requires complex
anti-bot parameters like msToken, a_bogus), we automate the web UI:
  1. Navigate to the generation page
  2. Fill the prompt textarea via React-compatible JS injection
  3. Click the circular submit button
  4. Wait for NEW generated content to appear in the DOM
  5. Download the results locally
"""

import asyncio
import logging
import re
import time
import uuid
from pathlib import Path

import httpx
from playwright.async_api import BrowserContext, Page
from tenacity import retry, stop_after_attempt, wait_fixed

from ...base import AbstractImageClient
from ...config import DATA_DIR
from ...types import (
    GeneratedImage,
    GeneratedVideo,
    GenerationResult,
    GenerationStatus,
    Platform,
    VideoGenerationResult,
)
from .enums import (
    MODEL_UI_LABELS,
    VIDEO_MODEL_UI_LABELS,
    JimengModel,
    JimengRatio,
    JimengResolution,
    JimengVideoDuration,
    JimengVideoModel,
    JimengVideoResolution,
)

logger = logging.getLogger(__name__)

# Local download directory (created lazily on first download)
DOWNLOADS_DIR = DATA_DIR / "downloads" / "jimeng"

GENERATE_URL = "https://jimeng.jianying.com/ai-tool/image/generate"

# JS snippet to collect CDN image URLs currently visible in the DOM
_COLLECT_IMAGES_JS = """() => {
    const imgs = document.querySelectorAll('img');
    const urls = [];
    for (const img of imgs) {
        const src = img.src || '';
        if ((src.includes('byteimg.com') || src.includes('imagex')
             || src.includes('dreamina-sign'))
            && src.length > 100) {
            const rect = img.getBoundingClientRect();
            if (rect.width > 100 && rect.height > 100) {
                urls.push(src);
            }
        }
    }
    return urls;
}"""


class JimengAPIError(Exception):
    """Raised when Jimeng generation fails."""
    pass


class JimengBaseClient:
    """Shared functionality for Jimeng image and video clients.

    Provides common methods for page navigation, prompt filling,
    submit button clicking, file downloading, and output directory management.
    """

    platform = Platform.JIMENG

    def __init__(self, page: Page, context: BrowserContext, output_dir: Path | None = None):
        self.page = page
        self.context = context
        self.output_dir = output_dir or DOWNLOADS_DIR

    async def _check_logged_in(self) -> bool:
        """Check if the user is logged in by looking for session cookies."""
        cookies = await self.context.cookies("https://jimeng.jianying.com")
        for cookie in cookies:
            if cookie["name"] == "sessionid" and cookie["value"]:
                return True
        return False

    async def _wait_for_login(self, timeout_seconds: int = 300) -> bool:
        """Wait for the user to log in manually in the headed browser.

        Polls for the sessionid cookie. Returns True once logged in.
        """
        logger.info("[Jimeng] Not logged in. Please log in manually in the browser window...")
        print("\n*** Please log in to jimeng.jianying.com in the browser window ***\n")

        for i in range(timeout_seconds):
            if await self._check_logged_in():
                logger.info("[Jimeng] Login detected!")
                print("*** Login detected! Continuing... ***\n")
                return True
            if i > 0 and i % 30 == 0:
                logger.info("[Jimeng] Still waiting for login... (%ds/%ds)", i, timeout_seconds)
            await asyncio.sleep(1)

        logger.error("[Jimeng] Login timeout after %ds", timeout_seconds)
        return False

    async def _ensure_generation_page(self) -> None:
        """Navigate to the generation page, ensuring user is logged in first."""
        current = self.page.url
        if "jimeng.jianying.com/ai-tool" not in current:
            await self.page.goto(
                GENERATE_URL,
                wait_until="domcontentloaded",
                timeout=60000,
            )
            await asyncio.sleep(3)

        # Check login status and wait if needed
        if not await self._check_logged_in():
            # Navigate to the main page so the user sees the login UI
            if "jimeng.jianying.com" not in self.page.url:
                await self.page.goto(
                    "https://jimeng.jianying.com",
                    wait_until="domcontentloaded",
                    timeout=60000,
                )
            logged_in = await self._wait_for_login()
            if not logged_in:
                raise JimengAPIError("Login timeout — user did not log in within the time limit")
            # Navigate to generation page after login
            await self.page.goto(
                GENERATE_URL,
                wait_until="domcontentloaded",
                timeout=60000,
            )
            await asyncio.sleep(3)

        # Wait for the page to be fully interactive (textarea should be visible)
        for _ in range(10):
            has_textarea = await self.page.evaluate('''() => {
                const textareas = document.querySelectorAll('textarea');
                for (const ta of textareas) {
                    const rect = ta.getBoundingClientRect();
                    if (rect.width > 200 && rect.height > 30) return true;
                }
                return false;
            }''')
            if has_textarea:
                return
            await asyncio.sleep(1)
        logger.warning("[Jimeng] Textarea not found after waiting — page may not be fully loaded")

    async def _fill_prompt(self, prompt: str) -> bool:
        """Fill the prompt textarea using React-compatible value injection.

        Returns True if the textarea was found and filled.
        """
        result = await self.page.evaluate('''(prompt) => {
            const textareas = document.querySelectorAll('textarea');
            for (const ta of textareas) {
                const rect = ta.getBoundingClientRect();
                if (rect.width > 200 && rect.height > 30) {
                    ta.focus();
                    // React-compatible value setting
                    const setter = Object.getOwnPropertyDescriptor(
                        window.HTMLTextAreaElement.prototype, 'value'
                    ).set;
                    setter.call(ta, prompt);
                    ta.dispatchEvent(new Event('input', { bubbles: true }));
                    ta.dispatchEvent(new Event('change', { bubbles: true }));
                    return true;
                }
            }
            return false;
        }''', prompt)
        return result

    async def _click_submit(self) -> bool:
        """Click the circular primary submit button in the bottom toolbar.

        Returns True if the button was found and clicked.
        """
        for _ in range(10):
            result = await self.page.evaluate('''() => {
                for (const btn of document.querySelectorAll('button')) {
                    const cls = btn.className || '';
                    const r = btn.getBoundingClientRect();
                    if (cls.includes('primary') && cls.includes('circle')
                        && r.top > 400 && r.width > 0
                        && !btn.disabled && !cls.includes('disabled')) {
                        btn.click();
                        return true;
                    }
                }
                return false;
            }''')
            if result:
                return True
            await asyncio.sleep(0.5)
        return False

    def _make_prompt_dir(self, prompt: str) -> Path:
        """Create an output subdirectory named after the prompt and timestamp."""
        safe = re.sub(r'[^\w\s\u4e00-\u9fff\u3400-\u4dbf-]', '', prompt)
        safe = re.sub(r'\s+', '_', safe.strip())
        safe = safe[:60] if len(safe) > 60 else safe
        ts = time.strftime('%Y%m%d_%H%M%S')
        dirname = f"{safe}_{ts}" if safe else ts
        return self.output_dir / dirname

    async def download_file(
        self,
        url: str,
        output_dir: Path | None = None,
        extension: str = ".png",
        timeout: float = 60.0,
    ) -> tuple[Path | None, str | None]:
        """Download a file from a URL and save it locally.

        Returns (local_path, filename) or (None, None) on failure.
        """
        dest = output_dir or self.output_dir
        dest.mkdir(parents=True, exist_ok=True)
        filename = f"{uuid.uuid4().hex}{extension}"
        local_path = dest / filename

        try:
            async with httpx.AsyncClient(timeout=timeout) as http:
                resp = await http.get(url)
                resp.raise_for_status()
                local_path.write_bytes(resp.content)
                logger.info(
                    "[Jimeng] Downloaded file to %s (%d bytes)",
                    local_path, len(resp.content),
                )
                return local_path, filename
        except Exception as e:
            logger.error("[Jimeng] Failed to download file: %s", e)
            return None, None

    async def close(self) -> None:
        """Clean up resources. Page and context managed by BrowserManager."""
        pass


class JimengClient(JimengBaseClient, AbstractImageClient):
    """即梦AI image generation client via browser automation.

    Automates the Jimeng web UI to generate images from text prompts.
    """

    def __init__(
        self,
        page: Page,
        context: BrowserContext,
        output_dir: Path | None = None,
        model: JimengModel = JimengModel.JIMENG_5_0,
        ratio: JimengRatio = JimengRatio.SMART,
        resolution: JimengResolution = JimengResolution.RES_2K,
    ):
        JimengBaseClient.__init__(self, page, context, output_dir)
        AbstractImageClient.__init__(self, page, context)
        self.model = model
        self.ratio = ratio
        self.resolution = resolution
        self._config_applied = False

    async def _setup_generation_config(self) -> None:
        """Configure model/ratio/resolution by clicking UI elements."""
        if self._config_applied:
            return

        await self._select_model()
        await self._select_ratio_and_resolution()
        self._config_applied = True
        logger.info(
            "[JimengClient] Config applied: model=%s, ratio=%s, resolution=%s",
            self.model.name, self.ratio.value, self.resolution.value,
        )

    async def _select_model(self) -> bool:
        """Open the model dropdown and click the option matching self.model."""
        target_label = MODEL_UI_LABELS[self.model]

        # Click the model dropdown (not the type selector that shows "生成")
        opened = await self.page.evaluate("""() => {
            const selects = document.querySelectorAll('.lv-select');
            for (const sel of selects) {
                const text = sel.textContent || '';
                if (text.indexOf('生成') === -1 && sel.getBoundingClientRect().width > 0) {
                    sel.click();
                    return true;
                }
            }
            return false;
        }""")
        if not opened:
            logger.warning("[JimengClient] Could not find model dropdown")
            return False

        await asyncio.sleep(0.5)

        clicked = await self.page.evaluate("""(target) => {
            const options = document.querySelectorAll('.lv-select-option');
            for (const opt of options) {
                // Try specific label class first, then fall back to full option text
                const label = opt.querySelector('[class*="option-label"]');
                const text = (label ? label.textContent : opt.textContent) || '';
                if (text.indexOf(target) !== -1) {
                    opt.click();
                    return text.trim();
                }
            }
            return null;
        }""", target_label)

        if clicked:
            logger.info("[JimengClient] Selected model: %s", clicked)
        else:
            # Log what options are actually available for debugging
            options_text = await self.page.evaluate("""() => {
                const options = document.querySelectorAll('.lv-select-option');
                return Array.from(options).map(o => o.textContent.trim());
            }""")
            logger.warning(
                "[JimengClient] Model '%s' not found in dropdown. Available: %s",
                target_label, options_text,
            )

        await asyncio.sleep(0.3)
        return clicked is not None

    async def _select_ratio_and_resolution(self) -> bool:
        """Open the ratio/resolution popover and click the desired options."""
        opened = await self.page.evaluate("""() => {
            for (const btn of document.querySelectorAll('button')) {
                const text = btn.textContent || '';
                if (text.indexOf('2K') !== -1 || text.indexOf('4K') !== -1
                    || text.indexOf('比例') !== -1) {
                    btn.click();
                    return true;
                }
            }
            return false;
        }""")
        if not opened:
            logger.warning("[JimengClient] Could not find ratio/resolution button")
            return False

        await asyncio.sleep(0.5)

        ratio_text = self.ratio.value
        clicked_ratio = await self.page.evaluate("""(target) => {
            const popover = document.querySelector('.lv-popover-inner-content');
            if (!popover) return null;
            const labels = popover.querySelectorAll('label');
            for (const label of labels) {
                const text = (label.textContent || '').trim();
                if (text === target) {
                    label.click();
                    return text;
                }
            }
            return null;
        }""", ratio_text)

        if clicked_ratio:
            logger.info("[JimengClient] Selected ratio: %s", clicked_ratio)
        else:
            logger.warning("[JimengClient] Ratio '%s' not found in popover", ratio_text)

        await asyncio.sleep(0.3)

        resolution_text = self.resolution.value
        clicked_res = await self.page.evaluate("""(target) => {
            const popover = document.querySelector('.lv-popover-inner-content');
            if (!popover) return null;
            const labels = popover.querySelectorAll('label');
            for (const label of labels) {
                const text = (label.textContent || '').trim();
                if (text === target) {
                    label.click();
                    return text;
                }
            }
            return null;
        }""", resolution_text)

        if clicked_res:
            logger.info("[JimengClient] Selected resolution: %s", clicked_res)
        else:
            logger.warning("[JimengClient] Resolution '%s' not found in popover", resolution_text)

        await asyncio.sleep(0.3)

        await self.page.keyboard.press("Escape")
        await asyncio.sleep(0.3)

        return clicked_ratio is not None

    @staticmethod
    def _read_image_dimensions(path: Path) -> tuple[int | None, int | None]:
        """Read actual pixel dimensions from an image file header.

        Supports WebP and PNG formats (the two formats Jimeng CDN serves).
        """
        try:
            data = path.read_bytes()
            if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
                if data[12:16] == b'VP8 ':
                    w = int.from_bytes(data[26:28], 'little') & 0x3FFF
                    h = int.from_bytes(data[28:30], 'little') & 0x3FFF
                    return w, h
                elif data[12:16] == b'VP8L':
                    bits = int.from_bytes(data[21:25], 'little')
                    w = (bits & 0x3FFF) + 1
                    h = ((bits >> 14) & 0x3FFF) + 1
                    return w, h
                elif data[12:16] == b'VP8X':
                    w = int.from_bytes(data[24:27], 'little') + 1
                    h = int.from_bytes(data[27:30], 'little') + 1
                    return w, h
            if data[:8] == b'\x89PNG\r\n\x1a\n':
                w = int.from_bytes(data[16:20], 'big')
                h = int.from_bytes(data[20:24], 'big')
                return w, h
        except Exception:
            pass
        return None, None

    async def _collect_existing_images(self) -> set[str]:
        """Snapshot all CDN image URLs currently in the DOM."""
        urls = await self.page.evaluate(_COLLECT_IMAGES_JS)
        return set(urls)

    @staticmethod
    def _is_cdn_image_url(url: str) -> bool:
        return (
            ('byteimg.com' in url or 'imagex' in url or 'dreamina-sign' in url)
            and len(url) > 100
        )

    @staticmethod
    def _parse_resize(url: str) -> int:
        """Extract the resize dimension from a CDN URL, or 0 if no resize."""
        m = re.search(r'aigc_resize:(\d+):(\d+)', url)
        return int(m.group(1)) if m else 0

    @staticmethod
    def _extract_hash(url: str) -> str | None:
        """Extract the image resource hash from a CDN URL."""
        m = re.search(r'/([a-f0-9]{32})~', url)
        return m.group(1) if m else None

    async def _get_highres_urls(self, thumbnail_urls: list[str]) -> dict[str, str]:
        """Open the gallery modal and navigate through images to capture high-res URLs.

        Returns a dict mapping thumbnail hash -> high-res URL.
        """
        if not thumbnail_urls:
            return {}

        target_hashes = {}
        for url in thumbnail_urls:
            h = self._extract_hash(url)
            if h:
                target_hashes[h] = None

        captured: dict[str, str] = {}

        def on_response(response):
            url = response.url
            if self._is_cdn_image_url(url):
                h = self._extract_hash(url)
                size = self._parse_resize(url)
                if h and h in target_hashes and size > 0:
                    prev_size = self._parse_resize(captured.get(h, ''))
                    if size > prev_size:
                        captured[h] = url

        try:
            self.page.on('response', on_response)

            clicked = await self.page.evaluate('''(thumbUrl) => {
                for (const img of document.querySelectorAll('img')) {
                    if (img.src === thumbUrl) {
                        img.click();
                        return true;
                    }
                }
                return false;
            }''', thumbnail_urls[0])

            if not clicked:
                logger.warning("[JimengClient] Could not click first thumbnail to open gallery")
                self.page.remove_listener('response', on_response)
                return {}

            await asyncio.sleep(2)

            await self.page.evaluate('''() => {
                const candidates = [];
                for (const img of document.querySelectorAll('img')) {
                    const src = img.src || '';
                    if ((src.includes('byteimg.com') || src.includes('imagex')
                         || src.includes('dreamina-sign'))
                        && src.length > 100) {
                        const rect = img.getBoundingClientRect();
                        if (rect.width > 200 || rect.height > 200) {
                            candidates.push({ el: img, area: rect.width * rect.height });
                        }
                    }
                }
                if (candidates.length > 0) {
                    candidates.sort((a, b) => b.area - a.area);
                    candidates[0].el.click();
                }
            }''')
            await asyncio.sleep(1.5)

            for i in range(len(thumbnail_urls) - 1):
                await self.page.keyboard.press('ArrowRight')
                await asyncio.sleep(1)
                await self.page.evaluate('''() => {
                    const candidates = [];
                    for (const img of document.querySelectorAll('img')) {
                        const src = img.src || '';
                        if ((src.includes('byteimg.com') || src.includes('imagex')
                             || src.includes('dreamina-sign'))
                            && src.length > 100) {
                            const rect = img.getBoundingClientRect();
                            if (rect.width > 200 || rect.height > 200) {
                                candidates.push({ el: img, area: rect.width * rect.height });
                            }
                        }
                    }
                    if (candidates.length > 0) {
                        candidates.sort((a, b) => b.area - a.area);
                        candidates[0].el.click();
                    }
                }''')
                await asyncio.sleep(1.5)

            self.page.remove_listener('response', on_response)

            await self.page.keyboard.press('Escape')
            await asyncio.sleep(0.3)
            await self.page.keyboard.press('Escape')
            await asyncio.sleep(0.3)

            logger.info(
                "[JimengClient] Captured high-res URLs for %d/%d images",
                len(captured), len(target_hashes),
            )
            return captured

        except Exception as e:
            logger.error("[JimengClient] Error in gallery navigation: %s", e)
            try:
                self.page.remove_listener('response', on_response)
            except Exception:
                pass
            try:
                await self.page.keyboard.press('Escape')
                await asyncio.sleep(0.2)
                await self.page.keyboard.press('Escape')
            except Exception:
                pass
            return captured

    async def _wait_for_new_images(
        self,
        existing: set[str],
        expected_count: int = 4,
        timeout_seconds: int = 120,
    ) -> list[str]:
        """Wait for new images to appear. Returns as many as found within timeout."""
        last_count = 0
        stable_ticks = 0

        for i in range(timeout_seconds):
            await asyncio.sleep(1)
            current_urls = await self.page.evaluate(_COLLECT_IMAGES_JS)
            new_urls = [u for u in current_urls if u not in existing]

            if len(new_urls) >= expected_count:
                return new_urls[:expected_count]

            if len(new_urls) == last_count:
                stable_ticks += 1
            else:
                stable_ticks = 0
                last_count = len(new_urls)

            if new_urls and stable_ticks >= 15:
                logger.info(
                    "[JimengClient] Stable at %d images after %ds, returning",
                    len(new_urls), i,
                )
                return new_urls

            if i > 0 and i % 15 == 0:
                logger.info(
                    "[JimengClient] Waiting for images... %d/%d (%ds/%ds)",
                    len(new_urls), expected_count, i, timeout_seconds,
                )

        current_urls = await self.page.evaluate(_COLLECT_IMAGES_JS)
        return [u for u in current_urls if u not in existing]

    async def download_image(
        self,
        cdn_url: str,
        output_dir: Path | None = None,
    ) -> tuple[Path | None, str | None]:
        """Download an image from the CDN and save it locally.

        Returns (local_path, filename) or (None, None) on failure.
        """
        return await self.download_file(cdn_url, output_dir=output_dir, extension=".png")

    @retry(stop=stop_after_attempt(2), wait=wait_fixed(3))
    async def generate_images(
        self,
        prompt: str,
        count: int = 4,
        timeout_seconds: int = 120,
    ) -> GenerationResult:
        """Generate images from a text prompt.

        Fills the prompt textarea, clicks submit, waits for new images
        to appear in the DOM, then downloads them.
        """
        logger.info("[JimengClient] Generating %d images: %s", count, prompt[:80])
        start_time = time.monotonic()

        await self._ensure_generation_page()
        await self._setup_generation_config()
        existing_images = await self._collect_existing_images()

        filled = await self._fill_prompt(prompt)
        if not filled:
            return GenerationResult(
                platform=Platform.JIMENG,
                prompt=prompt,
                status=GenerationStatus.FAILED,
                error="Could not find prompt textarea",
                duration_ms=int((time.monotonic() - start_time) * 1000),
            )
        await asyncio.sleep(0.5)

        clicked = await self._click_submit()
        if not clicked:
            return GenerationResult(
                platform=Platform.JIMENG,
                prompt=prompt,
                status=GenerationStatus.FAILED,
                error="Could not find or click submit button",
                duration_ms=int((time.monotonic() - start_time) * 1000),
            )

        logger.info("[JimengClient] Prompt submitted, waiting for %d images...", count)

        all_new = await self._wait_for_new_images(
            existing_images,
            expected_count=count,
            timeout_seconds=timeout_seconds,
        )

        if not all_new:
            return GenerationResult(
                platform=Platform.JIMENG,
                prompt=prompt,
                status=GenerationStatus.FAILED,
                error="No images generated (timeout)",
                duration_ms=int((time.monotonic() - start_time) * 1000),
            )

        logger.info("[JimengClient] Got %d new thumbnail URLs, fetching high-res...", len(all_new))

        prompt_dir = self._make_prompt_dir(prompt)
        highres_map = await self._get_highres_urls(all_new)

        images: list[GeneratedImage] = []
        for cdn_url in all_new:
            img_hash = self._extract_hash(cdn_url)
            highres_url = highres_map.get(img_hash) if img_hash else None
            download_url = highres_url or cdn_url
            is_highres = highres_url is not None

            local_path, filename = await self.download_image(download_url, output_dir=prompt_dir)
            w, h = None, None
            if local_path:
                w, h = self._read_image_dimensions(local_path)
            images.append(GeneratedImage(
                url=download_url,
                local_path=str(local_path) if local_path else None,
                filename=filename,
                width=w,
                height=h,
                is_highres=is_highres,
            ))

        duration_ms = int((time.monotonic() - start_time) * 1000)
        logger.info(
            "[JimengClient] Downloaded %d images in %dms",
            len(images), duration_ms,
        )

        return GenerationResult(
            platform=Platform.JIMENG,
            prompt=prompt,
            images=images,
            status=GenerationStatus.COMPLETED,
            duration_ms=duration_ms,
            model=self.model.value,
        )


class JimengVideoClient(JimengBaseClient):
    """即梦AI video generation client via browser automation.

    Automates the Jimeng web UI to generate videos from text prompts.
    Flow:
    1. Navigate to the generation page
    2. Switch to video mode via the type selector dropdown
    3. Select video model, ratio, duration
    4. Fill the prompt textarea
    5. Click the submit button
    6. Wait for the video to appear (intercept network responses for MP4 URLs)
    7. Download the video
    """

    VIDEO_GENERATE_URL = "https://jimeng.jianying.com/ai-tool/image/generate"

    def __init__(
        self,
        page: Page,
        context: BrowserContext,
        output_dir: Path | None = None,
        model: JimengVideoModel = JimengVideoModel.VIDEO_3_0_FAST,
        ratio: JimengRatio = JimengRatio.RATIO_16_9,
        resolution: JimengVideoResolution = JimengVideoResolution.RES_720P,
        duration: JimengVideoDuration = JimengVideoDuration.FIVE,
    ):
        super().__init__(page, context, output_dir)
        self.model = model
        self.ratio = ratio
        self.resolution = resolution
        self.duration = duration
        self._config_applied = False

    async def _switch_to_video_mode(self) -> bool:
        """Click the type selector dropdown and select '视频生成'."""
        # Click the lv-select that contains "生成" (the type selector)
        opened = await self.page.evaluate(r"""() => {
            const selects = document.querySelectorAll('.lv-select');
            for (const sel of selects) {
                const text = sel.textContent || '';
                if (text.indexOf('\u751f\u6210') !== -1) {
                    sel.click();
                    return true;
                }
            }
            return false;
        }""")
        if not opened:
            logger.warning("[JimengVideoClient] Could not find type selector dropdown")
            return False

        await asyncio.sleep(0.5)

        # Click "视频生成" option
        clicked = await self.page.evaluate(r"""() => {
            const options = document.querySelectorAll('.lv-select-option');
            for (const opt of options) {
                const text = (opt.textContent || '').trim();
                if (text.indexOf('\u89c6\u9891\u751f\u6210') !== -1) {
                    opt.click();
                    return true;
                }
            }
            return false;
        }""")

        if clicked:
            logger.info("[JimengVideoClient] Switched to video generation mode")
            await asyncio.sleep(1)
        else:
            logger.warning("[JimengVideoClient] Could not find '视频生成' option")

        return bool(clicked)

    async def _select_video_model(self) -> bool:
        """Select the video model from the model dropdown."""
        target_label = VIDEO_MODEL_UI_LABELS[self.model]

        # Click the model dropdown (NOT the type selector that shows "生成")
        opened = await self.page.evaluate(r"""() => {
            const selects = document.querySelectorAll('.lv-select');
            for (const sel of selects) {
                const text = sel.textContent || '';
                if (text.indexOf('\u751f\u6210') === -1
                    && sel.getBoundingClientRect().width > 0) {
                    sel.click();
                    return true;
                }
            }
            return false;
        }""")
        if not opened:
            logger.warning("[JimengVideoClient] Could not find model dropdown")
            return False

        await asyncio.sleep(0.5)

        clicked = await self.page.evaluate("""(target) => {
            const options = document.querySelectorAll('.lv-select-option');
            for (const opt of options) {
                const text = (opt.textContent || '').trim();
                if (text.indexOf(target) !== -1) {
                    opt.click();
                    return text;
                }
            }
            return null;
        }""", target_label)

        if clicked:
            logger.info("[JimengVideoClient] Selected model: %s", clicked)
        else:
            logger.warning("[JimengVideoClient] Model '%s' not found in dropdown", target_label)

        await asyncio.sleep(0.3)
        return clicked is not None

    async def _select_video_ratio(self) -> bool:
        """Select the aspect ratio from the ratio popover."""
        ratio_text = self.ratio.value

        # Click the ratio button to open the popover
        opened = await self.page.evaluate(r"""() => {
            for (const btn of document.querySelectorAll('button')) {
                const text = btn.textContent || '';
                if (text.indexOf('720') !== -1 || text.indexOf('1080') !== -1
                    || text.indexOf('\u6bd4\u4f8b') !== -1
                    || text.indexOf('16:9') !== -1 || text.indexOf('9:16') !== -1
                    || text.indexOf('1:1') !== -1 || text.indexOf('4:3') !== -1) {
                    btn.click();
                    return true;
                }
            }
            return false;
        }""")
        if not opened:
            logger.warning("[JimengVideoClient] Could not find ratio button")
            return False

        await asyncio.sleep(0.5)

        clicked = await self.page.evaluate("""(target) => {
            const popover = document.querySelector('.lv-popover-inner-content');
            if (!popover) return null;
            const labels = popover.querySelectorAll('label');
            for (const label of labels) {
                const text = (label.textContent || '').trim();
                if (text === target) {
                    label.click();
                    return text;
                }
            }
            return null;
        }""", ratio_text)

        if clicked:
            logger.info("[JimengVideoClient] Selected ratio: %s", clicked)
        else:
            logger.warning("[JimengVideoClient] Ratio '%s' not found", ratio_text)

        await asyncio.sleep(0.3)
        return clicked is not None

    async def _select_video_duration(self) -> bool:
        """Select the video duration from the duration selector."""
        duration_label = f"{self.duration.value // 1000}s"

        clicked = await self.page.evaluate("""(target) => {
            // Look for duration labels/buttons in the page
            for (const el of document.querySelectorAll('label, button, span, div')) {
                const text = (el.textContent || '').trim();
                if (text === target && el.getBoundingClientRect().width > 0) {
                    el.click();
                    return text;
                }
            }
            return null;
        }""", duration_label)

        if clicked:
            logger.info("[JimengVideoClient] Selected duration: %s", clicked)
        else:
            logger.warning("[JimengVideoClient] Duration '%s' not found", duration_label)

        await asyncio.sleep(0.3)
        return clicked is not None

    async def _select_video_resolution(self) -> bool:
        """Select the video resolution."""
        res_text = self.resolution.value.upper()  # "720P" or "1080P"

        clicked = await self.page.evaluate("""(target) => {
            for (const el of document.querySelectorAll('label, button, span, div')) {
                const text = (el.textContent || '').trim();
                if (text === target && el.getBoundingClientRect().width > 0) {
                    el.click();
                    return text;
                }
            }
            return null;
        }""", res_text)

        if clicked:
            logger.info("[JimengVideoClient] Selected resolution: %s", clicked)

        await asyncio.sleep(0.3)
        return clicked is not None

    async def _setup_video_config(self) -> None:
        """Switch to video mode and configure model/ratio/duration/resolution."""
        if self._config_applied:
            return

        await self._switch_to_video_mode()
        await asyncio.sleep(1)
        await self._select_video_model()
        await self._select_video_ratio()
        await self._select_video_duration()
        await self._select_video_resolution()
        self._config_applied = True
        logger.info(
            "[JimengVideoClient] Config applied: model=%s, ratio=%s, "
            "resolution=%s, duration=%ds",
            self.model.name, self.ratio.value,
            self.resolution.value, self.duration.value // 1000,
        )

    @staticmethod
    def _is_video_cdn_url(url: str) -> bool:
        """Check if a URL is a real generated video (not a static asset)."""
        if not url:
            return False
        # Must look like a CDN video URL
        is_cdn = (
            ('byteimg.com' in url or 'vlabvod' in url
             or 'jimeng' in url or 'bytevod' in url
             or 'capcut' in url)
            and ('.mp4' in url or 'video' in url.lower())
        )
        if not is_cdn:
            return False
        # Exclude static assets (loading animations, UI elements)
        static_patterns = ('static/media', 'animation', 'loading', 'lottie',
                           'assets/', 'icon', 'placeholder')
        return not any(p in url.lower() for p in static_patterns)

    async def _wait_for_video(
        self,
        timeout_seconds: int = 300,
    ) -> str | None:
        """Wait for video generation to complete by intercepting network responses.

        Also monitors the DOM for failure indicators.
        Returns the video URL or None on timeout/failure.
        """
        captured_url: list[str] = []

        def on_response(response):
            url = response.url
            if self._is_video_cdn_url(url) and url not in captured_url:
                captured_url.append(url)
                logger.info("[JimengVideoClient] Captured video URL: %s", url[:120])

        self.page.on('response', on_response)

        try:
            for i in range(timeout_seconds):
                if captured_url:
                    return captured_url[0]

                await asyncio.sleep(1)

                # Check for failure in the DOM — look for error toasts/modals,
                # not the full body text (which may contain "生成失败" as a label)
                if i > 15 and i % 10 == 0:
                    error_msg = await self.page.evaluate(r"""() => {
                        // Check toast/notification messages
                        const toasts = document.querySelectorAll(
                            '.lv-notification, .lv-message, .lv-toast, '
                            + '[class*="toast"], [class*="notification"], [class*="error-"]'
                        );
                        for (const t of toasts) {
                            const text = (t.textContent || '').trim();
                            if (text.indexOf('\u5931\u8d25') !== -1
                                || text.indexOf('\u9519\u8bef') !== -1
                                || text.indexOf('\u7a7a\u95f4\u4e0d\u8db3') !== -1) {
                                return text.substring(0, 200);
                            }
                        }
                        return null;
                    }""")
                    if error_msg:
                        logger.warning("[JimengVideoClient] Generation failed: %s", error_msg)
                        return None

                # Check for a video element in the DOM
                if i > 10 and i % 10 == 0:
                    video_src = await self.page.evaluate("""() => {
                        const videos = document.querySelectorAll('video source, video');
                        for (const v of videos) {
                            const src = v.src || v.getAttribute('src') || '';
                            if (src && src.length > 50 && !src.includes('loading')
                                && !src.includes('animation') && !src.includes('static')) {
                                return src;
                            }
                        }
                        return null;
                    }""")
                    if video_src:
                        logger.info("[JimengVideoClient] Found video in DOM: %s", video_src[:120])
                        return video_src

                if i > 0 and i % 30 == 0:
                    logger.info(
                        "[JimengVideoClient] Waiting for video... (%ds/%ds)",
                        i, timeout_seconds,
                    )
        finally:
            try:
                self.page.remove_listener('response', on_response)
            except Exception:
                pass

        return None

    async def download_video(
        self,
        url: str,
        output_dir: Path | None = None,
    ) -> tuple[Path | None, str | None]:
        """Download a video file. Returns (local_path, filename) or (None, None)."""
        return await self.download_file(url, output_dir=output_dir, extension=".mp4", timeout=120.0)

    @retry(stop=stop_after_attempt(2), wait=wait_fixed(3))
    async def generate_video(
        self,
        prompt: str,
        timeout_seconds: int = 300,
    ) -> VideoGenerationResult:
        """Generate a video from a text prompt via browser automation.

        1. Navigate to the generation page
        2. Switch to video mode and configure settings
        3. Fill prompt and click submit
        4. Wait for the video to appear
        5. Download the video
        """
        logger.info("[JimengVideoClient] Generating video: %s", prompt[:80])
        start_time = time.monotonic()

        await self._ensure_generation_page()
        await self._setup_video_config()

        filled = await self._fill_prompt(prompt)
        if not filled:
            return VideoGenerationResult(
                platform=Platform.JIMENG,
                prompt=prompt,
                status=GenerationStatus.FAILED,
                error="Could not find prompt textarea",
                duration_ms=int((time.monotonic() - start_time) * 1000),
            )
        await asyncio.sleep(0.5)

        clicked = await self._click_submit()
        if not clicked:
            return VideoGenerationResult(
                platform=Platform.JIMENG,
                prompt=prompt,
                status=GenerationStatus.FAILED,
                error="Could not find or click submit button",
                duration_ms=int((time.monotonic() - start_time) * 1000),
            )

        logger.info("[JimengVideoClient] Prompt submitted, waiting for video...")

        video_url = await self._wait_for_video(timeout_seconds=timeout_seconds)

        if not video_url:
            return VideoGenerationResult(
                platform=Platform.JIMENG,
                prompt=prompt,
                status=GenerationStatus.FAILED,
                error="No video generated (timeout or failure)",
                duration_ms=int((time.monotonic() - start_time) * 1000),
            )

        # Download
        logger.info("[JimengVideoClient] Downloading video: %s", video_url[:120])
        prompt_dir = self._make_prompt_dir(prompt)
        local_path, filename = await self.download_video(video_url, output_dir=prompt_dir)

        size_bytes = None
        if local_path and local_path.exists():
            size_bytes = local_path.stat().st_size

        video = GeneratedVideo(
            url=video_url,
            local_path=str(local_path) if local_path else None,
            filename=filename,
            size_bytes=size_bytes,
        )

        duration_ms = int((time.monotonic() - start_time) * 1000)
        logger.info(
            "[JimengVideoClient] Video complete in %dms (%s bytes)",
            duration_ms, size_bytes or "?",
        )

        return VideoGenerationResult(
            platform=Platform.JIMENG,
            prompt=prompt,
            video=video,
            status=GenerationStatus.COMPLETED,
            duration_ms=duration_ms,
            model=self.model.name,
        )
