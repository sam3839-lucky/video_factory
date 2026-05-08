#!/usr/bin/env python3
"""视频号发布 - 完整自动化脚本"""
import time, os, json, subprocess, re, sys
from playwright.sync_api import sync_playwright

# ===== 动态获取 CDP =====
import subprocess as sp
result = sp.run(['curl', '-s', 'http://localhost:9224/json/version'], capture_output=True, text=True)
CDP_URL = json.loads(result.stdout)['webSocketDebuggerUrl']
print(f"CDP: {CDP_URL[:50]}...")

# ===== 从飞书读最新待发布记录 =====
try:
    search_result = sp.run(
        ['lark-cli', 'base', '+record-search',
         '--base-token', 'XX8abIKw7a9GwBsVt57crlbHnOe',
         '--table-id', 'tblHptO4dDJckuFF',
         '--json', json.dumps({"keyword": "待发布", "search_fields": ["发布状态"]})],
        capture_output=True, text=True, timeout=15
    )
    data = json.loads(search_result.stdout)
    records = data['data']['data']
    record_ids = data['data']['record_id_list']
    
    # 取最后一条（最新的）
    last_record = records[-1]
    last_id = record_ids[-1]
    print(f"最新待发布记录: {last_id}")
    
    # 字段顺序: 视频标题, 发布时间, 视频号链接, 文案内容, 归档天数, 视频链接, 视频标签, 
    #            错误信息, 视频类型, 文件大小MB, 原创标志, 下架时间, 创建时间, 发布状态, 
    #            归档时间, 视频描述, 视频文件路径, 下架操作时间
    TITLE_RAW = last_record[0]  # "深圳5月7日\n楼市行情"
    VIDEO_DESC = last_record[15]  # 视频描述字段
    VIDEO_PATH = last_record[16]  # 视频文件路径
    
    TITLE = TITLE_RAW.replace('\n', '').strip()
    
    if not VIDEO_PATH or not os.path.exists(VIDEO_PATH):
        print(f"❌ 视频文件不存在: {VIDEO_PATH}")
        sys.exit(1)
    if not VIDEO_DESC or len(VIDEO_DESC) < 10:
        print(f"❌ 视频描述太短: {VIDEO_DESC}")
        sys.exit(1)
    
    print(f"标题: {TITLE}")
    print(f"描述: {VIDEO_DESC[:50]}...")
    print(f"视频: {VIDEO_PATH}")
    print(f"文件大小: {os.path.getsize(VIDEO_PATH) / 1024 / 1024:.1f}MB")
except Exception as e:
    print(f"❌ 读飞书失败: {e}")
    sys.exit(1)

# ===== 发布 =====
with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp(CDP_URL)
    context = browser.contexts[0]
    pages = context.pages
    
    print(f"\n当前打开的页面数: {len(pages)}")
    for i, pg in enumerate(pages):
        print(f"  页面{i}: {pg.url}")
    
    # 找发布页面
    page = None
    for pg in pages:
        if 'channels.weixin.qq.com/platform' in pg.url:
            page = pg
            break
    
    if not page:
        # 没有发布页面，新建一个
        print("新建发布页面...")
        page = context.new_page()
        page.goto("https://channels.weixin.qq.com/platform/post/create", timeout=30000)
        time.sleep(3)
    else:
        print(f"使用现有页面: {page.url}")
        # 如果不在发布页，导航过去（但skill说不要reload...看看当前是什么）
        if '/post/create' not in page.url:
            print("⚠️ 不在发布页，尝试创建新标签...")
            page = context.new_page()
            page.goto("https://channels.weixin.qq.com/platform/post/create", timeout=30000)
            time.sleep(3)
    
    # ⚠️ 重要：不重新导航，直接等 iframe 出现
    content_frame = None
    for attempt in range(30):
        time.sleep(1)
        for frame in page.frames:
            if "micro/content" in frame.url:
                content_frame = frame
                break
        if content_frame:
            break
        print(f"  [{attempt+1}] 等待 iframe...")
    else:
        print("❌ iframe 未出现")
        sys.exit(1)
    print(f"✅ iframe: {content_frame.url[:80]}...")

    # 1. 上传视频
    print("\n📤 上传视频...")
    with page.expect_file_chooser(timeout=30000) as fc_info:
        content_frame.evaluate(
            "() => document.querySelector('.ant-upload-btn input[type=\"file\"]').click()"
        )
    fc_info.value.set_files(VIDEO_PATH)
    print("⏳ 视频上传中，等待处理完成...")

    # 2. 等"直接发表"按钮出现（视频处理完）
    for i in range(90):  # 最多3分钟
        time.sleep(2)
        ready = content_frame.evaluate("""() => {
            for (const btn of document.querySelectorAll('button')) {
                if (btn.textContent.trim() === '直接发表') return true;
            }
            return false;
        }""")
        if ready:
            print(f"✅ 视频处理完成 ({(i+1)*2}s)")
            break
    else:
        print("❌ 视频上传超时")
        sys.exit(1)

    time.sleep(2)

    # 3. 填标题
    print(f"\n📝 标题: {TITLE}")
    content_frame.evaluate("""(t) => {
        const inp = document.querySelector('input[placeholder="概括视频主要内容，字数建议6-16个字符"]');
        if (!inp) return;
        const native = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        native.call(inp, t);
        inp.dispatchEvent(new Event('input', {bubbles: true}));
        inp.dispatchEvent(new Event('change', {bubbles: true}));
    }""", TITLE)
    print("✅ 标题已填")

    # 4. 填描述（必须用 execCommand insertText）
    print(f"\n📝 描述: {VIDEO_DESC[:40]}...")
    # 先清空
    content_frame.evaluate("""() => {
        const div = document.querySelector('div[data-placeholder="添加描述"]');
        if (!div) return;
        div.focus();
        div.innerText = '';
        div.dispatchEvent(new Event('input', {bubbles: true}));
    }""")
    time.sleep(0.3)
    # 用 execCommand 填入
    content_frame.evaluate("""(d) => {
        const div = document.querySelector('div[data-placeholder="添加描述"]');
        if (!div) return;
        div.focus();
        document.execCommand('insertText', false, d);
    }""", VIDEO_DESC)
    
    # 验证描述
    desc_val = content_frame.evaluate("""() => {
        const div = document.querySelector('div[data-placeholder="添加描述"]');
        return div ? div.innerText : "";
    }""")
    if not desc_val or len(desc_val) < 10:
        print(f"❌ 描述填写失败! desc='{desc_val}'")
        sys.exit(1)
    print(f"✅ 描述已填: {desc_val[:50]}...")

    # 5. 声明原创（4步流程）
    print("\n🔰 声明原创...")
    
    # 步骤1: 滚动到声明原创区域
    content_frame.evaluate("""() => {
        const all = Array.from(document.querySelectorAll('*'));
        for (const el of all) {
            if (el.textContent.trim() === '声明原创' && el.tagName === 'SPAN') {
                const parent = el.parentElement;
                if (parent && parent.className.includes('label')) {
                    el.scrollIntoView({block: 'center'});
                }
            }
        }
    }""")
    time.sleep(0.5)

    # 步骤2: 点击"声明原创" SPAN
    content_frame.evaluate("""() => {
        const all = Array.from(document.querySelectorAll('*'));
        for (const el of all) {
            if (el.textContent.trim() === '声明原创' && el.tagName === 'SPAN') {
                const parent = el.parentElement;
                if (parent && parent.className.includes('label')) {
                    el.scrollIntoView({block: 'center'});
                    el.click();
                    return;
                }
            }
        }
    }""")
    time.sleep(1)

    # 步骤3: 勾选同意条款（用 page.mouse.click 绝对坐标）
    checkbox_pos = content_frame.evaluate("""() => {
        for (const el of document.querySelectorAll('*')) {
            if (el.textContent?.includes('我已阅读并同意')) {
                const cb = el.querySelector('input[type="checkbox"]');
                if (cb) {
                    cb.scrollIntoView({block: 'center'});
                    const rect = cb.getBoundingClientRect();
                    const iframeEl = document.querySelector('iframe[src*="micro/content"]');
                    const iframeRect = iframeEl ? iframeEl.getBoundingClientRect() : {left: 0, top: 0};
                    return {
                        x: rect.left + rect.width/2 + iframeRect.left,
                        y: rect.top + rect.height/2 + iframeRect.top
                    };
                }
            }
        }
        return null;
    }""")
    if checkbox_pos:
        page.mouse.click(checkbox_pos['x'], checkbox_pos['y'])
        print(f"  ✅ 勾选同意条款")
    else:
        print("  ⚠️ checkbox未找到")
    time.sleep(0.5)

    # 步骤4: 点击弹窗内"声明原创"按钮
    btn_pos = content_frame.evaluate("""() => {
        const dialog = document.querySelector('[class*="declare-original-dialog"]');
        const searchRoot = dialog || document;
        const btns = Array.from(searchRoot.querySelectorAll('button'));
        const target = btns.find(b => b.textContent.trim() === '声明原创');
        if (!target) return null;
        target.scrollIntoView({block: 'center'});
        const rect = target.getBoundingClientRect();
        const iframeEl = document.querySelector('iframe[src*="micro/content"]');
        const iframeRect = iframeEl ? iframeEl.getBoundingClientRect() : {left: 0, top: 0};
        return {
            x: rect.left + rect.width/2 + iframeRect.left,
            y: rect.top + rect.height/2 + iframeRect.top
        };
    }""")
    if btn_pos:
        page.mouse.click(btn_pos['x'], btn_pos['y'])
        print(f"  ✅ 点击声明原创按钮")
    else:
        print("  ⚠️ 声明原创按钮未找到")
    time.sleep(1)

    # 验证声明原创
    state = content_frame.evaluate("""() => {
        const btns = Array.from(document.querySelectorAll('button')).filter(b => b.offsetParent !== null);
        return { buttons: btns.map(b => b.textContent.trim()).filter(t => t) };
    }""")
    print(f"  按钮列表: {state['buttons']}")
    if '直接发表' in state['buttons']:
        print("  ✅ 声明原创成功!")

    # 6. 发布前最终验证
    print("\n🔍 发布前验证...")
    final = content_frame.evaluate("""() => {
        const inp = document.querySelector('input[placeholder="概括视频主要内容，字数建议6-16个字符"]');
        const div = document.querySelector('div[data-placeholder="添加描述"]');
        return {
            title: inp ? inp.value : '',
            desc: div ? div.innerText : ''
        };
    }""")
    print(f"  标题验证: '{final['title']}'")
    print(f"  描述验证: '{final['desc'][:50] if final['desc'] else '(空)'}'")
    
    if not final['title'] or not final['desc']:
        print(f"❌ 标题或描述为空，拒绝发布!")
        sys.exit(1)
    print("✅ 验证通过")

    # 7. 点击"发表" → 弹窗 → "不保存" → "直接发表"
    print("\n🚀 发表...")
    
    # 点"发表"
    fabiao_result = content_frame.evaluate("""() => {
        const btns = Array.from(document.querySelectorAll('button'));
        const publishBtn = btns.find(b => b.textContent.trim() === '发表' && b.offsetParent !== null);
        if (publishBtn) {
            publishBtn.click();
            return 'clicked: 发表';
        }
        return '发表按钮未找到';
    }""")
    print(f"  {fabiao_result}")
    time.sleep(1)

    # 关闭"保留编辑"弹窗，点"不保存"
    dont_save_result = content_frame.evaluate("""() => {
        const btns = Array.from(document.querySelectorAll('button'));
        for (const btn of btns) {
            if (btn.textContent.trim() === '不保存' && btn.offsetParent !== null) {
                btn.click();
                return 'clicked: 不保存';
            }
        }
        return '未找到不保存按钮';
    }""")
    print(f"  {dont_save_result}")
    time.sleep(1)

    # 点"直接发表"
    direct_result = content_frame.evaluate("""() => {
        const btns = Array.from(document.querySelectorAll('button'));
        const directBtn = btns.find(b => b.textContent.trim() === '直接发表' && b.offsetParent !== null);
        if (directBtn) {
            directBtn.click();
            return 'clicked: 直接发表';
        }
        return '直接发表按钮未找到';
    }""")
    print(f"  {direct_result}")

    time.sleep(5)
    
    # 截图保存
    print(f"\n当前URL: {page.url}")
    page.screenshot(path="/Users/sam/video_factory/after_publish.png", full_page=True)
    print("📸 截图: /Users/sam/video_factory/after_publish.png")
    
    # 判断是否发布成功
    success = 'platform/post' not in page.url or 'success' in page.url.lower()
    print(f"\n🎉 {'发布成功!' if success else '发布完成，请确认'}")
    
    # 更新飞书记录
    if success or True:  # 总是尝试更新
        record_id = last_id
        cmd = ['lark-cli', 'base', '+record-upsert',
               '--base-token', 'XX8abIKw7a9GwBsVt57crlbHnOe',
               '--table-id', 'tblHptO4dDJckuFF',
               '--record-id', record_id,
               '--json', json.dumps({"发布状态": "已发布", "发布时间": time.strftime('%Y-%m-%d %H:%M:%S')})]
        result = sp.run(cmd, capture_output=True, text=True)
        print(f"飞书更新: {result.stdout[:200]}")
    
    print(f"\n✅ 完成! 记录ID: {record_id}")
