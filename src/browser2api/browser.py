"""Browser manager for browser-to-API automation with Playwright and Chrome CDP."""

import asyncio
import logging
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

# Playwright is optional - only required for actual crawling
try:
    from playwright.async_api import (
        Browser,
        BrowserContext,
        Page,
        Playwright,
        async_playwright,
    )
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    # Stub types for when playwright isn't installed
    Browser = Any  # type: ignore
    BrowserContext = Any  # type: ignore
    Page = Any  # type: ignore
    Playwright = Any  # type: ignore

from .types import Platform

logger = logging.getLogger(__name__)

# Path to stealth.min.js for anti-detection
STEALTH_JS_PATH = Path(__file__).parent / "stealth.min.js"

# Default CDP port
DEFAULT_CDP_PORT = 9224


def find_chrome_path() -> str | None:
    """
    Find the installed Chrome or Edge browser path.

    Returns:
        Path to Chrome/Edge executable, or None if not found
    """
    system = platform.system()

    if system == "Darwin":  # macOS
        paths = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
    elif system == "Windows":
        paths = [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        ]
    else:  # Linux
        paths = [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/snap/bin/chromium",
            "/usr/bin/microsoft-edge",
        ]
        # Also check which
        for cmd in ["google-chrome", "chromium", "chromium-browser", "microsoft-edge"]:
            result = shutil.which(cmd)
            if result:
                return result

    for path in paths:
        if os.path.exists(path):
            return path

    return None


async def get_cdp_ws_url(port: int = DEFAULT_CDP_PORT) -> str | None:
    """
    Get the WebSocket URL for CDP connection.

    Args:
        port: The remote debugging port

    Returns:
        WebSocket URL for CDP connection, or None if not available
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"http://127.0.0.1:{port}/json/version",
                timeout=5.0,
            )
            if response.status_code == 200:
                data = response.json()
                return data.get("webSocketDebuggerUrl")
    except Exception as e:
        logger.debug("Could not get CDP WebSocket URL: %s", e)
    return None


def find_chrome_process_for_user_data_dir(user_data_dir: Path) -> tuple[int, int] | None:
    """
    Find an existing Chrome process using the specified user data directory.

    Returns:
        Tuple of (pid, cdp_port) if found, None otherwise
    """
    import re

    try:
        # Use pgrep to find Chrome processes
        result = subprocess.run(
            ["pgrep", "-fl", "Chrome"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None

        # Look for our user data dir in the process list
        user_data_str = str(user_data_dir)
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            # Only match the MAIN Chrome process, not helpers
            # Main process has "Google Chrome" at the end of the path
            # Helper processes have "Google Chrome Helper" in their path
            if "Helper" in line:
                continue
            if user_data_str in line:
                # Extract PID (first number in line)
                pid_match = re.match(r"(\d+)", line)
                # Extract port from --remote-debugging-port=XXXX
                port_match = re.search(r"--remote-debugging-port=(\d+)", line)
                if pid_match and port_match:
                    pid = int(pid_match.group(1))
                    port = int(port_match.group(1))
                    logger.info(
                        "Found existing Chrome process (PID %d) using user data dir %s on port %d",
                        pid, user_data_dir, port
                    )
                    return (pid, port)
    except Exception as e:
        logger.debug("Error finding Chrome process: %s", e)

    return None


class ChromeLauncher:
    """Launches and manages a real Chrome browser with CDP."""

    def __init__(
        self,
        user_data_dir: Path,
        port: int = DEFAULT_CDP_PORT,
        headless: bool = False,
        minimal_flags: bool = False,
    ):
        self.user_data_dir = user_data_dir
        self.port = port
        self.headless = headless
        self.minimal_flags = minimal_flags
        self._process: subprocess.Popen | None = None

    def _get_launch_args(self) -> list[str]:
        """Get Chrome launch arguments.

        When minimal_flags=True, only essential CDP + UX flags are used.
        This avoids triggering Google's sign-in security checks that block
        browsers launched with automation-related flags.
        """
        args = [
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={self.user_data_dir}",
            "--no-first-run",
            "--no-default-browser-check",
        ]

        if not self.minimal_flags:
            args.extend([
                # Stability flags
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
                "--disable-features=TranslateUI",
                "--disable-ipc-flooding-protection",
                "--disable-hang-monitor",
                "--disable-prompt-on-repost",
                "--disable-sync",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                # Anti-detection flags
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
            ])

        if self.headless:
            args.extend([
                "--headless=new",
                "--disable-gpu",
            ])
        else:
            args.append("--start-maximized")

        return args

    def _wait_for_port(self, timeout: int = 30) -> bool:
        """Wait for CDP port to be ready using socket connection."""
        import socket
        import time

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(1)
                    result = s.connect_ex(('localhost', self.port))
                    if result == 0:
                        return True
            except Exception:
                pass
            time.sleep(0.5)
        return False

    async def launch(self) -> bool:
        """
        Launch Chrome browser with CDP.

        Returns:
            True if Chrome was launched successfully
        """
        chrome_path = find_chrome_path()
        if not chrome_path:
            logger.error("Chrome not found. Please install Google Chrome or Microsoft Edge.")
            return False

        logger.info("Launching Chrome from: %s", chrome_path)

        # Ensure user data dir exists
        self.user_data_dir.mkdir(parents=True, exist_ok=True)

        args = [chrome_path] + self._get_launch_args()
        logger.info("Chrome args: %s", " ".join(args))

        try:
            # Launch Chrome as subprocess
            # Use DEVNULL to avoid blocking on output buffers
            if sys.platform == "win32":
                self._process = subprocess.Popen(
                    args,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                )
            else:
                self._process = subprocess.Popen(
                    args,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    preexec_fn=os.setsid,  # Create new process group
                )

            # Wait for CDP port to be ready
            logger.info("Waiting for Chrome CDP to be ready on port %d...", self.port)
            if not self._wait_for_port(timeout=30):
                logger.error("Chrome CDP did not become ready within timeout")
                return False

            # Extra wait for CDP service to fully initialize
            await asyncio.sleep(1)

            # Verify we can get the WebSocket URL
            ws_url = await get_cdp_ws_url(self.port)
            if ws_url:
                logger.info("Chrome CDP ready at port %d", self.port)
                return True

            logger.error("Could not get Chrome CDP WebSocket URL")
            return False

        except Exception as e:
            logger.error("Failed to launch Chrome: %s", e)
            import traceback
            traceback.print_exc()
            return False

    def close(self) -> None:
        """Close the Chrome process."""
        if not self._process:
            return

        if self._process.poll() is not None:
            # Already exited
            self._process = None
            return

        logger.info("Closing Chrome process...")
        try:
            if sys.platform == "win32":
                self._process.terminate()
                try:
                    self._process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait(timeout=5)
            else:
                # Kill the entire process group
                import signal
                pgid = os.getpgid(self._process.pid)
                try:
                    os.killpg(pgid, signal.SIGTERM)
                    self._process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(pgid, signal.SIGKILL)
                    self._process.wait(timeout=5)
                except ProcessLookupError:
                    pass  # Already exited
        except Exception as e:
            logger.warning("Error closing Chrome: %s", e)
        finally:
            self._process = None


class BrowserManager:
    """
    Manages browser instances for browser-to-API automation.

    Supports two modes:
    1. CDP mode (default): Uses real Chrome browser via Chrome DevTools Protocol
       - Better anti-detection (uses real Chrome, not Playwright's Chromium)
       - Requires Chrome/Edge to be installed
    2. Playwright mode: Uses Playwright's bundled Chromium
       - No external dependencies
       - May be blocked by some sites

    Uses persistent user data directories to preserve full browser state
    (cookies, localStorage, IndexedDB, session storage) across sessions.
    """

    def __init__(
        self,
        data_dir: Path | None = None,
        proxy_url: str | None = None,
        use_cdp: bool = True,
        cdp_port: int = DEFAULT_CDP_PORT,
    ):
        """
        Initialize the browser manager.

        Args:
            data_dir: Base directory for browser data (user data dirs)
            proxy_url: Optional proxy URL for all requests
            use_cdp: If True, use Chrome CDP mode (default). If False, use Playwright Chromium.
            cdp_port: Port for Chrome DevTools Protocol
        """
        if data_dir is None:
            from .config import DATA_DIR
            data_dir = DATA_DIR / "browser_data"
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Keep cookies_dir for backwards compatibility
        self.cookies_dir = data_dir / "cookies"
        self.cookies_dir.mkdir(parents=True, exist_ok=True)

        self.proxy_url = proxy_url
        self.use_cdp = use_cdp
        self.cdp_port = cdp_port

        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._chrome_launcher: ChromeLauncher | None = None
        self._contexts: dict[str, BrowserContext] = {}  # key: platform name
        self._lock = asyncio.Lock()

    async def _ensure_playwright(self) -> Playwright:
        """Ensure Playwright is initialized."""
        if not PLAYWRIGHT_AVAILABLE:
            raise ImportError(
                "Playwright is required for social crawling. "
                "Install with: pip install playwright && playwright install chromium"
            )
        if self._playwright is None:
            self._playwright = await async_playwright().start()
        return self._playwright

    def _get_browser_args(self) -> list[str]:
        """Get browser launch arguments."""
        return [
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            "--disable-dev-shm-usage",
            "--no-sandbox",
        ]

    def _get_user_data_dir(self, platform: Platform) -> Path:
        """Get the user data directory for a platform."""
        if self.use_cdp:
            # CDP mode uses a separate directory to avoid conflicts with Playwright
            return self.data_dir / f"{platform.value}_cdp"
        return self.data_dir / platform.value

    def _get_context_options(self, platform: Platform) -> dict[str, Any]:
        """Get browser context options for a platform."""
        options: dict[str, Any] = {
            "viewport": {"width": 1920, "height": 1080},
            "user_agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "locale": "en-US",
            "timezone_id": "America/Los_Angeles",
        }

        if self.proxy_url:
            options["proxy"] = {"server": self.proxy_url}

        # Platform-specific settings
        if platform == Platform.JIMENG:
            options["locale"] = "zh-CN"
            options["timezone_id"] = "Asia/Shanghai"

        return options

    def _is_port_available(self, port: int) -> bool:
        """Check if a local TCP port is available."""
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return True
            except OSError:
                return False

    def _select_cdp_port(self) -> int:
        """Select an available CDP port, starting from the configured port."""
        if self._is_port_available(self.cdp_port):
            return self.cdp_port

        start_port = self.cdp_port + 1
        max_port = min(start_port + 100, 65535)
        for port in range(start_port, max_port + 1):
            if self._is_port_available(port):
                logger.warning(
                    "CDP port %d is in use, switching to available port %d",
                    self.cdp_port,
                    port,
                )
                return port

        raise RuntimeError(
            f"No available CDP port found from {start_port} to {max_port}"
        )

    async def _apply_stealth(self, page: Page) -> None:
        """Apply stealth techniques to avoid detection."""
        # Inject stealth.js if available
        if STEALTH_JS_PATH.exists():
            stealth_js = STEALTH_JS_PATH.read_text()
            await page.add_init_script(stealth_js)

        # Basic stealth measures
        await page.add_init_script("""
            // Override webdriver property
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });

            // Override plugins
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });

            // Override languages
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en']
            });

            // Override chrome property
            window.chrome = {
                runtime: {}
            };
        """)

    async def launch_for_login(
        self, platform: Platform
    ) -> tuple[BrowserContext, Page]:
        """
        Launch a HEADED browser with persistent user data for login.

        Uses Chrome CDP mode by default for better anti-detection.
        Falls back to Playwright Chromium if Chrome is not available.

        Args:
            platform: Target platform

        Returns:
            Tuple of (BrowserContext, Page)
        """
        pw = await self._ensure_playwright()
        user_data_dir = self._get_user_data_dir(platform)
        user_data_dir.mkdir(parents=True, exist_ok=True)

        context_options = self._get_context_options(platform)

        if self.use_cdp:
            # CDP mode: Launch real Chrome with minimal flags for login.
            # Minimal flags avoids triggering Google/other sign-in security
            # checks that block browsers with automation-related flags.
            context, page = await self._launch_cdp(
                user_data_dir=user_data_dir,
                context_options=context_options,
                headless=False,
                minimal_flags=True,
            )
        else:
            # Playwright mode: Use bundled Chromium
            context_options["args"] = self._get_browser_args()
            context = await pw.chromium.launch_persistent_context(
                user_data_dir=str(user_data_dir),
                headless=False,
                **context_options,
            )

            # Get the first page or create one
            if context.pages:
                page = context.pages[0]
            else:
                page = await context.new_page()

            await self._apply_stealth(page)

        # Store reference for cleanup
        self._contexts[platform.value] = context

        return context, page

    async def launch_for_crawl(
        self, platform: Platform
    ) -> tuple[BrowserContext, Page]:
        """
        Launch a HEADLESS browser with persistent user data for crawling.

        Uses Chrome CDP mode by default for better anti-detection.
        Falls back to Playwright Chromium if Chrome is not available.

        Args:
            platform: Target platform

        Returns:
            Tuple of (BrowserContext, Page)

        Raises:
            ValueError: If no user data exists for the platform
        """
        user_data_dir = self._get_user_data_dir(platform)
        if not user_data_dir.exists():
            raise ValueError(
                f"No saved browser data for {platform.value}. "
                "User must login first via headed browser."
            )

        pw = await self._ensure_playwright()
        context_options = self._get_context_options(platform)

        if self.use_cdp:
            # CDP mode: Launch real Chrome and connect via CDP
            context, page = await self._launch_cdp(
                user_data_dir=user_data_dir,
                context_options=context_options,
                headless=True,
            )
        else:
            # Playwright mode: Use bundled Chromium
            context_options["args"] = self._get_browser_args()
            context = await pw.chromium.launch_persistent_context(
                user_data_dir=str(user_data_dir),
                headless=True,
                **context_options,
            )

            # Get the first page or create one
            if context.pages:
                page = context.pages[0]
            else:
                page = await context.new_page()

            await self._apply_stealth(page)

        # Store reference for cleanup
        self._contexts[platform.value] = context

        return context, page

    async def _launch_cdp(
        self,
        user_data_dir: Path,
        context_options: dict[str, Any],
        headless: bool = False,
        minimal_flags: bool = False,
    ) -> tuple[BrowserContext, Page]:
        """
        Launch Chrome via CDP and connect with Playwright.

        Args:
            user_data_dir: User data directory for browser state
            context_options: Context options (viewport, user_agent, etc.)
            headless: Whether to run headless
            minimal_flags: If True, launch Chrome with minimal flags to avoid
                triggering sign-in security checks (e.g. Google)

        Returns:
            Tuple of (BrowserContext, Page)
        """
        pw = await self._ensure_playwright()

        # Check if Chrome is already running with this user data dir
        existing = find_chrome_process_for_user_data_dir(user_data_dir)
        if existing:
            pid, existing_port = existing
            logger.info("Found existing Chrome process (PID %d) on port %d", pid, existing_port)

            # Try to connect to the existing Chrome instance
            ws_url = await get_cdp_ws_url(existing_port)
            if ws_url:
                logger.info("Reusing existing Chrome connection on port %d", existing_port)
                self.cdp_port = existing_port
                try:
                    return await self._connect_to_cdp(
                        pw, ws_url, context_options,
                        apply_stealth=not minimal_flags,
                    )
                except Exception as e:
                    logger.warning("Failed to connect to existing Chrome: %s", e)
                    # Kill the stale process and launch fresh
                    logger.info("Killing stale Chrome process (PID %d)", pid)
                    try:
                        os.kill(pid, 9)
                        await asyncio.sleep(1)  # Wait for process to die
                    except Exception:
                        pass
            else:
                # Chrome running but CDP not responding - kill it
                logger.warning("Existing Chrome not responding on CDP, killing process")
                try:
                    os.kill(pid, 9)
                    await asyncio.sleep(1)
                except Exception:
                    pass

        # Ensure we connect to a port owned by the Chrome instance we launch.
        selected_port = self._select_cdp_port()
        self.cdp_port = selected_port

        # Launch Chrome with CDP
        self._chrome_launcher = ChromeLauncher(
            user_data_dir=user_data_dir,
            port=selected_port,
            headless=headless,
            minimal_flags=minimal_flags,
        )

        if not await self._chrome_launcher.launch():
            # Fall back to Playwright Chromium with SAME user data dir
            # Note: Playwright Chromium can use Chrome's user data format
            logger.warning("Chrome CDP failed, falling back to Playwright Chromium")
            context_options["args"] = self._get_browser_args()
            context = await pw.chromium.launch_persistent_context(
                user_data_dir=str(user_data_dir),
                headless=headless,
                **context_options,
            )
            if context.pages:
                page = context.pages[0]
            else:
                page = await context.new_page()
            if not minimal_flags:
                await self._apply_stealth(page)
            return context, page

        # Connect to Chrome via CDP
        ws_url = await get_cdp_ws_url(self.cdp_port)
        if not ws_url:
            raise RuntimeError("Failed to get Chrome CDP WebSocket URL")

        return await self._connect_to_cdp(
            pw, ws_url, context_options,
            apply_stealth=not minimal_flags,
        )

    async def _connect_to_cdp(
        self,
        pw: Playwright,
        ws_url: str,
        context_options: dict[str, Any],
        apply_stealth: bool = True,
    ) -> tuple[BrowserContext, Page]:
        """
        Connect to Chrome via CDP WebSocket URL.

        Args:
            pw: Playwright instance
            ws_url: CDP WebSocket URL
            context_options: Context options (viewport, user_agent, etc.)
            apply_stealth: Whether to inject stealth scripts (skip for login
                to avoid triggering Google's sign-in security checks)

        Returns:
            Tuple of (BrowserContext, Page)
        """
        logger.info("Connecting to Chrome via CDP: %s", ws_url)
        self._browser = await pw.chromium.connect_over_cdp(ws_url)

        if not self._browser.is_connected():
            raise RuntimeError("Failed to connect to Chrome via CDP")

        # Brief wait for page discovery to complete
        await asyncio.sleep(0.3)

        logger.info("Connected to Chrome. Contexts: %d", len(self._browser.contexts))

        # Get the default context (CDP uses the browser's existing context)
        contexts = self._browser.contexts
        if contexts:
            context = contexts[0]
            logger.info("Using existing context with %d pages", len(context.pages))
        else:
            # Create a new context with our options
            context = await self._browser.new_context(**context_options)
            logger.info("Created new context")

        # CRITICAL: Create a NEW page for reliable control
        # CDP-discovered pre-existing pages may not be fully controllable by Playwright
        # See: https://playwright.dev/python/docs/api/class-browsertype#browser-type-connect-over-cdp
        page = await context.new_page()
        logger.info("Created new controllable page")

        if apply_stealth:
            await self._apply_stealth(page)

        # Close the original blank tab to avoid user confusion
        # (the user will see our new page, not the original blank one)
        for p in context.pages:
            if p != page and p.url in ("about:blank", "chrome://newtab/", ""):
                try:
                    await p.close()
                    logger.info("Closed original blank tab")
                except Exception:
                    pass  # Ignore if already closed

        return context, page

    async def save_cookies(
        self, context: BrowserContext, platform: Platform
    ) -> None:
        """
        Save browser cookies for a platform.

        Note: With persistent context, cookies are auto-saved.
        This method is kept for compatibility.

        Args:
            context: Browser context with authenticated session
            platform: Target platform
        """
        # With persistent context, data is auto-saved
        # Just log that we're done
        logger.info("Browser data saved for %s at %s",
                   platform.value, self._get_user_data_dir(platform))

    def get_cookies_path(self, platform: Platform) -> Path:
        """Get the user data directory path for a platform."""
        return self._get_user_data_dir(platform)

    def has_cookies(self, platform: Platform) -> bool:
        """Check if browser data exists for a platform."""
        user_data_dir = self._get_user_data_dir(platform)
        # Check if the user data dir exists and has content
        if not user_data_dir.exists():
            return False
        # Check for key files that indicate a valid session
        # Chromium stores cookies in Default/Cookies or similar
        return (user_data_dir / "Default").exists() or any(user_data_dir.iterdir())

    def clear_cookies(self, platform: Platform) -> bool:
        """
        Clear saved browser data for a platform.

        Also kills any running Chrome processes using the user data directory.

        Returns:
            True if data was deleted
        """
        import shutil
        user_data_dir = self._get_user_data_dir(platform)

        # Kill any Chrome processes using this user data dir
        existing = find_chrome_process_for_user_data_dir(user_data_dir)
        if existing:
            pid, _ = existing
            logger.info("Killing Chrome process (PID %d) for %s", pid, platform.value)
            try:
                os.kill(pid, 9)
            except Exception as e:
                logger.warning("Failed to kill Chrome process: %s", e)

        if user_data_dir.exists():
            shutil.rmtree(user_data_dir)
            logger.info("Cleared browser data for %s", platform.value)
            return True
        return False

    async def close(self) -> None:
        """Close all browser contexts and clean up."""
        for platform, context in self._contexts.items():
            try:
                await context.close()
                logger.info("Closed browser context for %s", platform)
            except Exception as e:
                logger.warning("Error closing context for %s: %s", platform, e)
        self._contexts.clear()

        # Close CDP browser connection
        if self._browser:
            try:
                await self._browser.close()
            except Exception as e:
                logger.warning("Error closing CDP browser: %s", e)
            self._browser = None

        # Close Chrome launcher
        if self._chrome_launcher:
            self._chrome_launcher.close()
            self._chrome_launcher = None

        if self._playwright:
            await self._playwright.stop()
            self._playwright = None


# Singleton instance
_browser_manager: BrowserManager | None = None


def get_browser_manager(
    data_dir: Path | None = None,
    cookies_dir: Path | None = None,  # Deprecated, use data_dir
    proxy_url: str | None = None,
    use_cdp: bool = True,
    cdp_port: int = DEFAULT_CDP_PORT,
) -> BrowserManager:
    """
    Get the singleton browser manager instance.

    Args:
        data_dir: Base directory for browser data
        cookies_dir: Deprecated, use data_dir
        proxy_url: Optional proxy URL for all requests
        use_cdp: If True, use Chrome CDP mode (default). If False, use Playwright Chromium.
        cdp_port: Port for Chrome DevTools Protocol
    """
    global _browser_manager
    if _browser_manager is None:
        # cookies_dir is deprecated, prefer data_dir
        _browser_manager = BrowserManager(
            data_dir=data_dir or cookies_dir,
            proxy_url=proxy_url,
            use_cdp=use_cdp,
            cdp_port=cdp_port,
        )
    return _browser_manager
