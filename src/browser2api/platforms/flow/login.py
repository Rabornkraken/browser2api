"""Google Flow login handler using Google Account authentication."""

import asyncio
import logging
from pathlib import Path

from playwright.async_api import Page

from ...base import AbstractLoginHandler
from ...types import Platform

logger = logging.getLogger(__name__)


class FlowLoginHandler(AbstractLoginHandler):
    """
    Login handler for Google Flow (labs.google).

    Uses Google account authentication. User authenticates manually
    in the headed browser window. Cookies are persisted via CDP
    persistent user data dir.
    """

    platform = Platform.FLOW

    def __init__(self, cookies_dir: Path | None = None):
        super().__init__(cookies_dir)
        self._login_check_timeout = 300  # 5 minutes to wait for login

    async def _check_ui_logged_in(self, page: Page) -> bool:
        """Check if the UI shows logged-in state (Google Account avatar visible)."""
        try:
            # Primary: Google Account avatar image with aria-label
            avatar_selector = 'img[aria-label*="Google Account"]'
            if await page.is_visible(avatar_selector, timeout=2000):
                return True

            # Fallback: profile image from googleusercontent.com
            profile_selector = 'img[src*="googleusercontent.com/a/"]'
            if await page.is_visible(profile_selector, timeout=1000):
                return True

            # Fallback: absence of sign-in links indicates logged-in state
            sign_in_visible = await page.evaluate("""() => {
                for (const a of document.querySelectorAll('a')) {
                    const href = a.href || '';
                    const text = (a.textContent || '').toLowerCase();
                    if (href.includes('accounts.google.com/signin')
                        || href.includes('accounts.google.com/ServiceLogin')
                        || text.includes('sign in')
                        || text.includes('sign-in')) {
                        const rect = a.getBoundingClientRect();
                        if (rect.width > 0 && rect.height > 0) {
                            return true;
                        }
                    }
                }
                return false;
            }""")
            if sign_in_visible:
                return False

            # If no sign-in links found and page has loaded, check for any
            # user-related elements that indicate authentication
            has_user_element = await page.evaluate("""() => {
                // Look for any profile/account related buttons or images
                for (const el of document.querySelectorAll('button, img')) {
                    const aria = el.getAttribute('aria-label') || '';
                    if (aria.toLowerCase().includes('account')
                        || aria.toLowerCase().includes('profile')) {
                        return true;
                    }
                }
                return false;
            }""")
            return has_user_element

        except Exception:
            return False

    async def check_login_state(self, page: Page) -> bool:
        """Check if user is logged in on Google Flow."""
        return await self._check_ui_logged_in(page)

    async def login(self, page: Page) -> bool:
        """
        Perform Google Flow login via Google Sign-in.

        Navigates to Flow (which redirects to Google Sign-in if
        unauthenticated) and waits for user to complete authentication.
        """
        logger.info("Starting Google Flow login...")

        from .selectors import TOOL_URL
        await page.goto(TOOL_URL, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(3)

        # Check if already logged in
        if await self._check_ui_logged_in(page):
            logger.info("Already logged in to Google Flow")
            return True

        # Not logged in - try to click sign-in links
        logger.info("Not logged in. Attempting to trigger Google Sign-in...")

        try:
            sign_in_selectors = [
                'a[href*="accounts.google.com"]',
                "xpath=//a[contains(text(), 'Sign in')]",
                "xpath=//button[contains(text(), 'Sign in')]",
                "xpath=//a[contains(text(), 'Sign-in')]",
                "xpath=//span[contains(text(), 'Sign in')]",
            ]
            for sel in sign_in_selectors:
                try:
                    if await page.is_visible(sel, timeout=2000):
                        await page.click(sel)
                        logger.info("Clicked sign-in link")
                        await asyncio.sleep(2)
                        break
                except Exception:
                    continue
        except Exception as e:
            logger.warning("Could not find/click sign-in link: %s", e)

        print("\n" + "=" * 50)
        print("Please sign in to Google in the browser window!")
        print("Complete the Google authentication flow.")
        print("Waiting up to 5 minutes for login...")
        print("=" * 50 + "\n")

        # Poll for login state change
        for i in range(self._login_check_timeout):
            await asyncio.sleep(1)

            if await self._check_ui_logged_in(page):
                logger.info("Google Flow login successful!")
                await asyncio.sleep(3)
                return True

            if i % 15 == 0 and i > 0:
                remaining = self._login_check_timeout - i
                print(f"Still waiting for login... ({remaining}s remaining)")

        logger.error("Google Flow login timed out after %d seconds", self._login_check_timeout)
        return False
