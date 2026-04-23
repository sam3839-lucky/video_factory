#!/usr/bin/env python3
"""
视频自动发布 Cron 脚本
扫描多维表格，自动发布待发布视频，并支持定时下架

Base: 视频号发布记录
Table: 发布记录 (tblHptO4dDJckuFF)
"""

import os
import sys
import json
import subprocess
import datetime
import tempfile
import shutil
from pathlib import Path

# ========== 配置 ==========
BASE_TOKEN = "XX8abIKw7a9GwBsVt57crlbHnOe"
TABLE_ID = "tblHptO4dDJckuFF"
FEISHU_CHAT_ID = "oc_e8b467f584d247feb1f6bf63bbe33d66"  # 团队工作报告群
MP_DIR = Path.expanduser(Path("~/Videos")).resolve()
DRAFTS_DIR = MP_DIR / "drafts"
ARCHIVED_DIR = MP_DIR / "archived"
VIDEO_FACTORY_DIR = Path("/Users/sam/video_factory")

# 确保目录存在
DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
ARCHIVED_DIR.mkdir(parents=True, exist_ok=True)

# ========== 飞书多维表格操作 ==========

LARK_CLI = os.path.expanduser("~/.npm-global/bin/lark-cli")

def lark_cli(args: list) -> dict:
    """执行 lark-cli 命令并返回 JSON 结果"""
    cmd = [LARK_CLI] + args
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"lark-cli failed: {result.stderr}")
    return json.loads(result.stdout)


def parse_records_response(result: dict) -> list:
    """
    解析 lark-cli record-list 返回的数据
    lark-cli 返回 {"data": {"data": [[val1, val2...], ...], "fields": [...], "record_id_list": [...]}}
    转换为 [{"record_id": "...", "fields": {"field1": val1, ...}}, ...]
    """
    data = result.get("data", {})
    field_names = data.get("fields", [])
    rows = data.get("data", [])
    record_ids = data.get("record_id_list", [])
    
    records = []
    for i, row in enumerate(rows):
        rec = {
            "record_id": record_ids[i] if i < len(record_ids) else None,
            "fields": dict(zip(field_names, row))
        }
        records.append(rec)
    return records


def get_pending_records():
    """获取待发布的记录（状态=pending 且 发布时间≤当前时间）"""
    result = lark_cli([
        "base", "+record-list",
        "--base-token", BASE_TOKEN,
        "--table-id", TABLE_ID,
        "--limit", "200"
    ])
    records = parse_records_response(result)

    now = datetime.datetime.now()
    pending = []
    for record in records:
        fields = record.get("fields", {})
        status = fields.get("发布状态", {})
        publish_time = fields.get("发布时间", {})
        
        # 检查发布状态是否为 pending
        # 飞书多维表格的单选/多选字段返回 ["value"] 格式
        if isinstance(status, list):
            status_name = status[0] if status else ""
        elif isinstance(status, dict):
            status_name = status.get("name", "")
        else:
            status_name = str(status) if status else ""
        
        if status_name != "pending":
            continue
        
        # 检查发布时间
        if isinstance(publish_time, str) and publish_time:
            try:
                # 飞书 datetime 格式：2024-04-23T10:00:00Z
                pub_dt = datetime.datetime.fromisoformat(publish_time.replace("Z", "+00:00"))
                pub_dt_local = pub_dt.astimezone().replace(tzinfo=None)
                if pub_dt_local > now:
                    continue  # 未来发布时间，跳过
            except Exception:
                pass
        
        pending.append(record)
    
    return pending


def get_records_to_unpublish():
    """获取待下架的记录（状态=published 且 下架时间≤当前时间）"""
    result = lark_cli([
        "base", "+record-list",
        "--base-token", BASE_TOKEN,
        "--table-id", TABLE_ID,
        "--limit", "200"
    ])
    records = parse_records_response(result)

    now = datetime.datetime.now()
    to_unpublish = []
    for record in records:
        record_id = record.get("record_id")
        fields = record.get("fields", {})
        status = fields.get("发布状态", [])
        unpublish_time = fields.get("下架时间", {})
        
        # 检查发布状态是否为 published
        # 飞书多维表格的单选/多选字段返回 ["value"] 格式
        if isinstance(status, list):
            status_name = status[0] if status else ""
        elif isinstance(status, dict):
            status_name = status.get("name", "")
        else:
            status_name = str(status) if status else ""
        
        if status_name != "published":
            continue
        
        # 检查下架时间
        if isinstance(unpublish_time, str) and unpublish_time:
            try:
                un_dt = datetime.datetime.fromisoformat(unpublish_time.replace("Z", "+00:00"))
                un_dt_local = un_dt.astimezone().replace(tzinfo=None)
                if un_dt_local > now:
                    continue  # 未来下架时间，跳过
            except Exception:
                continue
        
        to_unpublish.append(record)
    
    return to_unpublish


def update_record(record_id: str, updates: dict):
    """更新记录字段"""
    # +record-upsert 使用 --json '{"field": value}' 格式
    result = lark_cli([
        "base", "+record-upsert",
        "--base-token", BASE_TOKEN,
        "--table-id", TABLE_ID,
        "--record-id", record_id,
        "--json", json.dumps(updates, ensure_ascii=False)
    ])
    return result


# ========== 视频生成 ==========

def generate_video(script_text: str, output_path: str) -> str:
    """
    调用 generate_video.py 生成视频
    :param script_text: 文案内容
    :param output_path: 输出文件路径
    :return: 生成的文件路径
    """
    gen_script = VIDEO_FACTORY_DIR / "generate_video.py"
    
    # 暂时用 SCRIPT 环境变量传参（后续可改为文件参数）
    env = os.environ.copy()
    env["VIDEO_SCRIPT"] = script_text
    env["VIDEO_OUTPUT"] = output_path
    
    result = subprocess.run(
        [sys.executable, str(gen_script)],
        env=env,
        capture_output=True,
        text=True,
        cwd=str(VIDEO_FACTORY_DIR)
    )
    
    if result.returncode != 0:
        raise RuntimeError(f"generate_video.py failed: {result.stderr}")
    
    return output_path


# ========== 视频号发布 ==========

# Playwright 路径
PLAYWRIGHT_PATH = "/Users/sam/Library/Python/3.9/lib/python/site-packages"
sys.path.insert(0, PLAYWRIGHT_PATH)
import asyncio
from playwright.async_api import async_playwright

COOKIE_PATH = Path("/Users/sam/video_factory/video_account_state.json")


def publish_to_video_account(video_path: str, record: dict) -> str:
    """
    发布视频到视频号（浏览器自动化）
    :param video_path: 本地视频文件路径
    :param record: 多维表格记录
    :return: 视频号链接（空表示失败）
    """
    fields = record.get("fields", {})

    # 从记录中获取发布信息
    video_title = fields.get("视频标题", "") or "无标题"
    video_desc = fields.get("视频描述", "") or ""

    # 判断是否原创
    is_original = fields.get("原创标志", {})
    if isinstance(is_original, dict):
        is_original_name = is_original.get("name", "否")
    else:
        is_original_name = str(is_original)

    print(f"  视频标题: {video_title}")
    print(f"  视频描述: {video_desc[:50]}..." if len(str(video_desc)) > 50 else f"  视频描述: {video_desc}")
    print(f"  原创标志: {is_original_name}")

    # 调用异步发布函数
    result = asyncio.run(_async_publish(video_path, video_title, video_desc))

    if result["success"]:
        print(f"  ✅ 发布成功: {result['video_url']}")
        return result.get("video_url", "")
    else:
        print(f"  ❌ 发布失败: {result['error']}")
        return ""


async def _async_publish(video_path: str, title: str, description: str) -> dict:
    """异步发布视频"""
    CHANNELS_PUBLISH_URL = "https://channels.weixin.qq.com/platform/post/create"

    async def _check_login(page) -> bool:
        await page.goto(CHANNELS_PUBLISH_URL, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
        if "login" in page.url:
            return False
        try:
            await page.wait_for_selector('input[type="file"]', state="attached", timeout=10000)
            return True
        except Exception:
            return False

    async def _shadow_click(page, text_contains: str, exact: bool = False) -> bool:
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

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)  # launchd无GUI，用无头模式
        context = await browser.new_context(viewport={"width": 1280, "height": 800})

        # 加载 cookie
        if COOKIE_PATH.exists():
            try:
                with open(COOKIE_PATH) as f:
                    state = json.load(f)
                await context.add_cookies(state.get("cookies", []))
                print(f"  ✅ Cookie 已加载 ({len(state.get('cookies', []))} 个)")
            except Exception as e:
                print(f"  ⚠️ Cookie 加载失败: {e}")

        page = await context.new_page()

        # 检查/执行登录
        is_logged_in = await _check_login(page)
        if not is_logged_in:
            print("  🆕 请扫码登录...")
            try:
                await page.wait_for_url("**/platform/post/create**", timeout=120000)
                state = await context.storage_state()
                with open(COOKIE_PATH, 'w') as f:
                    json.dump(state, f, ensure_ascii=False, indent=2)
                print("  ✅ 登录成功，Cookie 已保存")
            except TimeoutError:
                return {"success": False, "video_url": "", "error": "扫码登录超时"}
            except Exception as e:
                return {"success": False, "video_url": "", "error": f"登录失败: {e}"}

        # 上传视频
        print(f"  📤 上传视频: {Path(video_path).name}")
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
            print("  ✅ 文件已选择")
        except Exception as e:
            return {"success": False, "video_url": "", "error": f"上传失败: {e}"}

        # 等待视频就绪
        print("  ⏳ 等待视频上传就绪...")
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
            print("  ✅ 视频就绪")
        except Exception:
            print("  ⚠️ 等待视频就绪超时，继续...")

        await asyncio.sleep(3)

        # 填写标题
        try:
            await page.evaluate("""(t) => {
                const hosts = document.querySelectorAll('wujie-app, [shadow-root]');
                for (const h of hosts) {
                    const r = h.shadowRoot; if (!r) continue;
                    for (const inp of r.querySelectorAll('input')) {
                        const ph = inp.placeholder || '';
                        if (ph.includes('概括视频') || ph.includes('主要内容')) {
                            const s = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                            s.call(inp, t);
                            inp.dispatchEvent(new Event('input', {bubbles:true}));
                            inp.dispatchEvent(new Event('change', {bubbles:true}));
                            return;
                        }
                    }
                }
            }""", title[:16])
            print(f"  ✅ 标题已填写: {title[:16]}")
        except Exception as e:
            print(f"  ⚠️ 标题填写失败: {e}")

        await asyncio.sleep(2)

        # 填写描述
        if description:
            try:
                await page.evaluate("""(d) => {
                    const hosts = document.querySelectorAll('wujie-app, [shadow-root]');
                    for (const h of hosts) {
                        const r = h.shadowRoot; if (!r) continue;
                        const ed = r.querySelector('.input-editor[data-placeholder="添加描述"]');
                        if (ed) {
                            ed.focus();
                            document.execCommand('insertText', false, d);
                            ed.dispatchEvent(new InputEvent('input', {inputType:'insertText',data:d,bubbles:true,cancelable:true}));
                            return;
                        }
                    }
                }""", description[:1000])
                print(f"  ✅ 描述已填写")
            except Exception as e:
                print(f"  ⚠️ 描述填写失败: {e}")

        await asyncio.sleep(2)

        # 关闭弹窗
        for _ in range(5):
            dismissed = await _shadow_click(page, "我知道了", exact=True)
            if not dismissed:
                break
            await asyncio.sleep(2)

        await asyncio.sleep(3)

        # 点击发表
        publish_clicked = False
        for _ in range(3):
            clicked = await _shadow_click(page, "直接发表", exact=True)
            if clicked:
                publish_clicked = True
                break
            await asyncio.sleep(2)

        if not publish_clicked:
            await browser.close()
            return {"success": False, "video_url": "", "error": "未找到发表按钮"}

        await asyncio.sleep(5)

        # 确认发布成功
        for _ in range(3):
            dismissed = await _shadow_click(page, "我知道了")
            if dismissed:
                await asyncio.sleep(3)
                if True:
                    await asyncio.sleep(2)
                    continue
            break

        try:
            await page.wait_for_function(
                """() => {
                    const url = window.location.href;
                    if (!url.includes('/post/create') && url.includes('/platform')) return true;
                    return false;
                }""",
                timeout=30000
            )
            video_url = page.url
            # 保存 cookie
            state = await context.storage_state()
            with open(COOKIE_PATH, 'w') as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            await browser.close()
            return {"success": True, "video_url": video_url, "error": ""}
        except Exception:
            current_url = page.url
            await browser.close()
            if 'platform' in current_url:
                return {"success": True, "video_url": current_url, "error": ""}
            return {"success": False, "video_url": "", "error": "发布后未检测到成功信号"}


# ========== 视频号下架 ==========

def unpublish_from_video_account(record: dict) -> bool:
    """
    从视频号下架视频
    :param record: 多维表格记录
    :return: 是否成功
    TODO: 实现浏览器自动化下架视频
    """
    fields = record.get("fields", {})
    video_title = fields.get("视频标题", "")
    video_url = fields.get("视频号链接", "")
    
    print(f"  下架视频: {video_title}")
    print(f"  视频链接: {video_url}")
    
    # TODO: 浏览器自动化下架
    # 1. 登录视频号后台
    # 2. 进入内容管理
    # 3. 找到对应视频
    # 4. 点击下架/删除
    # 5. 确认下架
    
    raise NotImplementedError("视频号下架自动化尚未实现")


# ========== 公网预览链接 ==========

def upload_to_feishu_drive(video_path: str) -> str:
    """
    上传视频到飞书云盘，返回预览链接
    :param video_path: 本地视频文件路径
    :return: 飞书云盘预览链接
    """
    video_path = str(Path(video_path).resolve())
    video_name = Path(video_path).name
    video_dir = Path(video_path).parent

    # lark-cli 要求相对路径，所以切换到文件所在目录执行
    original_cwd = os.getcwd()
    os.chdir(video_dir)

    result = lark_cli([
        "--as", "user",
        "drive", "+upload",
        "--file", f"./{video_name}",
        "--name", video_name
    ])

    os.chdir(original_cwd)

    if not result.get("ok"):
        raise RuntimeError(f"飞书云盘上传失败: {result.get('error', {})}")

    file_token = result.get("data", {}).get("file_token", "")
    preview_url = f"https://bytedance.feishu.cn/file/{file_token}"
    print(f"  已上传飞书云盘: {preview_url}")
    return preview_url


def create_public_link(video_path: str) -> str:
    """
    创建预览链接：上传飞书云盘，返回预览链接
    """
    video_path = str(Path(video_path).resolve())
    print(f"  上传飞书云盘: {video_path}")
    return upload_to_feishu_drive(video_path)


# ========== 飞书通知 ==========

def send_published_notification(title: str, video_path: str, preview_url: str,
                                video_url: str, video_type: str):
    """
    发送飞书通知 - 视频已自动发布到视频号
    """
    message = f"""🎬 视频已自动发布！

📺 标题：{title}
🏷️ 类型：{video_type}

👀 飞书预览：{preview_url}
🔗 视频号：{video_url}

📁 本地文件：{video_path}"""

    print(f"[飞书通知]\n{message}")

    result = lark_cli([
        "--as", "user",
        "im", "+messages-send",
        "--chat-id", FEISHU_CHAT_ID,
        "--text", message
    ])
    if result.get("ok"):
        print(f"  ✅ 飞书通知已发送，message_id: {result.get('data', {}).get('message_id', 'N/A')}")
    else:
        print(f"  ❌ 飞书通知发送失败: {result.get('error', {})}")


def send_upload_notification(title: str, video_path: str, preview_url: str, 
                             video_type: str, record: dict, record_id: str):
    """
    发送飞书通知 - 视频已生成，待手动发布到视频号
    """
    fields = record.get("fields", {})
    video_desc = fields.get("视频描述", "")
    video_tags = fields.get("视频标签", "")
    is_original = fields.get("原创标志", {})
    if isinstance(is_original, dict):
        is_original_name = is_original.get("name", "否")
    else:
        is_original_name = str(is_original)

    desc_preview = str(video_desc)[:100] + "..." if len(str(video_desc)) > 100 else str(video_desc)
    message = f"""🎬 视频已生成，待手动发布！

📺 标题：{title}
🏷️ 类型：{video_type}
📝 视频描述：{desc_preview}
🏷️ 标签：{video_tags}
✅ 原创：{is_original_name}

👀 预览链接：{preview_url}

📁 视频文件：{video_path}

⏰ 请登录视频号后台完成发布，完成后手动更新多维表格中的「视频号链接」和「发布时间」字段。"""

    print(f"[飞书通知]\n{message}")

    # 实际发送飞书消息到群
    result = lark_cli([
        "--as", "user",
        "im", "+messages-send",
        "--chat-id", FEISHU_CHAT_ID,
        "--text", message
    ])
    if result.get("ok"):
        print(f"  ✅ 飞书通知已发送，message_id: {result.get('data', {}).get('message_id', 'N/A')}")
    else:
        print(f"  ❌ 飞书通知发送失败: {result.get('error', {})}")


# ========== 主流程 ==========

def process_pending_videos():
    """处理待发布的视频
    
    流程：生成视频 → 发布到视频号 → 上传飞书云盘预览 → 更新多维表格 → 通知波哥
    状态：pending → uploading → published（自动）/ failed
    """
    records = get_pending_records()
    
    if not records:
        print("没有待发布的视频")
        return
    
    print(f"找到 {len(records)} 条待发布记录")
    
    for record in records:
        record_id = record.get("record_id", {})
        fields = record.get("fields", {})
        
        # 获取 record_id
        if isinstance(record_id, dict):
            rid = record_id.get("text", "") or record_id.get("value", "")
        else:
            rid = str(record_id)
        
        print(f"\n处理记录: {rid}")
        
        # 获取文案内容
        script_text = fields.get("文案内容", "")
        if not script_text:
            print("  ⚠️ 文案内容为空，跳过")
            update_record(rid, {
                "发布状态": "failed",
                "错误信息": "文案内容为空"
            })
            continue
        
        video_title = fields.get("视频标题", "")
        video_type = fields.get("视频类型", {})
        if isinstance(video_type, dict):
            video_type = video_type.get("name", "日报")
        
        # 生成输出文件名
        date_str = datetime.datetime.now().strftime("%Y%m%d")
        safe_title = "".join(c if c.isalnum() else "_" for c in str(video_title))[:20]
        output_name = f"{video_type}_{date_str}_{safe_title}.mp4"
        output_path = str(DRAFTS_DIR / output_name)
        
        try:
            # 1. 生成视频
            print(f"  [1/5] 生成视频: {output_path}")
            generate_video(script_text, output_path)
            
            # 2. 发布到视频号
            print(f"  [2/5] 发布到视频号...")
            video_url = publish_to_video_account(output_path, record)
            
            if not video_url:
                print("  ⚠️ 视频号发布失败，记录状态更新")
                update_record(rid, {
                    "发布状态": "failed",
                    "错误信息": "视频号发布失败",
                    "视频文件路径": output_path,
                })
                # 仍上传云盘预览
                preview_url = create_public_link(output_path)
                send_upload_notification(video_title, output_path, preview_url, video_type, record, rid)
                continue
            
            # 3. 上传飞书云盘预览
            print(f"  [3/5] 上传飞书云盘预览...")
            preview_url = create_public_link(output_path)
            
            # 4. 更新多维表格
            print(f"  [4/5] 更新多维表格...")
            update_record(rid, {
                "发布状态": "published",
                "发布时间": datetime.datetime.now().isoformat(),
                "视频文件路径": output_path,
                "视频链接": preview_url,
                "视频号链接": video_url,
            })
            
            # 5. 通知波哥
            print(f"  [5/5] 发送飞书通知...")
            send_published_notification(video_title, output_path, preview_url, video_url, video_type)
            
            # 6. 移动文件到归档
            archived_path = str(ARCHIVED_DIR / output_name)
            shutil.move(output_path, archived_path)
            
            print(f"  ✅ 全流程完成！")
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"  ❌ 错误: {e}")
            try:
                update_record(rid, {
                    "发布状态": "failed",
                    "错误信息": str(e)
                })
            except Exception:
                pass


def process_unpublishing():
    """处理待下架的视频"""
    records = get_records_to_unpublish()
    
    if not records:
        print("没有待下架的视频")
        return
    
    print(f"找到 {len(records)} 条待下架记录")
    
    for record in records:
        record_id = record.get("record_id", {})
        fields = record.get("fields", {})
        
        if isinstance(record_id, dict):
            rid = record_id.get("text", "") or record_id.get("value", "")
        else:
            rid = str(record_id)
        
        print(f"\n处理下架: {rid}")
        
        try:
            # 1. 视频号下架
            success = unpublish_from_video_account(record)
            
            if success:
                # 2. 更新多维表格
                update_record(rid, {
                    "发布状态": "archived",
                    "下架操作时间": datetime.datetime.now().isoformat(),
                    "归档时间": datetime.datetime.now().isoformat(),
                })
                
                # 3. 移动文件
                video_path = fields.get("视频文件路径", "")
                if video_path and os.path.exists(video_path):
                    video_name = Path(video_path).name
                    shutil.move(video_path, str(ARCHIVED_DIR / video_name))
                
                print(f"  ✅ 下架完成")
            else:
                update_record(rid, {
                    "发布状态": "failed",
                    "错误信息": "下架操作失败"
                })
                
        except NotImplementedError as e:
            print(f"  ⚠️ {e}")
            update_record(rid, {
                "发布状态": "failed",
                "错误信息": str(e)
            })
        except Exception as e:
            print(f"  ❌ 错误: {e}")
            update_record(rid, {
                "发布状态": "failed",
                "错误信息": str(e)
            })


def main():
    print(f"[{datetime.datetime.now().isoformat()}] 视频自动发布 Cron 启动")
    
    # 处理待发布
    print("\n=== 处理待发布视频 ===")
    process_pending_videos()
    
    # 处理待下架
    print("\n=== 处理待下架视频 ===")
    process_unpublishing()
    
    print(f"\n[{datetime.datetime.now().isoformat()}] Cron 执行完成")


if __name__ == "__main__":
    main()
