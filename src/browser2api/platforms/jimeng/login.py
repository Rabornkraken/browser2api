"""即梦AI login handler using phone/QR code authentication."""

import asyncio
import logging
from pathlib import Path

from playwright.async_api import Page

from ...base import AbstractLoginHandler
from ...types import Platform

logger = logging.getLogger(__name__)


class JimengLoginHandler(AbstractLoginHandler):
    """
    Login handler for 即梦AI (Jimeng).

    Jimeng uses phone number or QR code login.
    User authenticates manually in the headed browser window.
    Cookies are persisted via CDP persistent user data dir.
    """

    platform = Platform.JIMENG

    def __init__(self, cookies_dir: Path | None = None):
        super().__init__(cookies_dir)
        self._login_check_timeout = 300  # 5 minutes to wait for login

    async def _check_ui_logged_in(self, page: Page) -> bool:
        """Check if the UI shows logged-in state (user avatar visible in header)."""
        try:
            # Jimeng shows an avatar div when logged in
            avatar_selector = "xpath=//div[contains(@class, 'avatar')]"
            is_visible = await page.is_visible(avatar_selector, timeout=2000)
            if is_visible:
                return True

            # Also check for user menu / profile area
            user_menu_selector = "xpath=//div[contains(@class, 'user-menu')]"
            is_visible = await page.is_visible(user_menu_selector, timeout=1000)
            return is_visible
        except Exception:
            return False

    async def check_login_state(self, page: Page) -> bool:
        """Check if user is logged in on Jimeng."""
        return await self._check_ui_logged_in(page)

    async def login(self, page: Page) -> bool:
        """
        Perform Jimeng login via phone/QR code.

        Opens the Jimeng page and waits for user to complete authentication.
        """
        logger.info("Starting Jimeng login...")

        # Navigate to Jimeng
        from .selectors import LOGIN_URL
        await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(3)

        # Check if already logged in
        if await self._check_ui_logged_in(page):
            logger.info("Already logged in to Jimeng")
            return True

        # Not logged in - try to click login button
        logger.info("Not logged in. Attempting to trigger login dialog...")

        try:
            # Look for login/sign-in button
            login_selectors = [
                "xpath=//button[contains(text(), '登录')]",
                "xpath=//span[contains(text(), '登录')]",
                "xpath=//div[contains(text(), '登录')]",
                "xpath=//a[contains(text(), '登录')]",
            ]
            for sel in login_selectors:
                try:
                    if await page.is_visible(sel, timeout=2000):
                        await page.click(sel)
                        logger.info("Clicked login button")
                        await asyncio.sleep(1)
                        break
                except Exception:
                    continue
        except Exception as e:
            logger.warning("Could not find/click login button: %s", e)

        print("\n" + "=" * 50)
        print("Please login to 即梦AI in the browser window!")
        print("You can use phone number or QR code.")
        print("Waiting up to 5 minutes for login...")
        print("=" * 50 + "\n")

        # Poll for login state change
        for i in range(self._login_check_timeout):
            await asyncio.sleep(1)

            if await self._check_ui_logged_in(page):
                logger.info("Jimeng login successful!")
                # Wait for cookies/state to settle
                await asyncio.sleep(3)
                return True

            if i % 15 == 0 and i > 0:
                remaining = self._login_check_timeout - i
                print(f"Still waiting for login... ({remaining}s remaining)")

        logger.error("Jimeng login timed out after %d seconds", self._login_check_timeout)
        return False
