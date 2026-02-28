"""
Google Flow image and video generation clients using browser automation.

Flow is a project-based generation UI at labs.google/fx/tools/flow.
The user lands on a project listing page, clicks "+ New project" to enter
the editor, then uses a bottom prompt bar with a contenteditable div,
a model selector button, and a submit (arrow_forward) button.

Images appear in the workspace and are served via signed GCS URLs.
Videos are served via storage.googleapis.com signed URLs.
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
    COUNT_UI_LABELS,
    MODEL_UI_LABELS,
    ORIENTATION_UI_LABELS,
    VIDEO_MODEL_UI_LABELS,
    FlowCount,
    FlowModel,
    FlowOrientation,
    FlowVideoModel,
)
from .selectors import TOOL_URL

logger = logging.getLogger(__name__)

# Local download directory (created lazily on first download)
DOWNLOADS_DIR = DATA_DIR / "downloads" / "flow"

# JS snippet to collect image URLs currently visible in the DOM.
# Flow serves images via labs.google/fx/api/trpc/media redirect URLs
# and also googleusercontent.com CDN.
_COLLECT_IMAGES_JS = """() => {
    const imgs = document.querySelectorAll('img');
    const urls = [];
    for (const img of imgs) {
        const src = img.src || '';
        if (src.length > 30) {
            const rect = img.getBoundingClientRect();
            if (rect.width > 100 && rect.height > 100
                && (src.includes('labs.google/fx/api/')
                    || src.includes('googleusercontent.com')
                    || src.includes('lh3.google')
                    || src.includes('gstatic.com'))) {
                urls.push(src);
            }
        }
    }
    return urls;
}"""


class FlowAPIError(Exception):
    """Raised when Flow generation fails."""
    pass


class FlowBaseClient:
    """Shared functionality for Flow image and video clients.

    Provides common methods for page navigation, config panel interaction,
    prompt filling, submit button clicking, file downloading, and output
    directory management.
    """

    platform = Platform.FLOW

    def __init__(self, page: Page, context: BrowserContext, output_dir: Path | None = None):
        self.page = page
        self.context = context
        self.output_dir = output_dir or DOWNLOADS_DIR

    async def _ensure_generation_page(self) -> None:
        """Navigate to Flow and ensure we're inside a project editor.

        Flow has two states:
        1. Project listing (URL ends with /flow) — need to enter a project
        2. Project editor (URL contains /project/<uuid>) — ready to generate

        If on the listing page, dismisses any announcement banner, then opens
        the most recent existing project. Only creates a new project if none exist.
        """
        current = self.page.url
        if "labs.google/fx/tools/flow" not in current:
            try:
                await self.page.goto(
                    TOOL_URL,
                    wait_until="commit",
                    timeout=60000,
                )
            except Exception as e:
                logger.warning("[Flow] Navigation note: %s", e)
            await asyncio.sleep(5)
            current = self.page.url

        # Already inside a project
        if "/project/" in current:
            logger.info("[Flow] Already in project editor")
            return

        # On listing page — dismiss banner, then open existing project or create new
        logger.info("[Flow] On listing page, entering project...")

        # Dismiss announcement banner if present
        await self.page.evaluate("""() => {
            for (const btn of document.querySelectorAll('button')) {
                if ((btn.textContent || '').trim() === 'close') {
                    btn.click();
                    return true;
                }
            }
            return false;
        }""")
        await asyncio.sleep(1)

        # Try clicking the most recent existing project thumbnail first.
        clicked = await self.page.evaluate("""() => {
            // Look for project card links/clickable areas
            for (const a of document.querySelectorAll('a[href*="/project/"]')) {
                const rect = a.getBoundingClientRect();
                if (rect.width > 50 && rect.height > 50) {
                    a.click();
                    return 'existing';
                }
            }
            // Fallback: click any large clickable element that isn't "New project"
            for (const el of document.querySelectorAll(
                '[role="link"], [role="button"], div, button'
            )) {
                const text = (el.textContent || '').trim();
                const rect = el.getBoundingClientRect();
                if (rect.width > 100 && rect.height > 100
                    && !text.includes('New project')
                    && !text.includes('new project')
                    && el.onclick !== null) {
                    el.click();
                    return 'existing';
                }
            }
            // No existing projects — click "+ New project"
            for (const btn of document.querySelectorAll('button')) {
                if ((btn.textContent || '').trim().includes('New project')) {
                    btn.click();
                    return 'new';
                }
            }
            return null;
        }""")

        if clicked == 'existing':
            await asyncio.sleep(5)
            logger.info("[Flow] Opened existing project, URL: %s", self.page.url)
        elif clicked == 'new':
            await asyncio.sleep(5)
            logger.info("[Flow] Created new project, URL: %s", self.page.url)
        else:
            logger.warning("[Flow] Could not find any project or 'New project' button")

        # Wait for the prompt bar to appear (contenteditable div or config button)
        for _ in range(20):
            ready = await self.page.evaluate("""() => {
                const ce = document.querySelector('[contenteditable="true"]');
                const btn = document.querySelector('button[aria-haspopup="menu"]');
                if (ce && btn) {
                    const r1 = ce.getBoundingClientRect();
                    const r2 = btn.getBoundingClientRect();
                    return r1.width > 50 && r2.width > 50;
                }
                return false;
            }""")
            if ready:
                break
            await asyncio.sleep(1)
        else:
            logger.warning("[Flow] Prompt bar did not appear within 20s")

    async def _open_config_panel(self) -> bool:
        """Click the main config button in the prompt bar to open the panel.

        The config button is the wide haspopup="menu" button containing
        a model name (Banana/Imagen/Veo) in the bottom prompt bar.
        """
        btn = await self.page.evaluate("""() => {
            for (const b of document.querySelectorAll('button[aria-haspopup="menu"]')) {
                const text = (b.textContent || '').trim();
                const rect = b.getBoundingClientRect();
                if (rect.width > 100 && rect.height > 20
                    && (text.includes('Banana') || text.includes('Imagen')
                        || text.includes('Veo'))) {
                    return { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 };
                }
            }
            return null;
        }""")
        if not btn:
            logger.warning("[Flow] Could not find config panel button")
            return False
        await self.page.mouse.click(btn['x'], btn['y'])
        await asyncio.sleep(1)
        # Verify panel opened by checking for [role="tab"] elements
        tab_count = await self.page.evaluate("""() => {
            return document.querySelectorAll('[role="tab"]').length;
        }""")
        if tab_count < 4:
            logger.warning("[Flow] Config panel may not have opened (tabs=%d)", tab_count)
            return False
        return True

    async def _click_tab(self, target_text: str) -> str | None:
        """Find a visible [role="tab"] matching target_text and click it via mouse.

        Returns 'already' if already selected, 'clicked' if newly clicked, None if not found.
        """
        tab_info = await self.page.evaluate("""(target) => {
            for (const tab of document.querySelectorAll('[role="tab"]')) {
                const text = (tab.textContent || '').trim();
                if (text.includes(target)) {
                    const rect = tab.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0) {
                        return {
                            selected: tab.getAttribute('aria-selected') === 'true',
                            x: rect.x + rect.width / 2,
                            y: rect.y + rect.height / 2,
                        };
                    }
                }
            }
            return null;
        }""", target_text)

        if not tab_info:
            return None
        if tab_info['selected']:
            return 'already'
        await self.page.mouse.click(tab_info['x'], tab_info['y'])
        await asyncio.sleep(0.5)
        return 'clicked'

    async def _fill_prompt(self, prompt: str) -> bool:
        """Fill the prompt contenteditable div using Playwright native typing.

        Uses real keyboard events (click to focus, Ctrl+A to select all,
        then type) for framework compatibility.

        Returns True if the prompt was filled successfully.
        """
        # Click the contenteditable div to focus it
        try:
            editable = self.page.locator('[contenteditable="true"]').first
            if await editable.count() > 0:
                await editable.click()
                await asyncio.sleep(0.3)
                # Select all existing text and replace
                await self.page.keyboard.press("Meta+a")
                await asyncio.sleep(0.1)
                await self.page.keyboard.type(prompt, delay=10)
                await asyncio.sleep(0.3)

                # Verify text was entered
                text = await editable.text_content()
                if text and prompt[:20] in text:
                    logger.info("[Flow] Filled prompt via contenteditable typing")
                    return True
        except Exception as e:
            logger.warning("[Flow] Contenteditable typing failed: %s", e)

        # Fallback: try textarea
        try:
            textareas = self.page.locator('textarea')
            for i in range(await textareas.count()):
                ta = textareas.nth(i)
                box = await ta.bounding_box()
                if box and box['width'] > 100 and box['height'] > 10:
                    await ta.click()
                    await self.page.keyboard.press("Meta+a")
                    await self.page.keyboard.type(prompt, delay=10)
                    logger.info("[Flow] Filled prompt via textarea typing")
                    return True
        except Exception as e:
            logger.warning("[Flow] Textarea typing failed: %s", e)

        logger.warning("[Flow] Could not find any prompt input element")
        return False

    async def _click_submit(self) -> bool:
        """Find and click the submit (arrow_forward) button in the prompt bar.

        Uses Playwright mouse.click at exact coordinates for reliability.
        Polls for up to 5 seconds for the button to become available.

        Returns True if the button was found and clicked.
        """
        for _ in range(10):
            btn_pos = await self.page.evaluate('''() => {
                const viewH = window.innerHeight;
                for (const btn of document.querySelectorAll('button')) {
                    const text = (btn.textContent || '').trim();
                    const rect = btn.getBoundingClientRect();
                    if (text.includes('arrow_forward')
                        && rect.top > viewH * 0.7
                        && rect.width > 0 && !btn.disabled) {
                        return {
                            x: Math.round(rect.x + rect.width / 2),
                            y: Math.round(rect.y + rect.height / 2),
                        };
                    }
                }
                return null;
            }''')
            if btn_pos:
                await self.page.mouse.click(btn_pos['x'], btn_pos['y'])
                logger.info("[Flow] Clicked submit (arrow_forward) button")
                return True
            await asyncio.sleep(0.5)

        logger.warning("[Flow] Could not find or click submit button")
        return False

    def _make_prompt_dir(self, prompt: str) -> Path:
        """Create an output subdirectory named after the prompt and timestamp."""
        safe = re.sub(r'[^\w\s-]', '', prompt)
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
            async with httpx.AsyncClient(
                timeout=timeout, follow_redirects=True,
            ) as http:
                resp = await http.get(url)
                resp.raise_for_status()
                local_path.write_bytes(resp.content)
                logger.info(
                    "[Flow] Downloaded file to %s (%d bytes)",
                    local_path, len(resp.content),
                )
                return local_path, filename
        except Exception as e:
            logger.error("[Flow] Failed to download file: %s", e)
            return None, None

    async def _download_with_cookies(
        self,
        url: str,
        output_dir: Path | None = None,
        extension: str = ".mp4",
        timeout: float = 120.0,
    ) -> tuple[Path | None, str | None]:
        """Download a file using the browser context's session cookies.

        Used for authenticated URLs like labs.google/fx/api/trpc/media
        redirect URLs that require login cookies to access.

        Returns (local_path, filename) or (None, None) on failure.
        """
        dest = output_dir or self.output_dir
        dest.mkdir(parents=True, exist_ok=True)
        filename = f"{uuid.uuid4().hex}{extension}"
        local_path = dest / filename

        try:
            # Extract cookies from browser context
            browser_cookies = await self.context.cookies()
            cookies = httpx.Cookies()
            for c in browser_cookies:
                cookies.set(c["name"], c["value"], domain=c.get("domain", ""))

            async with httpx.AsyncClient(
                timeout=timeout, follow_redirects=True, cookies=cookies,
            ) as http:
                resp = await http.get(url)
                resp.raise_for_status()
                local_path.write_bytes(resp.content)
                logger.info(
                    "[Flow] Downloaded file (authenticated) to %s (%d bytes)",
                    local_path, len(resp.content),
                )
                return local_path, filename
        except Exception as e:
            logger.error("[Flow] Failed authenticated download: %s", e)
            return None, None

    @staticmethod
    def _read_image_dimensions(path: Path) -> tuple[int | None, int | None]:
        """Read actual pixel dimensions from an image file header.

        Supports WebP, PNG, and JPEG formats.
        """
        try:
            data = path.read_bytes()
            # WebP
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
            # PNG
            if data[:8] == b'\x89PNG\r\n\x1a\n':
                w = int.from_bytes(data[16:20], 'big')
                h = int.from_bytes(data[20:24], 'big')
                return w, h
            # JPEG
            if data[:2] == b'\xff\xd8':
                i = 2
                while i < len(data) - 1:
                    if data[i] != 0xFF:
                        break
                    marker = data[i + 1]
                    if marker in (0xC0, 0xC1, 0xC2):
                        h = int.from_bytes(data[i + 5:i + 7], 'big')
                        w = int.from_bytes(data[i + 7:i + 9], 'big')
                        return w, h
                    length = int.from_bytes(data[i + 2:i + 4], 'big')
                    i += 2 + length
        except Exception:
            pass
        return None, None

    async def close(self) -> None:
        """Clean up resources. Page and context managed by BrowserManager."""
        pass


class FlowClient(FlowBaseClient, AbstractImageClient):
    """Google Flow image generation client via browser automation.

    Automates the Google Flow web UI to generate images from text prompts.
    """

    def __init__(
        self,
        page: Page,
        context: BrowserContext,
        output_dir: Path | None = None,
        model: FlowModel = FlowModel.NANO_BANANA_2,
        orientation: FlowOrientation = FlowOrientation.LANDSCAPE,
        count: FlowCount = FlowCount.X2,
    ):
        FlowBaseClient.__init__(self, page, context, output_dir)
        AbstractImageClient.__init__(self, page, context)
        self.model = model
        self.orientation = orientation
        self.count = count
        self._config_applied = False

    async def _setup_generation_config(self) -> None:
        """Configure model, orientation, and count via the config panel (one-time).

        The config panel is opened by clicking the main config button in the
        prompt bar (e.g. "Nano Banana 2 crop_16_9 x2"). Inside the panel:
        - Row 1: Image / Video tabs
        - Row 2: Landscape / Portrait tabs
        - Row 3: x1 / x2 / x3 / x4 tabs
        - Row 4: Model dropdown (e.g. "Nano Banana 2")
        """
        if self._config_applied:
            return

        await self._open_config_panel()
        # Ensure Image tab is selected
        result = await self._click_tab("Image")
        if result == 'clicked':
            logger.info("[FlowClient] Switched to Image tab")
        await self._select_orientation()
        await self._select_count()
        await self._select_model()
        # Close the config panel by clicking outside it
        await self.page.mouse.click(10, 10)
        await asyncio.sleep(0.5)

        # Verify by reading the config button text
        btn_text = await self.page.evaluate("""() => {
            for (const btn of document.querySelectorAll('button[aria-haspopup="menu"]')) {
                const rect = btn.getBoundingClientRect();
                if (rect.y > window.innerHeight * 0.7 && rect.width > 100) {
                    return (btn.textContent || '').trim();
                }
            }
            return null;
        }""")
        logger.info("[FlowClient] Config button now shows: %s", btn_text)

        self._config_applied = True
        logger.info(
            "[FlowClient] Config applied: model=%s, orientation=%s, count=%s",
            self.model.name, self.orientation.name, self.count.name,
        )

    async def _select_orientation(self) -> bool:
        """Select Landscape or Portrait tab in the open config panel."""
        target = ORIENTATION_UI_LABELS[self.orientation]
        result = await self._click_tab(target)

        if result == 'already':
            logger.info("[FlowClient] Orientation '%s' already selected", target)
        elif result == 'clicked':
            logger.info("[FlowClient] Selected orientation: %s", target)
        else:
            logger.warning("[FlowClient] Could not find orientation tab '%s'", target)
            return False
        return True

    async def _select_count(self) -> bool:
        """Select x1/x2/x3/x4 tab in the open config panel."""
        target = COUNT_UI_LABELS[self.count]
        # Count tabs use exact match (x1, x2, x3, x4) — find by exact text
        tab_info = await self.page.evaluate("""(target) => {
            for (const tab of document.querySelectorAll('[role="tab"]')) {
                const text = (tab.textContent || '').trim();
                if (text === target) {
                    const rect = tab.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0) {
                        return {
                            selected: tab.getAttribute('aria-selected') === 'true',
                            x: rect.x + rect.width / 2,
                            y: rect.y + rect.height / 2,
                        };
                    }
                }
            }
            return null;
        }""", target)

        if not tab_info:
            logger.warning("[FlowClient] Could not find count tab '%s'", target)
            return False
        if tab_info['selected']:
            logger.info("[FlowClient] Count '%s' already selected", target)
        else:
            await self.page.mouse.click(tab_info['x'], tab_info['y'])
            await asyncio.sleep(0.5)
            logger.info("[FlowClient] Selected count: %s", target)
        return True

    async def _select_model(self) -> bool:
        """Select image model from the dropdown inside the open config panel.

        The model dropdown is the button with 'arrow_drop_down' in the panel.
        """
        target_label = MODEL_UI_LABELS[self.model]

        # Find the model dropdown button inside the panel (has arrow_drop_down text)
        model_btn = await self.page.evaluate("""() => {
            for (const btn of document.querySelectorAll('button')) {
                const text = (btn.textContent || '').trim();
                const rect = btn.getBoundingClientRect();
                if (text.includes('arrow_drop_down') && rect.width > 100
                    && rect.y > 700 && rect.y < 900) {
                    return {
                        text: text,
                        x: rect.x + rect.width / 2,
                        y: rect.y + rect.height / 2,
                    };
                }
            }
            return null;
        }""")

        if not model_btn:
            logger.warning("[FlowClient] Could not find model dropdown button")
            return False

        # Check if already the right model
        if target_label in model_btn['text']:
            logger.info("[FlowClient] Model '%s' already selected", target_label)
            return True

        # Open the model dropdown
        await self.page.mouse.click(model_btn['x'], model_btn['y'])
        await asyncio.sleep(0.5)

        # Click the target model from the dropdown menu
        clicked = await self.page.evaluate("""(target) => {
            for (const item of document.querySelectorAll('[role="menuitem"]')) {
                const text = (item.textContent || '').trim();
                if (text.includes(target)) {
                    item.click();
                    return text;
                }
            }
            return null;
        }""", target_label)

        if clicked:
            logger.info("[FlowClient] Selected model: %s", clicked)
            await asyncio.sleep(0.3)
        else:
            logger.warning("[FlowClient] Model '%s' not found in dropdown", target_label)
            await self.page.keyboard.press("Escape")
            await asyncio.sleep(0.2)

        return clicked is not None

    def _setup_response_listener(self) -> tuple[list[str], object]:
        """Set up a network response listener to capture signed GCS image URLs.

        Captures URLs from two sources:
        1. The batchGenerateImages API response (JSON containing signed URLs)
        2. Individual storage.googleapis.com image responses

        Returns (captured_urls_list, listener_fn) — caller must remove listener.
        """
        captured: list[str] = []

        async def _extract_batch_urls(response):
            """Parse the batchGenerateImages API response for signed URLs."""
            try:
                body = await response.json()
                # Walk the response looking for signed GCS URLs
                def find_urls(obj):
                    if isinstance(obj, str):
                        if 'storage.googleapis.com' in obj and 'image' in obj:
                            captured.append(obj)
                    elif isinstance(obj, dict):
                        for v in obj.values():
                            find_urls(v)
                    elif isinstance(obj, list):
                        for item in obj:
                            find_urls(item)
                find_urls(body)
                logger.info(
                    "[FlowClient] Extracted %d GCS URLs from batch API response",
                    len(captured),
                )
            except Exception as e:
                logger.warning("[FlowClient] Failed to parse batch response: %s", e)

        def on_response(response):
            url = response.url
            # Capture individual GCS image responses
            if ('storage.googleapis.com' in url
                    and response.status == 200
                    and 'image' in response.headers.get('content-type', '')):
                if url not in captured:
                    captured.append(url)
                    logger.info("[FlowClient] Captured GCS image URL: %s", url[:120])
            # Capture batch generation API response
            elif ('batchGenerateImages' in url and response.status == 200):
                asyncio.ensure_future(_extract_batch_urls(response))

        self.page.on('response', on_response)
        return captured, on_response

    async def _collect_existing_images(self) -> set[str]:
        """Snapshot all image URLs currently in the DOM."""
        urls = await self.page.evaluate(_COLLECT_IMAGES_JS)
        return set(urls)

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
                    "[FlowClient] Stable at %d images after %ds, returning",
                    len(new_urls), i,
                )
                return new_urls

            if i > 0 and i % 15 == 0:
                logger.info(
                    "[FlowClient] Waiting for images... %d/%d (%ds/%ds)",
                    len(new_urls), expected_count, i, timeout_seconds,
                )

        current_urls = await self.page.evaluate(_COLLECT_IMAGES_JS)
        return [u for u in current_urls if u not in existing]

    async def download_image(
        self,
        url: str,
        output_dir: Path | None = None,
    ) -> tuple[Path | None, str | None]:
        """Download an image from a signed GCS URL.

        Returns (local_path, filename) or (None, None) on failure.
        """
        return await self.download_file(url, output_dir=output_dir, extension=".png")

    async def _download_via_canvas(
        self,
        img_src: str,
        output_dir: Path | None = None,
    ) -> tuple[Path | None, str | None]:
        """Fallback: extract image data by drawing to canvas in the browser.

        Used when direct download of the URL fails (e.g. redirect URLs).
        Returns (local_path, filename) or (None, None) on failure.
        """
        import base64

        dest = output_dir or self.output_dir
        dest.mkdir(parents=True, exist_ok=True)
        filename = f"{uuid.uuid4().hex}.png"
        local_path = dest / filename

        try:
            data_url = await self.page.evaluate('''(src) => {
                for (const img of document.querySelectorAll('img')) {
                    if (img.src === src && img.naturalWidth > 0) {
                        const canvas = document.createElement('canvas');
                        canvas.width = img.naturalWidth;
                        canvas.height = img.naturalHeight;
                        const ctx = canvas.getContext('2d');
                        ctx.drawImage(img, 0, 0);
                        return canvas.toDataURL('image/png');
                    }
                }
                return null;
            }''', img_src)

            if not data_url:
                logger.warning("[FlowClient] Canvas extraction: image not found in DOM")
                return None, None

            # Parse data URL: "data:image/png;base64,..."
            header, b64data = data_url.split(',', 1)
            img_bytes = base64.b64decode(b64data)
            local_path.write_bytes(img_bytes)
            logger.info(
                "[FlowClient] Extracted image via canvas to %s (%d bytes)",
                local_path, len(img_bytes),
            )
            return local_path, filename
        except Exception as e:
            logger.error("[FlowClient] Canvas extraction failed: %s", e)
            return None, None

    @retry(stop=stop_after_attempt(2), wait=wait_fixed(3))
    async def generate_images(
        self,
        prompt: str,
        count: int | None = None,
        timeout_seconds: int = 120,
    ) -> GenerationResult:
        """Generate images from a text prompt.

        Navigates to Flow, enters a project, fills the prompt via keyboard
        typing, clicks the submit arrow, waits for new images to appear
        in the DOM, then downloads them.

        Args:
            prompt: Text description of the image to generate.
            count: Expected number of images. If None, uses self.count
                   (set via FlowCount in constructor).
            timeout_seconds: Maximum wait time for image generation.
        """
        if count is None:
            count = self.count.value
        logger.info("[FlowClient] Generating %d images: %s", count, prompt[:80])
        start_time = time.monotonic()

        await self._ensure_generation_page()
        await self._setup_generation_config()
        existing_images = await self._collect_existing_images()

        filled = await self._fill_prompt(prompt)
        if not filled:
            return GenerationResult(
                platform=Platform.FLOW,
                prompt=prompt,
                status=GenerationStatus.FAILED,
                error="Could not find prompt input",
                duration_ms=int((time.monotonic() - start_time) * 1000),
            )
        await asyncio.sleep(0.5)

        # Start listening for signed GCS URLs BEFORE submit so we capture
        # the batchGenerateImages API response containing all signed URLs.
        gcs_urls, listener = self._setup_response_listener()

        clicked = await self._click_submit()
        if not clicked:
            try:
                self.page.remove_listener('response', listener)
            except Exception:
                pass
            return GenerationResult(
                platform=Platform.FLOW,
                prompt=prompt,
                status=GenerationStatus.FAILED,
                error="Could not find or click Create button",
                duration_ms=int((time.monotonic() - start_time) * 1000),
            )

        logger.info("[FlowClient] Prompt submitted, waiting for %d images...", count)

        all_new = await self._wait_for_new_images(
            existing_images,
            expected_count=count,
            timeout_seconds=timeout_seconds,
        )

        # Brief delay to let async batch URL extraction complete
        await asyncio.sleep(2)

        # Stop listening
        try:
            self.page.remove_listener('response', listener)
        except Exception:
            pass

        if not all_new:
            return GenerationResult(
                platform=Platform.FLOW,
                prompt=prompt,
                status=GenerationStatus.FAILED,
                error="No images generated (timeout)",
                duration_ms=int((time.monotonic() - start_time) * 1000),
            )

        logger.info(
            "[FlowClient] Got %d new image URLs, %d GCS URLs captured",
            len(all_new), len(gcs_urls),
        )

        prompt_dir = self._make_prompt_dir(prompt)

        images: list[GeneratedImage] = []
        for i, dom_url in enumerate(all_new):
            local_path = None
            filename = None

            # Strategy 1: download from captured signed GCS URL
            if i < len(gcs_urls):
                local_path, filename = await self.download_image(
                    gcs_urls[i], output_dir=prompt_dir,
                )

            # Strategy 2: extract via canvas (fallback)
            if local_path is None:
                logger.info("[FlowClient] Falling back to canvas extraction for image %d", i)
                local_path, filename = await self._download_via_canvas(
                    dom_url, output_dir=prompt_dir,
                )

            w, h = None, None
            if local_path:
                w, h = self._read_image_dimensions(local_path)
            images.append(GeneratedImage(
                url=gcs_urls[i] if i < len(gcs_urls) else dom_url,
                local_path=str(local_path) if local_path else None,
                filename=filename,
                width=w,
                height=h,
                is_highres=local_path is not None,
            ))

        duration_ms = int((time.monotonic() - start_time) * 1000)
        logger.info(
            "[FlowClient] Downloaded %d images in %dms",
            len(images), duration_ms,
        )

        return GenerationResult(
            platform=Platform.FLOW,
            prompt=prompt,
            images=images,
            status=GenerationStatus.COMPLETED,
            duration_ms=duration_ms,
            model=self.model.value,
        )


class FlowVideoClient(FlowBaseClient):
    """Google Flow video generation client via browser automation.

    Automates the Google Flow web UI to generate videos from text prompts.
    Flow:
    1. Navigate to the project editor
    2. Switch to Video mode via the config panel
    3. Select video model, orientation, and count
    4. Fill the prompt
    5. Click submit
    6. Wait for the video to appear (intercept network responses for GCS video URLs)
    7. Download the video
    """

    def __init__(
        self,
        page: Page,
        context: BrowserContext,
        output_dir: Path | None = None,
        model: FlowVideoModel = FlowVideoModel.VEO_3_1_FAST,
        orientation: FlowOrientation = FlowOrientation.LANDSCAPE,
        count: FlowCount = FlowCount.X2,
    ):
        super().__init__(page, context, output_dir)
        self.model = model
        self.orientation = orientation
        self.count = count
        self._config_applied = False

    async def _setup_video_config(self) -> None:
        """Configure video mode, model, orientation, and count via the config panel.

        Opens the config panel, clicks the Video tab, then sets orientation,
        count, and video model.
        """
        if self._config_applied:
            return

        await self._open_config_panel()

        # Switch to Video tab
        result = await self._click_tab("Video")
        if result == 'clicked':
            logger.info("[FlowVideoClient] Switched to Video tab")
            await asyncio.sleep(0.5)
        elif result is None:
            logger.warning("[FlowVideoClient] Could not find Video tab")

        # Select orientation (Landscape / Portrait)
        await self._select_orientation()

        # Select count (x1 / x2 / x3 / x4)
        await self._select_count()

        # Select video model from dropdown
        await self._select_video_model()

        # Close the config panel by clicking outside it
        await self.page.mouse.click(10, 10)
        await asyncio.sleep(0.5)

        # Verify by reading the config button text
        btn_text = await self.page.evaluate("""() => {
            for (const btn of document.querySelectorAll('button[aria-haspopup="menu"]')) {
                const rect = btn.getBoundingClientRect();
                if (rect.y > window.innerHeight * 0.7 && rect.width > 100) {
                    return (btn.textContent || '').trim();
                }
            }
            return null;
        }""")
        logger.info("[FlowVideoClient] Config button now shows: %s", btn_text)

        self._config_applied = True
        logger.info(
            "[FlowVideoClient] Config applied: model=%s, orientation=%s, count=%s",
            self.model.name, self.orientation.name, self.count.name,
        )

    async def _select_orientation(self) -> bool:
        """Select Landscape or Portrait tab in the open config panel."""
        target = ORIENTATION_UI_LABELS[self.orientation]
        result = await self._click_tab(target)

        if result == 'already':
            logger.info("[FlowVideoClient] Orientation '%s' already selected", target)
        elif result == 'clicked':
            logger.info("[FlowVideoClient] Selected orientation: %s", target)
        else:
            logger.warning("[FlowVideoClient] Could not find orientation tab '%s'", target)
            return False
        return True

    async def _select_count(self) -> bool:
        """Select x1/x2/x3/x4 tab in the open config panel."""
        target = COUNT_UI_LABELS[self.count]
        tab_info = await self.page.evaluate("""(target) => {
            for (const tab of document.querySelectorAll('[role="tab"]')) {
                const text = (tab.textContent || '').trim();
                if (text === target) {
                    const rect = tab.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0) {
                        return {
                            selected: tab.getAttribute('aria-selected') === 'true',
                            x: rect.x + rect.width / 2,
                            y: rect.y + rect.height / 2,
                        };
                    }
                }
            }
            return null;
        }""", target)

        if not tab_info:
            logger.warning("[FlowVideoClient] Could not find count tab '%s'", target)
            return False
        if tab_info['selected']:
            logger.info("[FlowVideoClient] Count '%s' already selected", target)
        else:
            await self.page.mouse.click(tab_info['x'], tab_info['y'])
            await asyncio.sleep(0.5)
            logger.info("[FlowVideoClient] Selected count: %s", target)
        return True

    async def _select_video_model(self) -> bool:
        """Select video model from the dropdown inside the open config panel.

        The model dropdown is the button with 'arrow_drop_down' in the panel.
        """
        target_label = VIDEO_MODEL_UI_LABELS[self.model]

        # Find the model dropdown button inside the panel (has arrow_drop_down text)
        model_btn = await self.page.evaluate("""() => {
            for (const btn of document.querySelectorAll('button')) {
                const text = (btn.textContent || '').trim();
                const rect = btn.getBoundingClientRect();
                if (text.includes('arrow_drop_down') && rect.width > 100
                    && rect.y > 700 && rect.y < 900) {
                    return {
                        text: text,
                        x: rect.x + rect.width / 2,
                        y: rect.y + rect.height / 2,
                    };
                }
            }
            return null;
        }""")

        if not model_btn:
            logger.warning("[FlowVideoClient] Could not find model dropdown button")
            return False

        # Check if already the right model
        if target_label in model_btn['text']:
            logger.info("[FlowVideoClient] Model '%s' already selected", target_label)
            return True

        # Open the model dropdown
        await self.page.mouse.click(model_btn['x'], model_btn['y'])
        await asyncio.sleep(0.5)

        # Click the target model from the dropdown menu
        clicked = await self.page.evaluate("""(target) => {
            for (const item of document.querySelectorAll('[role="menuitem"]')) {
                const text = (item.textContent || '').trim();
                if (text.includes(target)) {
                    item.click();
                    return text;
                }
            }
            return null;
        }""", target_label)

        if clicked:
            logger.info("[FlowVideoClient] Selected model: %s", clicked)
            await asyncio.sleep(0.3)
        else:
            logger.warning("[FlowVideoClient] Model '%s' not found in dropdown", target_label)
            await self.page.keyboard.press("Escape")
            await asyncio.sleep(0.2)

        return clicked is not None

    def _setup_video_listener(self) -> tuple[list[str], object]:
        """Set up a network response listener to capture signed GCS video URLs.

        Captures URLs from two sources:
        1. storage.googleapis.com responses with video content-type
        2. Batch API responses containing signed video download URLs

        Returns (captured_urls_list, listener_fn) — caller must remove listener.
        """
        captured: list[str] = []

        async def _extract_batch_urls(response):
            """Parse batch API response for signed video URLs."""
            try:
                body = await response.json()
                def find_urls(obj):
                    if isinstance(obj, str):
                        if ('storage.googleapis.com' in obj
                                and ('video' in obj or '.mp4' in obj)):
                            if obj not in captured:
                                captured.append(obj)
                    elif isinstance(obj, dict):
                        for v in obj.values():
                            find_urls(v)
                    elif isinstance(obj, list):
                        for item in obj:
                            find_urls(item)
                find_urls(body)
                if captured:
                    logger.info(
                        "[FlowVideoClient] Extracted %d video URLs from API response",
                        len(captured),
                    )
            except Exception as e:
                logger.warning("[FlowVideoClient] Failed to parse batch response: %s", e)

        def on_response(response):
            url = response.url
            ct = response.headers.get('content-type', '')
            # Capture individual GCS video responses
            if ('storage.googleapis.com' in url
                    and response.status == 200
                    and ('video' in ct or '.mp4' in url)):
                if url not in captured:
                    captured.append(url)
                    logger.info("[FlowVideoClient] Captured GCS video URL: %s", url[:120])
            # Capture batch generation API responses (may contain video URLs)
            elif (response.status == 200
                  and ('generateVideos' in url or 'batchGenerate' in url)):
                asyncio.ensure_future(_extract_batch_urls(response))

        self.page.on('response', on_response)
        return captured, on_response

    async def _collect_existing_videos(self) -> set[str]:
        """Snapshot all video URLs currently in the DOM (before submitting)."""
        urls = await self.page.evaluate("""() => {
            const urls = [];
            for (const v of document.querySelectorAll('video')) {
                const src = v.src || v.getAttribute('src') || '';
                if (src && src.length > 50) urls.push(src);
                for (const s of v.querySelectorAll('source')) {
                    const ssrc = s.src || s.getAttribute('src') || '';
                    if (ssrc && ssrc.length > 50) urls.push(ssrc);
                }
            }
            return urls;
        }""")
        logger.info("[FlowVideoClient] Existing videos in DOM: %d", len(urls))
        return set(urls)

    async def _wait_for_video(
        self,
        captured_urls: list[str],
        existing_videos: set[str],
        timeout_seconds: int = 300,
    ) -> list[str]:
        """Wait for videos to appear via network capture or DOM.

        Args:
            captured_urls: Mutable list populated by the response listener.
            existing_videos: URLs already present before submission (to exclude).
            timeout_seconds: Maximum wait time (default 300s for video generation).

        Returns list of NEW video URLs found.
        """
        expected_count = self.count.value

        for i in range(timeout_seconds):
            # Check captured URLs from network listener (always new, post-listener)
            if len(captured_urls) >= expected_count:
                logger.info(
                    "[FlowVideoClient] Got %d video URLs from network capture",
                    len(captured_urls),
                )
                return captured_urls[:expected_count]

            await asyncio.sleep(1)

            # Periodically check DOM for <video> elements as fallback
            if i > 15 and i % 10 == 0:
                video_srcs = await self.page.evaluate("""() => {
                    const urls = [];
                    for (const v of document.querySelectorAll('video')) {
                        const src = v.src || v.getAttribute('src') || '';
                        if (src && src.length > 50
                            && !src.includes('loading')
                            && !src.includes('animation')
                            && !src.includes('static')) {
                            urls.push(src);
                        }
                        // Check <source> children
                        for (const s of v.querySelectorAll('source')) {
                            const ssrc = s.src || s.getAttribute('src') || '';
                            if (ssrc && ssrc.length > 50
                                && !ssrc.includes('loading')
                                && !ssrc.includes('animation')) {
                                urls.push(ssrc);
                            }
                        }
                    }
                    return urls;
                }""")
                if video_srcs:
                    for src in video_srcs:
                        # Only add genuinely NEW videos (not in existing set or already captured)
                        if src not in existing_videos and src not in captured_urls:
                            captured_urls.append(src)
                            logger.info("[FlowVideoClient] Found NEW video in DOM: %s", src[:120])
                    if len(captured_urls) >= expected_count:
                        return captured_urls[:expected_count]

            if i > 0 and i % 30 == 0:
                logger.info(
                    "[FlowVideoClient] Waiting for video... %d/%d captured (%ds/%ds)",
                    len(captured_urls), expected_count, i, timeout_seconds,
                )

        # Return whatever we have at timeout
        return captured_urls

    async def download_video(
        self,
        url: str,
        output_dir: Path | None = None,
    ) -> tuple[Path | None, str | None]:
        """Download a video file. Returns (local_path, filename) or (None, None).

        Tries authenticated download first (needed for labs.google redirect URLs),
        then falls back to plain download (for direct GCS signed URLs).
        """
        # Authenticated URLs (labs.google/fx/api/trpc/media redirect)
        if 'labs.google' in url or 'getMediaUrlRedirect' in url:
            result = await self._download_with_cookies(
                url, output_dir=output_dir, extension=".mp4", timeout=120.0,
            )
            if result[0] is not None:
                return result
            logger.warning("[FlowVideoClient] Authenticated download failed, trying plain...")

        return await self.download_file(url, output_dir=output_dir, extension=".mp4", timeout=120.0)

    @retry(stop=stop_after_attempt(2), wait=wait_fixed(3))
    async def generate_video(
        self,
        prompt: str,
        timeout_seconds: int = 300,
    ) -> VideoGenerationResult:
        """Generate videos from a text prompt via browser automation.

        1. Navigate to the project editor
        2. Configure video mode and settings
        3. Fill prompt and click submit
        4. Wait for video to appear (network interception + DOM polling)
        5. Download the video(s)

        Args:
            prompt: Text description of the video to generate.
            timeout_seconds: Maximum wait time (default 300s).
        """
        logger.info("[FlowVideoClient] Generating video: %s", prompt[:80])
        start_time = time.monotonic()

        await self._ensure_generation_page()
        await self._setup_video_config()

        # Snapshot existing videos in DOM so we only detect NEW ones
        existing_videos = await self._collect_existing_videos()

        filled = await self._fill_prompt(prompt)
        if not filled:
            return VideoGenerationResult(
                platform=Platform.FLOW,
                prompt=prompt,
                status=GenerationStatus.FAILED,
                error="Could not find prompt input",
                duration_ms=int((time.monotonic() - start_time) * 1000),
            )
        await asyncio.sleep(0.5)

        # Start listening for video URLs BEFORE submit
        captured_urls, listener = self._setup_video_listener()

        clicked = await self._click_submit()
        if not clicked:
            try:
                self.page.remove_listener('response', listener)
            except Exception:
                pass
            return VideoGenerationResult(
                platform=Platform.FLOW,
                prompt=prompt,
                status=GenerationStatus.FAILED,
                error="Could not find or click submit button",
                duration_ms=int((time.monotonic() - start_time) * 1000),
            )

        logger.info("[FlowVideoClient] Prompt submitted, waiting for video...")

        video_urls = await self._wait_for_video(
            captured_urls,
            existing_videos=existing_videos,
            timeout_seconds=timeout_seconds,
        )

        # Brief delay for any async URL extraction
        await asyncio.sleep(2)

        # Stop listening
        try:
            self.page.remove_listener('response', listener)
        except Exception:
            pass

        if not video_urls:
            return VideoGenerationResult(
                platform=Platform.FLOW,
                prompt=prompt,
                status=GenerationStatus.FAILED,
                error="No video generated (timeout)",
                duration_ms=int((time.monotonic() - start_time) * 1000),
            )

        # Download the first video
        video_url = video_urls[0]
        logger.info("[FlowVideoClient] Downloading video: %s", video_url[:120])
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
            "[FlowVideoClient] Video complete in %dms (%s bytes)",
            duration_ms, size_bytes or "?",
        )

        return VideoGenerationResult(
            platform=Platform.FLOW,
            prompt=prompt,
            video=video,
            status=GenerationStatus.COMPLETED,
            duration_ms=duration_ms,
            model=self.model.value,
        )
