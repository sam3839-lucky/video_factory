#!/usr/bin/env python3
"""扫码登录视频号，保存cookies"""
import sys, json
from pathlib import Path

sys.path.insert(0, '/Users/sam/Library/Python/3.9/lib/python/site-packages')
from playwright.sync_api import sync_playwright

COOKIES_FILE = Path("video_account_cookies.json")
DONE_FILE = Path("login_done.flag")

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=False,
        args=['--disable-blink-features=AutomationControlled']
    )
    context = browser.new_context(
        user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    )
    page = context.new_page()
    
    print("打开发布页面，请用微信扫码登录...")
    page.goto("https://channels.weixin.qq.com/platform/post/create", timeout=30000)
    print(f"页面标题: {page.title()}")
    print(f"当前URL: {page.url}")
    
    # 每5秒检查一次URL是否变化（说明登录成功）
    for i in range(60):  # 最多等5分钟
        import time
        time.sleep(5)
        current_url = page.url
        print(f"[{i*5}s] URL: {current_url}")
        if "post/create" in current_url and "login" not in current_url:
            print("✅ 登录成功！")
            break
    
    print("保存 cookies...")
    cookies = context.cookies()
    with open(COOKIES_FILE, "w") as f:
        json.dump(cookies, f)
    print(f"共 {len(cookies)} 个 cookies:")
    for c in cookies:
        print(f"  {c['domain']:40s} {c['name']:30s} {c['value'][:40]}")
    
    # 写标记文件
    DONE_FILE.write_text("done")
    
    print("完成！浏览器将关闭。")
    browser.close()