"""Monitor API responses during video generation to debug failures."""

import asyncio
import json
import logging

from browser2api import BrowserManager, Platform
from browser2api.platforms.jimeng.client import JimengBaseClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)


async def discover():
    bm = BrowserManager()
    try:
        context, page = await bm.launch_for_crawl(Platform.JIMENG)

        base = JimengBaseClient(page, context)
        await base._ensure_generation_page()

        # Switch to video mode
        await page.evaluate("""() => {
            const selects = document.querySelectorAll('.lv-select');
            for (const sel of selects) {
                const text = sel.textContent || '';
                if (text.indexOf('\u751f\u6210') !== -1 && sel.getBoundingClientRect().width > 0) {
                    sel.click();
                    return true;
                }
            }
        }""")
        await asyncio.sleep(0.5)
        await page.evaluate("""() => {
            const options = document.querySelectorAll('.lv-select-option');
            for (const opt of options) {
                const text = (opt.textContent || '').trim();
                if (text.indexOf('\u89c6\u9891\u751f\u6210') !== -1) {
                    opt.click();
                    return;
                }
            }
        }""")
        await asyncio.sleep(2)

        # Monitor ALL API responses (JSON endpoints)
        def on_response(response):
            url = response.url
            ct = response.headers.get('content-type', '')
            status = response.status
            # Log API calls (JSON responses)
            if 'json' in ct or 'api' in url or 'mweb' in url or 'generate' in url:
                async def log_body():
                    try:
                        body = await response.text()
                        # Truncate for readability
                        body_short = body[:500] if len(body) > 500 else body
                        print(f"\n  API [{status}] {url[:120]}")
                        print(f"      {body_short}")
                    except Exception:
                        print(f"\n  API [{status}] {url[:120]} (could not read body)")

                asyncio.ensure_future(log_body())

        page.on('response', on_response)

        # Fill prompt and submit
        print("\n=== Filling prompt and submitting ===")
        await base._fill_prompt("一棵大树在风中摇摆")
        await asyncio.sleep(0.5)
        await base._click_submit()
        print("=== Submitted, monitoring API responses for 60s ===\n")

        # Wait and monitor
        for i in range(60):
            await asyncio.sleep(1)

            # Check for failure/success indicators in DOM
            if i % 5 == 0:
                status_text = await page.evaluate("""() => {
                    // Look for the most recent generation card's status
                    const cards = document.querySelectorAll('[class*="record-content"]');
                    if (cards.length === 0) return null;
                    const latest = cards[0];
                    const text = (latest.textContent || '').trim().replace(/\\s+/g, ' ');
                    return text.substring(0, 200);
                }""")
                if status_text:
                    print(f"  [{i}s] Latest card: {status_text[:150]}")
                    if '\u751f\u6210\u5931\u8d25' in (status_text or ''):
                        print(f"  [{i}s] DETECTED FAILURE - stopping early")
                        break

            if i == 10:
                await page.screenshot(path="test/video_api_10s.png", full_page=False)

    finally:
        await bm.close()


asyncio.run(discover())
