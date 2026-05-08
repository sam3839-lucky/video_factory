#!/usr/bin/env python3
"""
测试视频号自动化发布
用法: python3 test_video_publish.py [视频文件路径]
"""
import sys
import os
import asyncio
import json
from pathlib import Path

COOKIE_PATH = Path("/Users/sam/video_factory/video_account_state.json")
VIDEO_FACTORY_DIR = Path("/Users/sam/video_factory")
CHANNELS_PUBLISH_URL = "https://channels.weixin.qq.com/platform/post/create"
DRAFTS_DIR = Path.home() / "Videos" / "drafts"

PLAYWRIGHT_PATH = "/Users/sam/Library/Python/3.9/lib/python/site-packages"
sys.path.insert(0, PLAYWRIGHT_PATH)
from playwright.async_api import async_playwright


async def check_login(page) -> bool:
    await page.goto(CHANNELS_PUBLISH_URL, wait_until="domcontentloaded", timeout=30000)
    await asyncio.sleep(3)
    if "login" in page.url:
        return False
    try:
        await page.wait_for_selector('input[type="file"]', state="attached", timeout=10000)
        return True
    except Exception:
        return False


async def shadow_click(page, text_contains: str, exact: bool = False) -> bool:
    if exact:
        js = """(t) => {
            const hosts = document.querySelectorAll('wujie-app, [shadow-root]');
            for (const h of hosts) {
                const r = h.shadowRoot; if (!r) continue;
                for (const el of r.querySelectorAll('*')) {
                    if (el.textContent.trim() === t) { el.dispatchEvent(new MouseEvent('click', {bubbles:true,cancelable:true})); return t; }
                }
            }
            return null;
        }"""
    else:
        js = """(t) => {
            const hosts = document.querySelectorAll('wujie-app, [shadow-root]');
            for (const h of hosts) {
                const r = h.shadowRoot; if (!r) continue;
                for (const el of r.querySelectorAll('*')) {
                    const txt = el.textContent.trim();
                    if (txt.includes(t) && txt.length < 30) { el.dispatchEvent(new MouseEvent('click', {bubbles:true,cancelable:true})); return txt; }
                }
            }
            return null;
        }"""
    result = await page.evaluate(js, text_contains)
    return bool(result)


async def test_publish(video_path: str, headless: bool = False):
    """测试发布流程 - 不实际发表，只测到上传视频那步"""
    print(f"\n=== 视频号发布测试 ===")
    print(f"视频文件: {video_path}")
    print(f"文件存在: {Path(video_path).exists()}")
    print(f"模式: {'无头' if headless else '有头'}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(viewport={"width": 1280, "height": 800})

        # 加载 cookie
        if COOKIE_PATH.exists():
            try:
                with open(COOKIE_PATH) as f:
                    state = json.load(f)
                await context.add_cookies(state.get("cookies", []))
                print(f"✅ Cookie 已加载 ({len(state.get('cookies', []))} 个)")
            except Exception as e:
                print(f"⚠️ Cookie 加载失败: {e}")

        page = await context.new_page()

        # 检查登录状态
        is_logged_in = await check_login(page)
        if not is_logged_in:
            print("❌ 未登录或登录已过期，需要重新扫码")
            print("请在打开的浏览器窗口扫码登录...")
            try:
                await page.wait_for_url("**/platform/post/create**", timeout=120000)
                state = await context.storage_state()
                with open(COOKIE_PATH, 'w') as f:
                    json.dump(state, f, ensure_ascii=False, indent=2)
                print("✅ 登录成功，Cookie 已保存")
            except TimeoutError:
                print("❌ 扫码登录超时")
                await browser.close()
                return
            except Exception as e:
                print(f"❌ 登录失败: {e}")
                await browser.close()
                return
        else:
            print("✅ 已登录")

        # 上传视频
        print(f"\n📤 上传视频...")
        try:
            async with page.expect_file_chooser(timeout=30000) as fc_info:
                clicked = False
                for sel in ['div[class*="upload"]', 'button:has-text("上传")', 'button:has-text("添加视频")']:
                    try:
                        el = await page.wait_for_selector(sel, state="attached", timeout=3000)
                        if el:
                            await el.click()
                            clicked = True
                            break
                    except Exception:
                        continue
                if not clicked:
                    await page.mouse.click(640, 400)
            await (await fc_info.value).set_files(video_path)
            print("✅ 文件已选择，等待上传...")
        except Exception as e:
            print(f"❌ 上传失败: {e}")
            await browser.close()
            return

        # 等待视频就绪（最多等5分钟）
        print("⏳ 等待视频上传就绪（最多5分钟）...")
        try:
            await page.wait_for_function(
                """() => {
                    const hosts = document.querySelectorAll('wujie-app, [shadow-root]');
                    for (const h of hosts) {
                        const r = h.shadowRoot; if (!r) continue;
                        for (const el of r.querySelectorAll('*')) {
                            if (el.textContent.trim() === '直接发表') return true;
                        }
                    }
                    return false;
                }""",
                timeout=300000
            )
            print("✅ 视频已就绪（'直接发表'按钮出现）")
        except Exception:
            print("⚠️ 等待视频就绪超时，但继续尝试...")
            await asyncio.sleep(5)

        await asyncio.sleep(3)

        # 截图保存当前状态
        screenshot_path = VIDEO_FACTORY_DIR / "test_video_publish_state.png"
        await page.screenshot(path=str(screenshot_path))
        print(f"📸 当前状态已截图: {screenshot_path}")

        print("\n=== 测试完成 ===")
        await browser.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        # 找一个测试视频
        videos = list(DRAFTS_DIR.glob("*.mp4"))
        if videos:
            video_path = str(videos[0])
            print(f"使用最新视频: {video_path}")
        else:
            print("用法: python3 test_video_publish.py [视频文件路径]")
            sys.exit(1)
    else:
        video_path = sys.argv[1]

    asyncio.run(test_publish(video_path))
