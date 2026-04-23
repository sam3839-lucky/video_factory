#!/usr/bin/env python3
"""
视频号发布测试脚本
基于 Workbuddy property_clawer 项目的方案：
1. 用 Playwright 自己的 Chromium 扫码登录
2. 保存 storage_state() 到 cookie 文件
3. 之后复用 cookie 文件
"""
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, '/Users/sam/Library/Python/3.9/lib/python/site-packages')
from playwright.async_api import async_playwright

COOKIE_PATH = Path("/Users/sam/video_factory/video_account_state.json")
COOKIE_PATH.parent.mkdir(parents=True, exist_ok=True)

CHANNELS_PUBLISH_URL = "https://channels.weixin.qq.com/platform/post/create"


async def save_cookies(context, path):
    state = await context.storage_state()
    with open(path, 'w') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    print(f"✅ Cookie 已保存: {path} ({len(state.get('cookies', []))} 个)")


async def load_cookies(context, path) -> bool:
    if not path.exists():
        return False
    try:
        with open(path, 'r') as f:
            state = json.load(f)
        await context.add_cookies(state.get("cookies", []))
        print(f"✅ Cookie 已加载: {len(state.get('cookies', []))} 个")
        return True
    except Exception as e:
        print(f"❌ Cookie 加载失败: {e}")
        return False


async def check_login(page) -> bool:
    """检测是否已登录（检查页面是否有 file input）"""
    try:
        await page.goto(CHANNELS_PUBLISH_URL, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
        
        url = page.url
        print(f"  当前URL: {url}")
        
        if "login" in url:
            print("  → 需要登录")
            return False
        
        # 检查发布页面标志性元素
        try:
            file_input = await page.wait_for_selector('input[type="file"]', state="attached", timeout=10000)
            if file_input:
                print("  → 已登录，发布页面就绪")
                return True
        except Exception:
            pass
        
        print("  → 可能未登录（无file input）")
        return False
    except Exception as e:
        print(f"  → 登录检测异常: {e}")
        return False


async def main():
    async with async_playwright() as p:
        # 启动 Playwright 自己的 Chromium（不是 Google Chrome）
        browser = await p.chromium.launch(
            headless=False,  # 必须可见才能扫码
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800}
        )
        page = await context.new_page()

        # 尝试加载已有 cookie
        has_cookies = await load_cookies(context, COOKIE_PATH)

        # 检查登录状态
        is_logged_in = await check_login(page)

        if not is_logged_in:
            if has_cookies:
                print("\n🔄 Cookie可能过期，等待重新扫码...")
            else:
                print("\n🆕 首次登录，请在浏览器中扫码...")
            
            # 等待扫码（2分钟）
            try:
                await page.wait_for_url("**/platform/post/create**", timeout=120000)
                print("✅ 扫码成功！")
                await save_cookies(context, COOKIE_PATH)
            except TimeoutError:
                print("❌ 扫码超时（2分钟）")
                await browser.close()
                return
        
        # 已登录，保存cookie
        await save_cookies(context, COOKIE_PATH)
        
        # 截图确认
        await page.screenshot(path="/Users/sam/video_factory/video_publish_ready.png", full_page=True)
        print(f"📸 页面截图: /Users/sam/video_factory/video_publish_ready.png")
        
        await asyncio.sleep(3)
        await browser.close()
        print("完成！")


if __name__ == "__main__":
    asyncio.run(main())