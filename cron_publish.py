#!/usr/bin/env python3
"""
视频自动发布 Cron 脚本
扫描多维表格，自动发布待发布视频，并支持定时下架

Base: 视频号发布记录
Table: 发布记录 (tblHptO4dDJckuFF)

状态流转（中文）：
  待制作 → 制作中 → 待下载 → 下载中 → 待发布 → 发布中 → 已发布 → 已归档

清理规则（按类型区分保留期）：
  日报 → 3天 → 归档
  周报 → 5天 → 直接删除
  月报 → 10天 → 归档
  专题 → 不处理
"""

import os
import sys
import json
import subprocess
import datetime
import shutil
import time
from pathlib import Path
from typing import Optional, List, Dict

# ========== 配置 ==========
# 飞书配置：从环境变量或配置文件读取（不要硬编码到代码里）
def _load_feishu_config():
    base_token = os.environ.get("FEISHU_BASE_TOKEN", "")
    table_id = os.environ.get("FEISHU_TABLE_ID", "tblHptO4dDJckuFF")
    # 配置文件放在 ~/Library/Application Support/video_factory/config.json
    config_path = Path.home() / "Library/Application Support/video_factory/config.json"
    if config_path.exists():
        with open(config_path) as f:
            cfg = json.load(f)
            base_token = base_token or cfg.get("FEISHU_BASE_TOKEN", "")
            table_id = cfg.get("FEISHU_TABLE_ID", table_id)
    if not base_token:
        raise RuntimeError("请设置环境变量 FEISHU_BASE_TOKEN 或 ~/Library/Application Support/video_factory/config.json")
    return base_token, table_id

FEISHU_BASE_TOKEN, FEISHU_TABLE_ID = _load_feishu_config()
FEISHU_CHAT_ID = "oc_e8b467f584d247feb1f6bf63bbe33d66"  # 团队工作报告群
LARK_CLI = os.path.expanduser("~/.npm-global/bin/lark-cli")

MP_DIR = Path.home() / "Videos"
DRAFTS_DIR = MP_DIR / "drafts"
ARCHIVED_DIR = MP_DIR / "archived"
VIDEO_FACTORY_DIR = Path("/Users/sam/video_factory")

# 确保目录存在
DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
ARCHIVED_DIR.mkdir(parents=True, exist_ok=True)

# ========== 常量 ==========
STATUS_PENDING_MAKE = "待制作"
STATUS_PENDING_PUBLISH = "待发布"
STATUS_PUBLISHING = "发布中"
STATUS_PUBLISHED = "已发布"
STATUS_ARCHIVED = "已归档"
# 失败状态（细分到具体环节）
STATUS_FAILED_MAKE = "生成失败"
STATUS_FAILED_PUBLISH = "发布失败"
STATUS_FAILED_UPLOAD = "上传失败"
# 按视频类型保留天数
RETENTION_DAYS = {
    "日报": 3,
    "周报": 5,
    "月报": 10,
}

# 超期后执行的动作：归档还是删除
# 周报直接删除，其他归档
RETENTION_ACTION = {
    "日报": "archive",
    "周报": "delete",
    "月报": "archive",
}

# ========== 飞书多维表格操作 ==========

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


def get_all_records():
    """获取所有记录"""
    result = lark_cli([
        "base", "+record-list",
        "--base-token", FEISHU_BASE_TOKEN,
        "--table-id", FEISHU_TABLE_ID,
        "--limit", "500"
    ])
    return parse_records_response(result)


def get_records_by_status(status_name: str):
    """获取指定状态的记录"""
    all_records = get_all_records()
    return [r for r in all_records if _get_status_name(r["fields"]) == status_name]


def _get_status_name(fields: dict) -> str:
    """从字段中提取状态名称（兼容中英文）"""
    status = fields.get("发布状态", [])
    if isinstance(status, list):
        return status[0] if status else ""
    if isinstance(status, dict):
        return status.get("name", "")
    return str(status) if status else ""


def _get_video_type(fields: dict) -> str:
    """从字段中提取视频类型"""
    vt = fields.get("视频类型", [])
    if isinstance(vt, list):
        return vt[0] if vt else ""
    if isinstance(vt, dict):
        return vt.get("name", "")
    return str(vt) if vt else ""


def _get_record_id(record: dict) -> str:
    """从记录中提取 record_id"""
    record_id = record.get("record_id", {})
    if isinstance(record_id, dict):
        return record_id.get("text", "") or record_id.get("value", "") or ""
    return str(record_id) if record_id else ""


def _get_field_value(fields: dict, key: str) -> str:
    """从字段中提取文本值"""
    val = fields.get(key, [])
    if isinstance(val, list):
        return val[0] if val else ""
    if isinstance(val, dict):
        return val.get("name", "")
    return str(val) if val else ""


def _parse_datetime(val: str) -> Optional[datetime.datetime]:
    """解析飞书 datetime 字符串为本地时间"""
    if not val:
        return None
    try:
        dt = datetime.datetime.fromisoformat(val.replace("Z", "+00:00"))
        return dt.astimezone().replace(tzinfo=None)
    except Exception:
        return None


def update_record_status(record_id: str, status: str, extra_fields: dict = None):
    """更新记录状态 + 附加字段"""
    updates = {"发布状态": status}
    if extra_fields:
        updates.update(extra_fields)
    result = lark_cli([
        "base", "+record-upsert",
        "--base-token", FEISHU_BASE_TOKEN,
        "--table-id", FEISHU_TABLE_ID,
        "--record-id", record_id,
        "--json", json.dumps(updates, ensure_ascii=False)
    ])
    if not result.get("ok"):
        print(f"  ⚠️ 更新记录失败 {record_id}: {result}")
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

    # 视频号下架自动化尚未实现，登录视频号后台手动下架
    # 后续可基于 publish_to_video_account.py 的 Playwright 自动化扩展
    print("  ⚠️ 视频号下架自动化尚未实现，请在视频号后台手动下架")
    return False


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

def process_video_lifecycle():
    """处理视频生命周期（从待制作到已发布）
    
    状态流转：
      待制作 → 制作中 → 待下载 → 下载中 → 待发布 → 发布中 → 已发布
    
    每个步骤之间更新表格状态，确保状态全程可追踪。
    """
    print("\n=== 1. 处理 待制作 视频（生成视频）===")
    records = get_records_by_status(STATUS_PENDING_MAKE)
    if not records:
        print("  没有待制作的视频")
    else:
        print(f"  找到 {len(records)} 条待制作记录")
        for record in records:
            rid = _get_record_id(record)
            fields = record["fields"]
            video_title = _get_field_value(fields, "视频标题")
            script_text = _get_field_value(fields, "文案内容")
            
            if not script_text:
                print(f"  ⚠️ [{rid}] 文案内容为空，跳过")
                update_record_status(rid, STATUS_FAILED_MAKE, {"错误信息": "文案内容为空"})
                continue
            
            print(f"\n  处理记录: {rid} | {video_title}")
            
            # ① 待制作 → 制作中
            update_record_status(rid, "制作中")
            print(f"  [1/4] 状态: 待制作 → 制作中")
            
            # ② 调用本地视频生成（MoneyPrinterV2）
            try:
                date_str = datetime.datetime.now().strftime("%Y%m%d")
                safe_title = "".join(c if c.isalnum() else "_" for c in video_title)[:20]
                video_type = _get_video_type(fields) or "日报"
                output_name = f"{video_type}_{date_str}_{safe_title}.mp4"
                output_path = str(DRAFTS_DIR / output_name)
                
                print(f"  [2/4] 生成视频中: {output_path}")
                generate_video(script_text, output_path)
                print(f"  [2/4] ✅ 视频生成完成")
            except Exception as e:
                print(f"  [2/4] ❌ 生成失败: {e}")
                update_record_status(rid, STATUS_FAILED_MAKE, {"错误信息": f"视频生成失败: {e}"})
                continue
            
            # ③ 制作中 → 待下载（生成完成，等下载；但本地生成无需下载）
            update_record_status(rid, "待下载")
            print(f"  [3/4] 状态: 制作中 → 待下载")
            
            # ④ 待下载 → 下载中 → 待发布（本地文件直接到位）
            update_record_status(rid, "下载中")
            time.sleep(1)
            update_record_status(rid, STATUS_PENDING_PUBLISH, {
                "视频文件路径": output_path,
            })
            print(f"  [4/4] 状态: 下载中 → 待发布 ✅")
            print(f"  文件: {output_path}")
    
    print("\n=== 2. 处理 待发布 视频（发布到视频号）===")
    records = get_records_by_status(STATUS_PENDING_PUBLISH)
    if not records:
        print("  没有待发布的视频")
    else:
        print(f"  找到 {len(records)} 条待发布记录")
        for record in records:
            rid = _get_record_id(record)
            fields = record["fields"]
            video_title = _get_field_value(fields, "视频标题")
            video_path = _get_field_value(fields, "视频文件路径")
            
            print(f"\n  处理记录: {rid} | {video_title}")
            
            if not video_path or not os.path.exists(video_path):
                print(f"  ⚠️ 视频文件不存在: {video_path}")
                update_record_status(rid, STATUS_FAILED_MAKE, {"错误信息": f"视频文件不存在: {video_path}"})
                continue
            
            # ⑤ 待发布 → 发布中
            update_record_status(rid, STATUS_PUBLISHING)
            print(f"  [5/7] 状态: 待发布 → 发布中")
            
            # ⑥ 发布到视频号
            try:
                print(f"  [6/7] 发布到视频号...")
                video_url = publish_to_video_account(video_path, record)
                
                if not video_url:
                    print(f"  [6/7] ⚠️ 视频号发布失败（可能未登录）")
                    update_record_status(rid, STATUS_PENDING_PUBLISH, {
                        "错误信息": "视频号发布失败，请检查登录状态"
                    })
                    # 仍上传云盘预览
                    preview_url = create_public_link(video_path)
                    send_upload_notification(
                        video_title, video_path, preview_url,
                        _get_video_type(fields), record, rid
                    )
                    continue
                    
                print(f"  [6/7] ✅ 视频号发布成功: {video_url}")
            except Exception as e:
                print(f"  [6/7] ❌ 发布异常: {e}")
                update_record_status(rid, STATUS_FAILED_PUBLISH, {"错误信息": str(e)})
                continue
            
            # ⑦ 发布中 → 已发布
            try:
                print(f"  [7/7] 上传飞书云盘...")
                preview_url = create_public_link(video_path)
                
                now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                update_record_status(rid, STATUS_PUBLISHED, {
                    "发布时间": now,
                    "视频号链接": video_url,
                    "视频链接": preview_url,
                })
                print(f"  [7/7] 状态: 发布中 → 已发布 ✅")
                
                # 通知波哥
                send_published_notification(
                    video_title, video_path, preview_url,
                    video_url, _get_video_type(fields)
                )
                
                # 文件保留在原位（云盘已有预览链接），不需要移动
                    
            except Exception as e:
                print(f"  [7/7] ❌ 后处理失败: {e}")
                update_record_status(rid, STATUS_FAILED_UPLOAD, {"错误信息": str(e)})


def process_cleanup():
    """处理过期视频自动归档/删除
    
    规则：已发布视频按类型保留天数，超期后执行对应动作
    - 日报：3天 → 归档
    - 周报：5天 → 直接删除
    - 月报：10天 → 归档
    注意：只处理已发布状态的视频，专题类不处理
    """
    
    print("\n=== 3. 处理过期视频自动归档/删除 ===")
    all_records = get_all_records()
    
    expired = []
    for record in all_records:
        fields = record["fields"]
        status = _get_status_name(fields)
        video_type = _get_video_type(fields)
        pub_time_str = _get_field_value(fields, "发布时间")
        
        if status != STATUS_PUBLISHED:
            continue
        
        retention = RETENTION_DAYS.get(video_type)
        if not retention:
            continue  # 专题类不处理
        
        pub_time = _parse_datetime(pub_time_str)
        cutoff = datetime.datetime.now() - datetime.timedelta(days=retention)
        if pub_time and pub_time < cutoff:
            action = RETENTION_ACTION.get(video_type, "archive")
            expired.append((record, pub_time, video_type, retention, action))
    
    if not expired:
        print(f"  没有需要处理的过期视频")
        return
    
    print(f"  找到 {len(expired)} 条过期视频待处理:")
    for record, pub_time, video_type, retention, action in expired:
        rid = _get_record_id(record)
        fields = record["fields"]
        title = _get_field_value(fields, "视频标题")
        video_path = _get_field_value(fields, "视频文件路径")
        pub_time_str = _get_field_value(fields, "发布时间")
        days_old = (datetime.datetime.now() - pub_time).days
        action_desc = "删除" if action == "delete" else "归档"
        print(f"  • {title} | {video_type} | 发布于 {pub_time_str[:10]}（{days_old}天前）→ {action_desc}")
        
        # 视频号下架（目前需要手动）
        print(f"    → 视频号后台下架（需手动）: https://channels.weixin.qq.com")
        
        # 更新表格状态
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        update_record_status(rid, STATUS_ARCHIVED, {
            "下架时间": now_str,
            "下架操作时间": now_str,
        })
        
        # 处理本地文件
        if video_path and os.path.exists(video_path):
            if action == "delete":
                try:
                    os.remove(video_path)
                    print(f"    → ✅ 文件已删除: {video_path}")
                except Exception as e:
                    print(f"    → ⚠️ 文件删除失败: {e}")
            else:
                archived_path = str(ARCHIVED_DIR / Path(video_path).name)
                try:
                    shutil.move(video_path, archived_path)
                    print(f"    → 文件已归档: {archived_path}")
                except Exception as e:
                    print(f"    → ⚠️ 文件移动失败: {e}")
        else:
            print(f"    → 本地文件不存在")
        
        print(f"    → ✅ 状态已更新为 已归档")
        time.sleep(0.5)


def main():
    rules = " / ".join([f"{k}={v}天({'删除' if RETENTION_ACTION.get(k)=='delete' else '归档'})" for k, v in RETENTION_DAYS.items()])
    print(f"[{datetime.datetime.now().isoformat()}] 视频自动发布 Cron 启动")
    print(f"清理规则：{rules}")
    
    try:
        # 处理视频生命周期（待制作 → 已发布）
        process_video_lifecycle()
        
        # 处理过期视频自动归档/删除
        process_cleanup()
    except Exception as e:
        print(f"\n❌ Cron 执行异常: {e}")
        raise
    
    print(f"\n[{datetime.datetime.now().isoformat()}] Cron 执行完成")


if __name__ == "__main__":
    main()
