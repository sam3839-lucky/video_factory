#!/usr/bin/env python3
"""
视频号浏览器自动化发布脚本
基于 Workbuddy property_clawer 项目的方案：
- 使用 Playwright 自己的 Chromium 浏览器（无需 Google Chrome）
- storage_state() 保存/恢复登录态
- shadow DOM 遍历操作所有页面元素

用法：
    python3 publish_to_video_account.py "视频文件路径" "标题" "描述"
"""
import asyncio
import json
import os
import sys
import random
import argparse
from pathlib import Path
from datetime import datetime

# Playwright 路径
PLAYWRIGHT_PATH = "/Users/sam/Library/Python/3.9/lib/python/site-packages"
sys.path.insert(0, PLAYWRIGHT_PATH)

from playwright.async_api import async_playwright, TimeoutError

# ========== 配置 ==========
CHANNELS_PUBLISH_URL = "https://channels.weixin.qq.com/platform/post/create"
COOKIE_PATH = Path("/Users/sam/video_factory/video_account_state.json")
UPLOAD_WAIT_TIMEOUT = 300
PAGE_LOAD_TIMEOUT = 30
ACTION_INTERVAL_MIN = 2.0
ACTION_INTERVAL_MAX = 5.0


class VideoPublisher:
    """微信视频号发布器"""

    def __init__(self, cookie_path: str):
        self.cookie_path = Path(cookie_path)
        self._browser = None
        self._context = None

    async def _random_delay(self):
        delay = random.uniform(ACTION_INTERVAL_MIN, ACTION_INTERVAL_MAX)
        await asyncio.sleep(delay)

    async def _save_cookies(self, context):
        state = await context.storage_state()
        self.cookie_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cookie_path, 'w') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        print(f"  ✅ Cookie 已保存 ({len(state.get('cookies', []))} 个)")

    async def _load_cookies(self, context) -> bool:
        if not self.cookie_path.exists():
            print(f"  ⚠️ Cookie 文件不存在: {self.cookie_path}")
            return False
        try:
            with open(self.cookie_path, 'r') as f:
                state = json.load(f)
            await context.add_cookies(state.get("cookies", []))
            print(f"  ✅ Cookie 已加载 ({len(state.get('cookies', []))} 个)")
            return True
        except Exception as e:
            print(f"  ❌ Cookie 加载失败: {e}")
            return False

    async def _check_login(self, page) -> bool:
        """检测登录状态"""
        await page.goto(CHANNELS_PUBLISH_URL,
                       wait_until="domcontentloaded",
                       timeout=PAGE_LOAD_TIMEOUT * 1000)
        await asyncio.sleep(3)

        url = page.url
        if "login" in url:
            print("  → 需要登录")
            return False

        # 检查发布页面标志性元素：input[type="file"]
        try:
            file_input = await page.wait_for_selector(
                'input[type="file"]',
                state="attached",
                timeout=10000
            )
            if file_input:
                print("  → 已登录，发布页面就绪")
                return True
        except TimeoutError:
            pass
        except Exception as e:
            print(f"  → 登录检测异常: {e}")
        return False

    def _get_content_frame(self, page):
        """获取 content iframe（视频编辑面板所在的 frame）"""
        for frame in page.frames:
            if frame.name == "content":
                return frame
        return None

    async def _shadow_click(self, page, text_contains: str, exact: bool = False) -> bool:
        """在 WUJIE-APP shadow DOM 中点击包含指定文本的元素"""
        if exact:
            js = """(textToFind) => {
                const hosts = document.querySelectorAll('wujie-app, [shadow-root]');
                for (const host of hosts) {
                    const root = host.shadowRoot;
                    if (!root) continue;
                    const els = root.querySelectorAll('*');
                    for (const el of els) {
                        if (el.textContent.trim() === textToFind) {
                            el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
                            return textToFind;
                        }
                    }
                }
                return null;
            }"""
        else:
            js = """(textToFind) => {
                const hosts = document.querySelectorAll('wujie-app, [shadow-root]');
                for (const host of hosts) {
                    const root = host.shadowRoot;
                    if (!root) continue;
                    const els = root.querySelectorAll('*');
                    for (const el of els) {
                        const text = el.textContent.trim();
                        if (text.includes(textToFind) && text.length < 30) {
                            el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
                            return text;
                        }
                    }
                }
                return null;
            }"""
        result = await page.evaluate(js, text_contains)
        if result:
            print(f"  ✅ shadow DOM 点击: '{result}'")
            return True
        return False

    async def publish(self, video_path: str, title: str,
                     description: str = "") -> dict:
        """
        发布视频到视频号。
        Returns: {"success": bool, "video_url": str, "error": str}
        """
        video_path = str(Path(video_path).resolve())
        if not os.path.exists(video_path):
            return {"success": False, "video_url": "", "error": f"视频文件不存在: {video_path}"}

        async with async_playwright() as p:
            self._browser = await p.chromium.launch(headless=False)
            self._context = await self._browser.new_context(
                viewport={"width": 1280, "height": 800}
            )

            # 加载已保存的 Cookie
            has_cookies = await self._load_cookies(self._context)
            page = await self._context.new_page()

            try:
                # 检测登录
                is_logged_in = await self._check_login(page)
                if not is_logged_in:
                    if has_cookies:
                        print("  🔄 Cookie 可能过期，等待重新扫码...")
                    else:
                        print("  🆕 首次登录，请在浏览器中扫码...")
                    try:
                        await page.wait_for_url("**/platform/post/create**", timeout=120000)
                        print("  ✅ 扫码成功！")
                        await self._save_cookies(self._context)
                    except TimeoutError:
                        return {"success": False, "video_url": "", "error": "扫码登录超时（2分钟）"}
                    except Exception as e:
                        return {"success": False, "video_url": "", "error": f"扫码登录失败: {e}"}

                # ==========================================
                # STEP 1: 上传视频文件
                # ==========================================
                print(f"  📤 开始上传: {os.path.basename(video_path)}")
                await asyncio.sleep(2)

                uploaded = False
                try:
                    async with page.expect_file_chooser(timeout=30000) as fc_info:
                        clicked = False
                        for sel in [
                            'div[class*="upload"]', 'div[class*="Upload"]',
                            'div[class*="drag"]', 'div[class*="Drag"]',
                            'div[class*="add"]', 'div[class*="Add"]',
                            'button:has-text("上传")', 'button:has-text("添加视频")',
                        ]:
                            try:
                                el = await page.wait_for_selector(sel, state="attached", timeout=3000)
                                if el:
                                    box = await el.bounding_box()
                                    if box and box['height'] > 0 and box['width'] > 0:
                                        await el.click()
                                        clicked = True
                                        print(f"  ✅ 点击上传区域: {sel}")
                                        break
                            except Exception:
                                continue

                        if not clicked:
                            await page.mouse.click(640, 400)
                            print("  ✅ 点击页面中心作为兜底")

                    file_chooser = await fc_info.value
                    await file_chooser.set_files(video_path)
                    uploaded = True
                    print("  ✅ 文件已选择，等待上传...")
                except Exception as e:
                    print(f"  ⚠️ 上传触发失败: {e}")
                    await page.screenshot(path="/Users/sam/video_factory/video_upload_error.png")
                    return {"success": False, "video_url": "", "error": f"上传触发失败: {e}"}

                if not uploaded:
                    return {"success": False, "video_url": "", "error": "所有上传策略均失败"}

                # 等待视频就绪信号："直接发表" 按钮出现
                print(f"  ⏳ 等待视频上传就绪（超时 {UPLOAD_WAIT_TIMEOUT}s）...")
                try:
                    await page.wait_for_function(
                        """() => {
                            const hosts = document.querySelectorAll('wujie-app, [shadow-root]');
                            for (const host of hosts) {
                                const root = host.shadowRoot;
                                if (!root) continue;
                                const els = root.querySelectorAll('*');
                                for (const el of els) {
                                    if (el.textContent.trim() === '直接发表') return true;
                                }
                            }
                            return false;
                        }""",
                        timeout=UPLOAD_WAIT_TIMEOUT * 1000
                    )
                    print("  ✅ 视频就绪（检测到'直接发表'按钮）")
                except TimeoutError:
                    print("  ⚠️ 等待视频就绪超时，继续尝试...")

                # 等待编辑区就绪
                await asyncio.sleep(3)
                for attempt in range(10):
                    title_ready = await page.evaluate("""() => {
                        const hosts = document.querySelectorAll('wujie-app, [shadow-root]');
                        for (const host of hosts) {
                            const root = host.shadowRoot;
                            if (!root) continue;
                            const inputs = root.querySelectorAll('input');
                            for (const inp of inputs) {
                                const ph = inp.placeholder || '';
                                if (ph.includes('概括视频') || ph.includes('主要内容')) return true;
                            }
                        }
                        return false;
                    }""")
                    if title_ready:
                        print("  ✅ 编辑区已就绪（标题输入框出现）")
                        break
                    if attempt < 9:
                        print(f"  ⏳ 等待编辑区... ({attempt + 1}/10)")
                    await asyncio.sleep(3)
                else:
                    print("  ⚠️ 编辑区等待超时，继续尝试填写")

                await self._random_delay()

                # ==========================================
                # STEP 2: 填写标题
                # ==========================================
                try:
                    filled_title = await page.evaluate("""(titleText) => {
                        const hosts = document.querySelectorAll('wujie-app, [shadow-root]');
                        for (const host of hosts) {
                            const root = host.shadowRoot;
                            if (!root) continue;
                            const inputs = root.querySelectorAll('input');
                            for (const inp of inputs) {
                                const ph = inp.placeholder || '';
                                if (ph.includes('概括视频') || ph.includes('主要内容')) {
                                    inp.focus();
                                    const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                                        window.HTMLInputElement.prototype, 'value').set;
                                    nativeInputValueSetter.call(inp, titleText);
                                    inp.dispatchEvent(new Event('input', { bubbles: true }));
                                    inp.dispatchEvent(new Event('change', { bubbles: true }));
                                    return titleText;
                                }
                            }
                        }
                        return null;
                    }""", title[:16])
                    if filled_title:
                        print(f"  ✅ 标题已填写: {filled_title}")
                    else:
                        print("  ⚠️ 标题 input 未找到")
                except Exception as e:
                    print(f"  ⚠️ 标题填写失败: {e}")

                await self._random_delay()

                # ==========================================
                # STEP 3: 填写描述
                # ==========================================
                if description:
                    try:
                        filled = await page.evaluate("""(descText) => {
                            const hosts = document.querySelectorAll('wujie-app, [shadow-root]');
                            for (const host of hosts) {
                                const root = host.shadowRoot;
                                if (!root) continue;
                                const editor = root.querySelector('.input-editor[data-placeholder="添加描述"]');
                                if (editor) {
                                    editor.focus();
                                    const sel = window.getSelection();
                                    const range = document.createRange();
                                    range.selectNodeContents(editor);
                                    sel.removeAllRanges();
                                    sel.addRange(range);
                                    document.execCommand('insertText', false, descText);
                                    editor.dispatchEvent(new InputEvent('input', {
                                        inputType: 'insertText',
                                        data: descText,
                                        bubbles: true,
                                        cancelable: true,
                                    }));
                                    return editor.textContent.substring(0, 30) + '...';
                                }
                            }
                            return null;
                        }""", description[:1000])
                        if filled:
                            print(f"  ✅ 描述已填写: {filled}")
                        else:
                            print("  ⚠️ 描述输入框未找到")
                    except Exception as e:
                        print(f"  ⚠️ 描述填写异常: {e}")

                await self._random_delay()

                # ==========================================
                # STEP 4: 关闭弹窗
                # ==========================================
                content_frame = self._get_content_frame(page)

                for _ in range(5):
                    dismissed = await self._shadow_click(page, "我知道了", exact=True)
                    if not dismissed:
                        break
                    print("  ✅ 已关闭 shadow 弹窗: 我知道了")
                    await asyncio.sleep(2)

                await asyncio.sleep(3)

                # ==========================================
                # STEP 5: 点击发表
                # ==========================================
                publish_clicked = False

                # 策略A: content frame 中的发表按钮
                if content_frame:
                    try:
                        publish_btn = await content_frame.wait_for_selector(
                            'button:has-text("发表")',
                            state="attached",
                            timeout=10000
                        )
                        if publish_btn:
                            box = await publish_btn.bounding_box()
                            print(f"  → '发表'按钮位置: {box}")
                            if box:
                                await publish_btn.click(force=True)
                                publish_clicked = True
                                print("  ✅ 在 content frame 中点击了'发表'")
                    except Exception as e:
                        print(f"  ⚠️ content frame 发表按钮: {e}")

                # 策略B: shadow DOM 中的"直接发表"
                if not publish_clicked:
                    print("  → 尝试 shadow DOM '直接发表'...")
                    publish_clicked = await self._shadow_click(page, "直接发表", exact=True)
                    if not publish_clicked:
                        result = await page.evaluate("""() => {
                            const hosts = document.querySelectorAll('wujie-app, [shadow-root]');
                            for (const host of hosts) {
                                const root = host.shadowRoot;
                                if (!root) continue;
                                const els = root.querySelectorAll('*');
                                for (const el of els) {
                                    const text = el.textContent.trim();
                                    if (text.includes('直接发表') && !text.includes('不再提醒')
                                        && !text.includes('声明原创') && text.length <= 10) {
                                        el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
                                        return text;
                                    }
                                }
                            }
                            return null;
                        }""")
                        publish_clicked = bool(result)
                        print(f"  → shadow DOM 非精确匹配: {result}, clicked={publish_clicked}")

                if not publish_clicked:
                    await page.screenshot(path="/Users/sam/video_factory/video_no_publish_btn.png")
                    return {"success": False, "video_url": "", "error": "未找到发表按钮"}

                await asyncio.sleep(5)

                # ==========================================
                # STEP 6: 处理弹窗并确认
                # ==========================================
                for round_num in range(1, 4):
                    dismissed = await self._shadow_click(page, "我知道了")
                    if not dismissed:
                        dismissed_main = await page.evaluate("""() => {
                            const btns = document.querySelectorAll('button');
                            for (const btn of btns) {
                                const text = btn.textContent.trim();
                                if (text === '确定' || text === '确认' || text === '我知道了') {
                                    btn.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
                                    return text;
                                }
                            }
                            return null;
                        }""")
                        if dismissed_main:
                            dismissed = True
                            print(f"  ✅ 已关闭主文档弹窗: {dismissed_main}")

                    if not dismissed:
                        print(f"  → 第 {round_num} 轮：无弹窗")
                        break

                    print(f"  → 第 {round_num} 轮：弹窗已关闭，再次点击发表")
                    await asyncio.sleep(2)
                    if content_frame:
                        try:
                            await content_frame.evaluate("""() => {
                                const btns = document.querySelectorAll('button');
                                for (const btn of btns) {
                                    if (btn.textContent.trim().includes('发表')) btn.click();
                                }
                            }""")
                        except Exception:
                            await self._shadow_click(page, "直接发表", exact=True)
                    else:
                        await self._shadow_click(page, "直接发表", exact=True)
                    await asyncio.sleep(3)

                # ==========================================
                # STEP 7: 检查发布结果
                # ==========================================
                try:
                    await page.wait_for_function(
                        """() => {
                            const url = window.location.href;
                            if (!url.includes('/post/create') && url.includes('/platform')) return true;
                            const body = document.body.innerText;
                            if (body.includes('发布成功') || body.includes('审核中')) return true;
                            return false;
                        }""",
                        timeout=30000
                    )
                    video_url = page.url
                    await self._save_cookies(self._context)
                    print(f"  ✅ 发布成功! URL: {video_url}")
                    return {"success": True, "video_url": video_url, "error": ""}
                except Exception:
                    current_url = page.url
                    try:
                        page_text = await page.evaluate("() => document.body.innerText.substring(0, 500)")
                        print(f"  ⚠️ 发布结果未确认, url={current_url}")
                        print(f"  ⚠️ 页面文本: {page_text[:200]}")
                    except Exception:
                        pass
                    return {
                        "success": False,
                        "video_url": current_url if 'platform' in current_url else "",
                        "error": "发表后未检测到成功信号"
                    }

            except Exception as e:
                import traceback
                traceback.print_exc()
                return {"success": False, "video_url": "", "error": str(e)[:500]}
            finally:
                await self._context.close()
                await self._browser.close()


def main():
    parser = argparse.ArgumentParser(description="视频号浏览器自动化发布")
    parser.add_argument("video_path", help="视频文件路径")
    parser.add_argument("title", help="视频标题")
    parser.add_argument("description", nargs="?", default="", help="视频描述")
    args = parser.parse_args()

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 视频号发布开始")
    print(f"  视频: {args.video_path}")
    print(f"  标题: {args.title}")

    publisher = VideoPublisher(str(COOKIE_PATH))
    result = asyncio.run(publisher.publish(
        video_path=args.video_path,
        title=args.title,
        description=args.description,
    ))

    if result["success"]:
        print(f"\n✅ 发布成功！视频链接: {result['video_url']}")
    else:
        print(f"\n❌ 发布失败: {result['error']}")


if __name__ == "__main__":
    main()