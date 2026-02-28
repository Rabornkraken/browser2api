"""Submit a video prompt and log all network responses to find the real video URL."""

import asyncio
import logging

from browser2api import BrowserManager, Platform
from browser2api.platforms.jimeng.client import JimengBaseClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

logger = logging.getLogger(__name__)


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

        # Log ALL network responses containing video-related content
        interesting_urls = []

        def on_response(response):
            url = response.url
            ct = response.headers.get('content-type', '')
            # Log anything that might be video-related
            if any(kw in url.lower() for kw in ['.mp4', 'video', '.m3u8', 'vod', 'media']):
                is_static = 'static/media' in url or 'animation' in url
                tag = " [STATIC ASSET]" if is_static else ""
                print(f"  NET{tag}: {ct} | {url[:200]}")
                interesting_urls.append((url, ct, is_static))

        page.on('response', on_response)

        # Fill prompt and submit
        await base._fill_prompt("一只小猫在草地上奔跑")
        await asyncio.sleep(0.5)
        await base._click_submit()
        print("\n=== Prompt submitted, monitoring network for 120s ===\n")

        # Also monitor DOM for video elements and any new elements
        for i in range(120):
            await asyncio.sleep(1)

            # Check for video elements in DOM
            video_info = await page.evaluate("""() => {
                const results = [];
                for (const video of document.querySelectorAll('video')) {
                    const src = video.src || '';
                    const sources = Array.from(video.querySelectorAll('source'))
                        .map(s => s.src).filter(s => s);
                    const poster = video.poster || '';
                    const rect = video.getBoundingClientRect();
                    if (rect.width > 50) {
                        results.push({src, sources, poster, w: rect.width, h: rect.height});
                    }
                }
                return results;
            }""")

            if video_info:
                for v in video_info:
                    if v['src'] and 'blob:' not in v['src']:
                        print(f"  DOM VIDEO [{i}s]: src={v['src'][:150]}")
                    if v['sources']:
                        for s in v['sources']:
                            print(f"  DOM VIDEO [{i}s]: source={s[:150]}")
                    if v['poster']:
                        print(f"  DOM VIDEO [{i}s]: poster={v['poster'][:150]}")

            # Check for any new progress indicators or completion states
            if i % 10 == 0:
                progress = await page.evaluate("""() => {
                    // Look for progress bars, loading states, completion indicators
                    const results = [];
                    for (const el of document.querySelectorAll('[class*="progress"], [class*="loading"], [class*="generat"], [class*="complet"], [class*="success"], [class*="result"]')) {
                        const rect = el.getBoundingClientRect();
                        if (rect.width > 50) {
                            const text = (el.textContent || '').trim().substring(0, 100);
                            results.push({class: el.className.substring(0, 80), text});
                        }
                    }
                    return results;
                }""")
                if progress:
                    print(f"  PROGRESS [{i}s]:")
                    for p in progress[:5]:
                        print(f"    {p['class'][:50]} | {p['text'][:80]}")

                # Also screenshot every 30s
                if i % 30 == 0 and i > 0:
                    await page.screenshot(path=f"test/video_gen_{i}s.png", full_page=False)
                    print(f"  SCREENSHOT: test/video_gen_{i}s.png")

        print("\n=== Summary of captured URLs ===")
        for url, ct, is_static in interesting_urls:
            tag = " [STATIC]" if is_static else " [POTENTIAL VIDEO]"
            print(f"  {tag} {ct} | {url[:200]}")

    finally:
        await bm.close()


asyncio.run(discover())
