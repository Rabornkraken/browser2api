"""Abstract base classes for browser-to-API image generation."""

import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

# Playwright is optional - only required for actual browser automation
try:
    from playwright.async_api import BrowserContext, Page
except ImportError:
    BrowserContext = Any  # type: ignore
    Page = Any  # type: ignore

from .config import DATA_DIR
from .types import GeneratedImage, GenerationResult, GenerationStatus, Platform

logger = logging.getLogger(__name__)


class AbstractImageClient(ABC):
    """Abstract base class for browser-automated image generation clients."""

    platform: Platform

    def __init__(self, page: Page, context: BrowserContext):
        self.page = page
        self.context = context

    @abstractmethod
    async def generate_images(
        self,
        prompt: str,
        count: int = 4,
        timeout_seconds: int = 120,
    ) -> GenerationResult:
        """
        Generate images from a text prompt.

        Args:
            prompt: Text prompt for image generation
            count: Number of images to generate
            timeout_seconds: Maximum time to wait for generation

        Returns:
            GenerationResult with generated images
        """
        ...

    async def generate_image(self, prompt: str) -> GeneratedImage | None:
        """Convenience method: generate a single image."""
        result = await self.generate_images(prompt, count=1)
        if result.images:
            return result.images[0]
        return None

    @abstractmethod
    async def close(self) -> None:
        """Clean up resources."""
        ...


class AbstractLoginHandler(ABC):
    """Abstract base class for platform login handlers."""

    platform: Platform
    cookies_dir: Path

    def __init__(self, cookies_dir: Path | None = None):
        if cookies_dir is None:
            cookies_dir = DATA_DIR / "cookies"
        self.cookies_dir = cookies_dir
        self.cookies_dir.mkdir(parents=True, exist_ok=True)

    @property
    def cookies_path(self) -> Path:
        """Get the path to the cookies file for this platform."""
        return self.cookies_dir / f"{self.platform.value}.json"

    @abstractmethod
    async def check_login_state(self, page: Page) -> bool:
        """Check if the user is currently logged in."""
        ...

    @abstractmethod
    async def login(self, page: Page) -> bool:
        """Perform interactive login. Opens a headed browser for user to authenticate."""
        ...

    async def save_cookies(self, context: BrowserContext) -> None:
        """Save browser cookies to disk."""
        cookies = await context.cookies()
        self.cookies_path.write_text(json.dumps(cookies, indent=2))
        logger.info("Saved cookies to %s", self.cookies_path)

    async def load_cookies(self, context: BrowserContext) -> bool:
        """Load saved cookies into browser context."""
        if not self.cookies_path.exists():
            return False

        try:
            cookies = json.loads(self.cookies_path.read_text())
            await context.add_cookies(cookies)
            logger.info("Loaded cookies from %s", self.cookies_path)
            return True
        except (json.JSONDecodeError, IOError) as e:
            logger.warning("Failed to load cookies: %s", e)
            return False

    def clear_cookies(self) -> bool:
        """Clear saved cookies for this platform."""
        if self.cookies_path.exists():
            self.cookies_path.unlink()
            logger.info("Cleared cookies for %s", self.platform.value)
            return True
        return False

    def has_saved_cookies(self) -> bool:
        """Check if there are saved cookies for this platform."""
        return self.cookies_path.exists()


class LoginManager:
    """Manages login handlers for all platforms."""

    def __init__(self, cookies_dir: Path | None = None):
        if cookies_dir is None:
            cookies_dir = DATA_DIR / "cookies"
        self.cookies_dir = cookies_dir
        self._handlers: dict[Platform, AbstractLoginHandler] = {}

    def register(self, handler: AbstractLoginHandler) -> None:
        """Register a login handler for a platform."""
        self._handlers[handler.platform] = handler

    def get_handler(self, platform: Platform) -> AbstractLoginHandler | None:
        """Get the login handler for a platform."""
        return self._handlers.get(platform)

    def get_login_status(self) -> dict[str, dict[str, Any]]:
        """Get login status for all platforms."""
        status = {}
        for platform, handler in self._handlers.items():
            status[platform.value] = {
                "has_cookies": handler.has_saved_cookies(),
            }
        return status
