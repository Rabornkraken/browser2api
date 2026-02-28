"""Discover video duration options and ratio/resolution controls."""

import asyncio
import logging

from browser2api import BrowserManager, Platform

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)


async def discover():
    bm = BrowserManager()
    try:
        context, page = await bm.launch_for_crawl(Platform.JIMENG)

        await page.goto(
            "https://jimeng.jianying.com/ai-tool/image/generate",
            wait_until="domcontentloaded",
            timeout=60000,
        )
        await asyncio.sleep(5)

        # Switch to video mode
        await page.evaluate(
            """() => {
            const selects = document.querySelectorAll('.lv-select');
            for (const sel of selects) {
                const text = sel.textContent || '';
                if (text.indexOf('\u751f\u6210') !== -1 && sel.getBoundingClientRect().width > 0) {
                    sel.click();
                    return true;
                }
            }
            return false;
        }"""
        )
        await asyncio.sleep(0.5)
        await page.evaluate(
            """() => {
            const options = document.querySelectorAll('.lv-select-option');
            for (const opt of options) {
                const text = (opt.textContent || '').trim();
                if (text.indexOf('\u89c6\u9891') !== -1) {
                    opt.click();
                    return text;
                }
            }
            return null;
        }"""
        )
        await asyncio.sleep(2)

        # Find and click the duration dropdown (small lv-select showing "5s")
        duration_opened = await page.evaluate(
            """() => {
            const selects = document.querySelectorAll('.lv-select');
            for (const sel of selects) {
                const text = (sel.textContent || '').trim();
                const rect = sel.getBoundingClientRect();
                if (text.match(/^\\d+s$/) && rect.width < 200 && rect.width > 0) {
                    sel.click();
                    return text;
                }
            }
            return null;
        }"""
        )
        print(f"Clicked duration dropdown: {duration_opened}")
        await asyncio.sleep(1)

        # Read duration options
        duration_options = await page.evaluate(
            """() => {
            const options = document.querySelectorAll('.lv-select-option');
            return Array.from(options).map(o => ({
                text: o.textContent.trim().replace(/\\s+/g, ' '),
                selected: o.classList.contains('lv-select-option-selected'),
            }));
        }"""
        )
        print(f"\nDuration options ({len(duration_options)}):")
        for d in duration_options:
            sel = " [SELECTED]" if d["selected"] else ""
            print(f"  - {d['text']}{sel}")

        await page.screenshot(path="test/video_duration_dropdown.png", full_page=False)
        print("\nScreenshot: test/video_duration_dropdown.png")

        # Close dropdown
        await page.keyboard.press("Escape")
        await asyncio.sleep(0.5)

        # Now check the ratio/resolution button
        ratio_btn_text = await page.evaluate(
            """() => {
            for (const btn of document.querySelectorAll('button')) {
                const text = btn.textContent || '';
                if (text.indexOf(':') !== -1 && text.indexOf('P') !== -1) {
                    return text.trim().replace(/\\s+/g, ' ');
                }
            }
            return null;
        }"""
        )
        print(f"\nRatio/resolution button text: {ratio_btn_text}")

        # Click it and see what popover appears
        ratio_opened = await page.evaluate(
            """() => {
            for (const btn of document.querySelectorAll('button')) {
                const text = btn.textContent || '';
                if (text.indexOf(':') !== -1 && text.indexOf('P') !== -1) {
                    btn.click();
                    return true;
                }
            }
            return false;
        }"""
        )
        print(f"Clicked ratio button: {ratio_opened}")
        await asyncio.sleep(1)

        # Read popover content
        popover_labels = await page.evaluate(
            """() => {
            const popover = document.querySelector('.lv-popover-inner-content');
            if (!popover) return [];
            const labels = popover.querySelectorAll('label');
            return Array.from(labels).map(l => l.textContent.trim().replace(/\\s+/g, ' '));
        }"""
        )
        print(f"\nRatio popover labels ({len(popover_labels)}):")
        for l in popover_labels:
            print(f"  - {l}")

        await page.screenshot(path="test/video_ratio_popover.png", full_page=False)
        print("\nScreenshot: test/video_ratio_popover.png")

        # Also check how credits/cost display per model
        # Switch back to check each model's info
        await page.keyboard.press("Escape")
        await asyncio.sleep(0.5)

        # Read the bottom toolbar for credits info
        toolbar_text = await page.evaluate(
            """() => {
            // Look for credits/cost indicators near the bottom
            const results = [];
            for (const el of document.querySelectorAll('span, div')) {
                const text = (el.textContent || '').trim();
                const rect = el.getBoundingClientRect();
                if (rect.y > 400 && rect.width > 0 && rect.width < 200
                    && (text.match(/\\d+/) && text.length < 20)
                    && rect.height < 50) {
                    results.push({text, y: Math.round(rect.y), x: Math.round(rect.x)});
                }
            }
            return results;
        }"""
        )
        print(f"\nToolbar numbers:")
        for t in toolbar_text:
            print(f"  '{t['text']}' @ ({t['x']}, {t['y']})")

    finally:
        await bm.close()


asyncio.run(discover())
