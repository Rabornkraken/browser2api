"""Try video generation and capture the full API response on success/failure."""

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

        # Intercept the full body of key API responses
        captured_responses = []

        def on_response(response):
            url = response.url
            if 'get_history_by_ids' in url or 'aigc_draft/generate' in url:
                async def capture():
                    try:
                        body = await response.text()
                        data = json.loads(body)
                        captured_responses.append({'url': url, 'data': data})
                        print(f"\n  === API: {url.split('?')[0].split('/')[-1]} ===")
                        print(json.dumps(data, indent=2, ensure_ascii=False)[:2000])
                    except Exception as e:
                        print(f"\n  API error: {e}")
                asyncio.ensure_future(capture())

            # Also capture any video-related responses
            ct = response.headers.get('content-type', '')
            if '.mp4' in url and 'static/media' not in url:
                print(f"\n  VIDEO NET: {url[:200]}")

        page.on('response', on_response)

        # Fill prompt and submit
        print("\n=== Submitting video prompt ===")
        await base._fill_prompt("一朵花慢慢绽放")
        await asyncio.sleep(0.5)
        await base._click_submit()
        print("=== Submitted ===\n")

        # Wait and poll for results
        for i in range(180):
            await asyncio.sleep(1)

            if i % 10 == 0:
                # Check DOM status
                status = await page.evaluate("""() => {
                    const cards = document.querySelectorAll('[class*="record-content"]');
                    if (cards.length === 0) return null;
                    const latest = cards[0];
                    const text = (latest.textContent || '').trim().replace(/\\s+/g, ' ');
                    return text.substring(0, 200);
                }""")
                if status:
                    print(f"  [{i}s] Card: {status[:150]}")

                if status and '\u751f\u6210\u5931\u8d25' in status:
                    print(f"  [{i}s] FAILURE detected")
                    break

                # Check for video element
                video = await page.evaluate("""() => {
                    for (const v of document.querySelectorAll('video')) {
                        const src = v.src || '';
                        if (src && src.length > 50 && !src.includes('animation')) {
                            return src;
                        }
                    }
                    return null;
                }""")
                if video:
                    print(f"  [{i}s] VIDEO FOUND: {video[:150]}")
                    break

            if i == 30:
                await page.screenshot(path="test/video_success_30s.png", full_page=False)

        # Print summary
        print("\n=== Captured API responses ===")
        for r in captured_responses:
            endpoint = r['url'].split('?')[0].split('/')[-1]
            data = r['data']
            print(f"\n--- {endpoint} ---")
            # Look for item_list, video URLs, status codes
            if 'data' in data:
                d = data['data']
                if isinstance(d, dict):
                    for key, val in d.items():
                        if isinstance(val, dict):
                            status = val.get('task', {}).get('status') if isinstance(val.get('task'), dict) else None
                            items = val.get('item_list', [])
                            fail_msg = val.get('task', {}).get('fail_msg') if isinstance(val.get('task'), dict) else None
                            print(f"  key={key}, task_status={status}, items={len(items)}, fail_msg={fail_msg}")
                            if items:
                                for item in items[:3]:
                                    print(f"    item: {json.dumps(item, ensure_ascii=False)[:300]}")

    finally:
        await bm.close()


asyncio.run(discover())
