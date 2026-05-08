#!/usr/bin/env python3
"""闪剪自动化脚本 - 完整流程（表格驱动版）
状态流转: 待制作/制作失败 → 制作中 → 待发布（成功）/ 制作失败（失败）
"""
import sys, os, json, time, subprocess

# Playwright 浏览器路径（Hermes 环境需要显式设置）
os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', '/Users/sam/Library/Caches/ms-playwright')

from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.dirname(__file__))
from table_utils import (
    get_all_records_by_status,
    update_status,
    update_record,
    STATUS_PENDING_MAKE, STATUS_MAKE_FAIL, STATUS_MAKING, STATUS_PENDING_PUB,
)

COOKIE_FILE = "/Users/sam/.video_factory/shanjian_cookies.json"
TEMPLATE_NAME = "深圳4月26日楼市行情"
OUTPUT_DIR = "/Users/sam/Videos"
BOT_CHAT_ID = "oc_e8b467f584d247feb1f6bf63bbe33d66"


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")


# ============================== 工具函数 ==============================

def load_cookies(ctx):
    with open(COOKIE_FILE) as f:
        cookies = json.load(f)
    for c in cookies:
        if 'expiry' in c:
            c['expires'] = c['expiry']
            del c['expiry']
    ctx.add_cookies(cookies)


def send_feishu_message(text):
    """发送飞书文本消息给波哥"""
    cmd = [
        'lark-cli', 'im', 'messages', 'create',
        '--as', 'user',
        '--receive-id-type', 'open_id',
        '--receive-id', BOT_CHAT_ID,
        '--msg-type', 'text',
        '--content', json.dumps({"text": text}),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0


def check_cookie_valid():
    """Cookie 预检：headless 验证登录态"""
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False,
                args=['--no-first-run', '--no-default-browser-check'])
            ctx = browser.new_context()
            load_cookies(ctx)
            page = ctx.new_page()
            page.goto('https://app.shanjian.tv/product', timeout=15000)
            page.wait_for_load_state('domcontentloaded')
            time.sleep(3)
            page_text = page.evaluate("() => document.body.innerText")
            browser.close()
            if '登录/注册' in page_text or '手机登录' in page_text:
                err = "⚠️ 闪剪 Cookie 已失效，请手动登录后更新"
                log(err)
                send_feishu_message(err)
                return False
            log("✅ Cookie 预检通过")
            return True
    except Exception as e:
        err = f"⚠️ Cookie 预检失败: {e}"
        log(err)
        send_feishu_message(err)
        return False


# ============================== 闪剪页面操作 ==============================

def find_template_card(page, template_name):
    """查找模板卡片，返回 {x, y, title} 或 None"""
    all_titles = page.evaluate("""() => {
        const cards = document.querySelectorAll('[class*="_item_"]');
        return Array.from(cards).slice(0, 20).map(c => {
            const t = c.querySelector('[class*="_title_"]');
            return t ? t.textContent.trim() : '';
        });
    }""")
    matched_title = None
    for t in all_titles:
        if template_name in t:
            matched_title = t
            break
    if not matched_title:
        log(f"⚠️ 模板「{template_name}」不存在。现有模板: {all_titles}")
        return None

    card_info = page.evaluate(f"""(title) => {{
        const cards = document.querySelectorAll('[class*="_item_"]');
        for (const card of cards) {{
            const t = card.querySelector('[class*="_title_"]');
            if (t && t.textContent.trim().includes(title)) {{
                card.scrollIntoView({{behavior: 'instant', block: 'center'}});
                const rect = card.getBoundingClientRect();
                return {{x: rect.x + rect.width/2, y: rect.y + rect.height/2, title: t.textContent.trim()}};
            }}
        }}
        return null;
    }}""", matched_title)
    time.sleep(1)

    if not card_info:
        log("⚠️ 滚动后未找到卡片坐标")
        return None
    log(f"   模板: {card_info['title']} at ({card_info['x']:.0f}, {card_info['y']:.0f})")
    return card_info


def do_same_title(page, ctx, record_id, video_title, body_text):
    """
    做同款 → 进编辑器 → 改标题/水印/正文 → 导出
    video_title: 已去除换行（short_title）
    body_text: 表格中的「文案内容」
    ctx: BrowserContext（用于捕获前端自动打开的新页面）
    """
    # ---- 1. 找到模板卡片 ----
    card_info = find_template_card(page, TEMPLATE_NAME)
    if not card_info:
        raise Exception(f"未找到模板卡片: {TEMPLATE_NAME}")

    # ---- 2. Hover → JS点击「做同款」----
    page.mouse.move(card_info['x'] - 60, card_info['y'] - 80)
    time.sleep(0.5)
    page.mouse.move(card_info['x'], card_info['y'])
    time.sleep(3)

    # 用 expect_popup 捕获前端做同款后自动打开的新页面
    doc_page = None
    try:
        with page.expect_popup(timeout=60000) as popup_info:
            page.evaluate(f"""(function() {{
                const cx = {card_info['x']}, cy = {card_info['y']};
                const btns = document.querySelectorAll('button');
                let best = null, bestDist = 9999;
                for (let i=0; i<btns.length; i++) {{
                    if (btns[i].textContent.indexOf('做同款')>=0) {{
                        const r = btns[i].getBoundingClientRect();
                        if (r.width === 0 || r.height === 0) continue;
                        const dist = Math.abs(r.x+r.width/2 - cx) + Math.abs(r.y+r.height/2 - cy);
                        if (dist < bestDist) {{ best = btns[i]; bestDist = dist; }}
                    }}
                }}
                if (best) best.click();
            }})()""")
        doc_page = popup_info.value
        log(f"✅ 已点击做同款 → 编辑器弹出: {doc_page.url[:80]}")
    except Exception as e:
        # expect_popup 超时，回退到轮询
        log(f"⚠️ expect_popup 未捕获，回退轮询: {e}")
        initial_page_count = len(ctx.pages)
        for _ in range(120):
            time.sleep(0.5)
            pages = ctx.pages
            if len(pages) > initial_page_count:
                for p in pages:
                    if 'doc.shanjian.tv' in p.url:
                        doc_page = p
                        break
            if doc_page:
                log(f"✅ 轮询捕获编辑器: {doc_page.url[:80]}")
                break
    if not doc_page:
        raise Exception("做同款后未自动打开编辑器页面")

    doc_page.wait_for_load_state('domcontentloaded')
    time.sleep(5)
    log(f"✅ 编辑器已打开: {doc_page.url}")

    # ---- 3a. 修改视频名称（铅笔图标）----
    log("修改视频名称...")
    try:
        doc_page.evaluate("""() => {
            const icons = document.querySelectorAll('.editIcon, [class*="icon-a-program_icon_edit"]');
            for (const icon of icons) { icon.click(); break; }
        }""")
        time.sleep(1)
        doc_page.evaluate(f"""(title) => {{
            const input = document.querySelector('input.ant-input');
            if (!input) return;
            const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
            setter.call(input, title);
            input.dispatchEvent(new Event('input', {{ bubbles: true }}));
            input.dispatchEvent(new Event('change', {{ bubbles: true }}));
        }}""", video_title)
        time.sleep(0.5)
        doc_page.evaluate("""() => {
            const btns = document.querySelectorAll('div[class*="_custom-button"]');
            for (const b of btns) { if (b.textContent.includes('确定')) { b.click(); break; } }
        }""")
        time.sleep(1)
        log(f"✅ 视频名称已修改「{video_title}」")
    except Exception as e:
        log(f"⚠️ 修改视频名称失败: {e}")

    # ---- 3b. 修改水印（视频预览区内 contenteditable → dblclick → Cmd+V 粘贴）----
    log("修改视频预览区水印...")
    try:
        # 直接找视频预览区内的 contenteditable（水印文字），而不是靠坐标计算
        wm_found = doc_page.evaluate(f"""(title) => {{
            const stage = document.querySelector('[class*="_canvas_m8kpp"]') 
                       || document.querySelector('[class*="_canvas-wrap"]');
            if (!stage) return {{found: false, reason: 'no stage'}};
            
            // 在预览区内找到带日期格式的 contenteditable（水印）
            const editables = stage.querySelectorAll('[contenteditable]');
            for (const el of editables) {{
                const t = el.textContent.trim();
                // 水印通常包含"X月X日"或"楼市行情"等模式
                if (t.length > 3 && /\\d+月\\d+[日号]|楼市/.test(t)) {{
                    const r = el.getBoundingClientRect();
                    return {{
                        found: true,
                        rect: {{x: r.x, y: r.y, w: r.width, h: r.height}},
                        center: {{x: r.x + r.width/2, y: r.y + r.height/2}},
                        text: t
                    }};
                }}
            }}
            // 回退：取第一个 contenteditable
            if (editables.length > 0) {{
                const el = editables[0];
                const r = el.getBoundingClientRect();
                return {{
                    found: true,
                    rect: {{x: r.x, y: r.y, w: r.width, h: r.height}},
                    center: {{x: r.x + r.width/2, y: r.y + r.height/2}},
                    text: el.textContent.trim()
                }};
            }}
            return {{found: false, reason: 'no editables', count: editables.length}};
        }}""", video_title)

        if not wm_found.get('found'):
            log(f"⚠️ 未找到水印 contenteditable: {wm_found}")
        else:
            wx = wm_found['center']['x']
            wy = wm_found['center']['y']
            log(f"   水印位置: ({wx:.0f}, {wy:.0f}) 文本:「{wm_found['text'][:30]}」")
            
            # 按波哥演示步骤：移动 → 单击 → 双击 → Cmd+V → 点外面
            doc_page.mouse.move(wx, wy)
            time.sleep(0.3)
            doc_page.mouse.click(wx, wy)
            time.sleep(0.3)
            doc_page.mouse.dblclick(wx, wy)
            time.sleep(0.5)
            # Cmd+V 粘贴（dblclick 已全选文字，直接粘贴替换）
            doc_page.evaluate(f"navigator.clipboard.writeText('{video_title}')")
            time.sleep(0.3)
            doc_page.keyboard.press('Meta+V')
            time.sleep(0.5)
            # 点外面确认
            doc_page.mouse.click(wx + 200, wy + 200)
            time.sleep(0.5)
            log(f"✅ 水印已修改「{video_title}」")
    except Exception as e:
        log(f"⚠️ 修改水印失败: {e}")

    # ---- 3c. 修改正文（点图文内容下文本区→Cmd+A→粘贴）----
    log("修改正文文案...")
    try:
        doc_page.evaluate("""() => {
            const elms = document.querySelectorAll('*');
            for (const el of elms) {
                if (el.textContent.trim() === '图文内容') { el.click(); return; }
            }
        }""")
        time.sleep(2)

        rt_info = doc_page.evaluate("""() => {
            const rt = document.querySelector('[class*="_rich-text_"]');
            if (rt) {
                const rect = rt.getBoundingClientRect();
                return {x: rect.x + rect.width/2, y: rect.y + 30};
            }
            return null;
        }""")
        if not rt_info:
            log("⚠️ 未找到正文输入区")
        else:
            log(f"   正文区 at ({rt_info['x']:.0f}, {rt_info['y']:.0f})")
            doc_page.mouse.click(rt_info['x'], rt_info['y'])
            time.sleep(0.5)
            doc_page.keyboard.press('Meta+A')
            time.sleep(0.3)
            doc_page.evaluate(f"navigator.clipboard.writeText({json.dumps(body_text)})")
            time.sleep(0.3)
            doc_page.keyboard.press('Meta+V')
            time.sleep(0.5)
            doc_page.mouse.click(10, 500)
            time.sleep(0.5)
            log("✅ 正文文案已填入")
    except Exception as e:
        log(f"⚠️ 修改正文失败: {e}")

    # ---- 截图 + 导出 ----
    doc_page.screenshot(path="/Users/sam/video_factory/shanjian_run_result.png")
    log("截图: shanjian_run_result.png")

    log("导出视频...")
    doc_page.evaluate('''() => {
        const btn = [...document.querySelectorAll('button')].find(b => b.textContent.includes('导出视频'));
        if (btn) btn.click();
    }''')
    log("✅ 导出任务已提交")
    time.sleep(3)
    return time.strftime('%Y.%m.%d %H:%M')


def poll_video_done(page, video_title, after_time=None, timeout=60 * 60):
    """轮询作品列表，等待视频生成完毕（仅匹配 after_time 之后创建的卡片）"""
    interval = 60
    elapsed = 0
    while elapsed < timeout:
        time.sleep(interval)
        elapsed += interval
        page.reload()
        page.wait_for_load_state('domcontentloaded')
        time.sleep(3)

        # 找卡片 + hover 后才检查下载按钮（下载按钮 hover 才出现）
        info = page.evaluate(f"""(title) => {{
            const after = {json.dumps(after_time) if after_time else 'null'};
            const cards = document.querySelectorAll('[class*="_item_"]');
            for (const card of cards) {{
                const titleEl = card.querySelector('[class*="_title_"]');
                if (titleEl && titleEl.textContent.includes(title)) {{
                    const timeText = (card.querySelector('[class*="_time_"]')?.textContent || '').trim();
                    if (after && timeText < after) continue;
                    const durEl = card.querySelector('[class*="_duration_"]');
                    const durText = durEl ? durEl.textContent.trim() : '';
                    // 先拿到卡片位置（用于 hover）
                    const r = card.getBoundingClientRect();
                    return {{
                        title: titleEl.textContent.trim(),
                        time: timeText,
                        duration: durText,
                        hasDuration: /^[0-9]{{2}}:[0-9]{{2}}/.test(durText),
                        pos: {{x: r.x + r.width/2, y: r.y + r.height/2}}
                    }};
                }}
            }}
            return null;
        }}""", video_title)

        # hover 后检查下载按钮
        if info and info['hasDuration']:
            page.mouse.move(info['pos']['x'], info['pos']['y'])
            time.sleep(1.5)
            has_dl = page.evaluate(f"""(title) => {{
                const cards = document.querySelectorAll('[class*="_item_"]');
                for (const card of cards) {{
                    if (card.textContent.includes(title)) {{
                        return !!card.querySelector('i[class*="Mywork-Download"]');
                    }}
                }}
                return false;
            }}""", video_title)
            info['hasDownload'] = has_dl

        log(f"  [{elapsed//60}min] 查找「{video_title}」: {info}")
        if info and info['hasDuration'] and info.get('hasDownload'):
            log(f"✅ 视频生成完毕: {info['title']} 时长 {info['time']}")
            return True
    raise Exception(f"视频生成超时（等待超过{timeout//60}分钟）")


def download_video(page, video_title):
    """hover 到目标卡片 → 点击下载 → 返回保存路径"""
    # 找到目标卡片的下载按钮（通过 JS 定位）
    card_xy = page.evaluate(f"""(title) => {{
        const cards = document.querySelectorAll('[class*="_item_"]');
        for (const card of cards) {{
            const t = card.querySelector('[class*="_title_"]');
            if (t && t.textContent.includes(title)) {{
                const rect = card.getBoundingClientRect();
                card.scrollIntoView({{behavior:'instant',block:'center'}});
                return [rect.x + rect.width/2, rect.y + rect.height/2];
            }}
        }}
        return null;
    }}""", video_title)

    if not card_xy:
        raise Exception(f"下载时未找到视频卡片: {video_title}")

    page.mouse.move(card_xy[0], card_xy[1])
    time.sleep(2)

    dl_btn = page.locator('i[class*="Mywork-Download"]').first
    bbox = dl_btn.bounding_box()
    if not bbox:
        # 备选：JS click 下载按钮
        page.evaluate("""() => {
            const icons = document.querySelectorAll('i[class*="Mywork-Download"]');
            if (icons.length > 0) icons[0].click();
        }""")
        time.sleep(3)

    safe_title = video_title.replace('/', '_')
    save_path = f"{OUTPUT_DIR}/{safe_title}.mp4"

    with page.expect_download(timeout=60000) as dl_info:
        dl_btn.click(force=True)
    dl = dl_info.value
    dl.save_as(save_path)
    size_mb = os.path.getsize(save_path) / 1024 / 1024
    log(f"✅ 下载完成: {save_path} ({size_mb:.1f}MB)")
    return save_path


# ============================== 主流程 ==============================

def main():
    # ---- 第〇步：Cookie 预检 ----
    if not check_cookie_valid():
        log("❌ Cookie 校验未通过，终止任务")
        return

    # ---- 第一步：查表格 ----
    record_id = None
    fields = None
    all_records = get_all_records_by_status([STATUS_PENDING_MAKE, STATUS_MAKE_FAIL])
    for rid, flds in all_records:
        if flds.get('文案内容'):
            body = flds.get('文案内容', '')
            # 检查成交数据是否全为 0（避免浪费算力）
            import re
            numbers = re.findall(r'(\d+)套', body)
            if numbers and all(n == '0' for n in numbers[:2]):
                log(f"⏭️ 记录 {rid} 成交数据全为0，跳过")
                update_status(rid, STATUS_MAKE_FAIL, "数据全为0，跳过制作")
                time.sleep(1)
                continue
            record_id = rid
            fields = flds
            break
        log(f"⚠️ 记录 {rid} 文案内容为空，跳过")
        update_status(rid, STATUS_MAKE_FAIL, "文案内容为空")
        time.sleep(1)

    if not record_id:
        log("❌ 没有待制作的记录，退出")
        send_feishu_message("❌ 闪剪自动化：无待制作记录")
        return

    video_title = fields.get('视频标题', '')
    body_text = fields.get('文案内容', '')
    short_title = video_title.replace('\n', '').strip()

    log(f"✅ 找到待制作记录: {record_id}")
    log(f"   视频标题: {video_title}")
    log(f"   文案预览: {body_text[:50]}...")

    # ---- 第二步：设为制作中 ----
    if not update_status(record_id, STATUS_MAKING):
        log("❌ 设置制作中状态失败，退出")
        return

    try:
        with sync_playwright() as p:
            # ---- 第三步：启动浏览器 + 登录闪剪 ----
            browser = p.chromium.launch(
                headless=False,
                args=['--disable-blink-features=AutomationControlled', '--no-first-run', '--no-default-browser-check']
            )
            ctx = browser.new_context(viewport={'width': 1920, 'height': 1080})
            load_cookies(ctx)

            # ★ 必须在 new_page 之前设 on('page') 监听，否则做同款弹出的新页面无法被捕获
            new_pages = []
            def _on_new_page(p):
                new_pages.append(p)
            ctx.on('page', _on_new_page)

            page = ctx.new_page()
            page.goto('https://app.shanjian.tv/product', timeout=30000)
            page.wait_for_load_state('domcontentloaded')
            time.sleep(5)

            page_text = page.evaluate("() => document.body.innerText")
            if '登录/注册' in page_text:
                raise Exception("Cookie已失效")

            log(f"✅ 已登录: {page.url}")

            # ---- 第四步：做同款 + 修改 + 导出 ----
            export_time = do_same_title(page, ctx, record_id, short_title, body_text)

            # ---- 第五步：等待渲染（只匹配导出时间后的新卡片）----
            log(f"⏳ 等待视频生成（导出时间 {export_time}，最多60分钟）...")
            poll_video_done(page, short_title, after_time=export_time)

            # ---- 第六步：下载 ----
            log("📥 下载视频...")
            save_path = download_video(page, short_title)

            # ---- 第七步：发飞书 ----
            safe_name = short_title.replace('/', '_')
            video_dir = os.path.dirname(os.path.abspath(save_path))

            # 生成封面
            cover_path = os.path.join(video_dir, f"{safe_name}_cover.jpg")
            subprocess.run([
                'ffmpeg', '-y', '-i', save_path,
                '-vframes', '1', '-q:v', '2', cover_path
            ], capture_output=True)

            # 发视频消息
            result = subprocess.run([
                'lark-cli', 'im', '+messages-send',
                '--chat-id', BOT_CHAT_ID,
                '--video', os.path.basename(save_path),
                '--video-cover', os.path.basename(cover_path),
            ], capture_output=True, text=True, cwd=video_dir)

            if result.returncode != 0:
                log(f"⚠️ 飞书发送失败: {result.stderr.strip()[:200]}")
            else:
                log("✅ 视频已发送到飞书群")

            # ---- 第八步：更新表格状态 ----
            update_record(record_id, {
                '视频文件路径': save_path,
                '发布状态': STATUS_PENDING_PUB,
            })
            log(f"✅ 制作完成，状态已更新为「待发布」")
            send_feishu_message(f"✅ 闪剪制作完成：{short_title}")

    except Exception as e:
        err_msg = str(e)
        log(f"❌ 制作失败: {err_msg}")
        update_status(record_id, STATUS_MAKE_FAIL, err_msg)
        send_feishu_message(f"❌ 闪剪制作失败：{short_title}，原因：{err_msg}")


if __name__ == "__main__":
    main()
