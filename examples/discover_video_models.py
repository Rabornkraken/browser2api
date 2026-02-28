"""Discover available video models and their free-tier status in Jimeng UI."""

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

        # Navigate to generation page
        await page.goto(
            "https://jimeng.jianying.com/ai-tool/image/generate",
            wait_until="domcontentloaded",
            timeout=60000,
        )
        await asyncio.sleep(5)

        # Click the type selector (the lv-select containing "生成")
        switched = await page.evaluate(
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
        print(f"Clicked type selector: {switched}")
        await asyncio.sleep(1)

        # Read type options
        type_options = await page.evaluate(
            """() => {
            const options = document.querySelectorAll('.lv-select-option');
            return Array.from(options).map(o => o.textContent.trim().replace(/\\s+/g, ' '));
        }"""
        )
        print(f"Type options: {type_options}")

        # Click video option
        clicked_video = await page.evaluate(
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
        print(f"Clicked video option: {clicked_video}")
        await asyncio.sleep(2)

        # Screenshot the video mode UI
        await page.screenshot(path="test/video_mode_ui.png", full_page=False)
        print("Screenshot: test/video_mode_ui.png")

        # Open model dropdown
        opened = await page.evaluate(
            """() => {
            const selects = document.querySelectorAll('.lv-select');
            for (const sel of selects) {
                const text = sel.textContent || '';
                if (text.indexOf('\u751f\u6210') === -1 && sel.getBoundingClientRect().width > 0) {
                    sel.click();
                    return text.trim().replace(/\\s+/g, ' ');
                }
            }
            return null;
        }"""
        )
        print(f"\nCurrent model in dropdown: {opened}")
        await asyncio.sleep(1)

        # Read all video model options with full detail
        models = await page.evaluate(
            """() => {
            const options = document.querySelectorAll('.lv-select-option');
            const results = [];
            for (const opt of options) {
                const text = (opt.textContent || '').trim().replace(/\\s+/g, ' ');
                const isSelected = opt.classList.contains('lv-select-option-selected');
                const html = opt.innerHTML;
                results.push({text, isSelected, html: html.substring(0, 500)});
            }
            return results;
        }"""
        )
        print(f"\nVideo model options ({len(models)}):")
        for i, m in enumerate(models):
            sel = " [SELECTED]" if m["isSelected"] else ""
            print(f"  {i+1}. {m['text']}{sel}")

        # Screenshot with dropdown open
        await page.screenshot(path="test/video_models_dropdown.png", full_page=False)
        print("\nScreenshot: test/video_models_dropdown.png")

        # Close dropdown
        await page.keyboard.press("Escape")
        await asyncio.sleep(0.5)

        # Check for duration controls
        duration_info = await page.evaluate(
            """() => {
            const results = [];
            // Look for duration-related elements
            for (const el of document.querySelectorAll('label, button, span, div')) {
                const text = (el.textContent || '').trim();
                if ((text === '5s' || text === '10s' || text === '15s'
                     || text.match(/^\\d+s$/) || text.match(/^\\d+秒$/))
                    && el.getBoundingClientRect().width > 0
                    && el.getBoundingClientRect().width < 200) {
                    const rect = el.getBoundingClientRect();
                    results.push({
                        text,
                        tag: el.tagName,
                        class: el.className.substring(0, 100),
                        x: Math.round(rect.x),
                        y: Math.round(rect.y),
                        w: Math.round(rect.width),
                        h: Math.round(rect.height),
                    });
                }
            }
            return results;
        }"""
        )
        print(f"\nDuration controls found: {len(duration_info)}")
        for d in duration_info:
            print(f"  {d['text']} ({d['tag']}.{d['class'][:40]}) @ ({d['x']},{d['y']}) {d['w']}x{d['h']}")

        # Look for ratio controls
        ratio_info = await page.evaluate(
            """() => {
            const results = [];
            for (const btn of document.querySelectorAll('button')) {
                const text = btn.textContent || '';
                if (text.indexOf(':') !== -1 || text.indexOf('\u6bd4\u4f8b') !== -1) {
                    results.push(text.trim().replace(/\\s+/g, ' '));
                }
            }
            return results;
        }"""
        )
        print(f"\nRatio buttons: {ratio_info}")

    finally:
        await bm.close()


asyncio.run(discover())
