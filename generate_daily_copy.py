#!/usr/bin/env python3
"""
生成深圳楼市日报文案，写入飞书多维表格（状态=待制作）

数据来源：property_clawer 的 SQLite 数据库
  - ZJJ 数据优先（presale_signed, subsequent_signed）
  - fallback 到 opendata 新房总量

文案模板（提问式）：
  深圳买房的注意了！{月}月{日}日深圳楼市成交数据刚刚出炉——
  新房{rengou}套，二手房{esf}套，总共{total}套！
  环比{huanbi}，当月累计{cumulative}套。
  买房卖房前一定要看这条视频，关注我，每天了解深圳楼市真实成交数据。

用法：
  python3 generate_daily_copy.py              # 生成今天日报
  python3 generate_daily_copy.py 2026-04-23  # 指定日期
"""

import sys
import os
import json
import sqlite3
import subprocess
import datetime
from pathlib import Path
from typing import Optional, Dict, Any

# ========== 路径配置 ==========
PROPERTY_DB = Path("/Users/sam/Workbuddy/property_clawer/data/property.db")
CONFIG_PATH = Path.home() / "Library/Application Support/video_factory/config.json"
LARK_CLI = Path.home() / ".npm-global/bin/lark-cli"

# 飞书表格
FEISHU_TABLE_ID = "tblHptO4dDJckuFF"  # 视频发布记录

# ========== 文案模板 ==========
COPY_TEMPLATE = (
    "深圳买房卖房的注意了！{month}月{day}日深圳楼市成交数据刚刚出炉——\n"
    "新房{rengou}套，二手房{esf}套，总共{total}套！\n"
    "当月累计{cumulative}套，环比{huanbi}。\n"
    "买房卖房前一定要看这条视频，关注我，每天了解深圳楼市真实成交数据。"
)

TITLE_TEMPLATE = "深圳{month}月{day}日\n楼市行情"

# ========== 数据库操作 ==========

def get_connection():
    return sqlite3.connect(str(PROPERTY_DB))


def query_daily_data(target_date: str) -> Dict[str, Any]:
    """
    查询指定日期的深圳楼市数据。
    优先 ZJJ（预售/现售网签），fallback 到 opendata。
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        result = {
            "new_total": 0,     # opendata 新房总量
            "esf_total": 0,    # 二手房
            "presale_signed": 0,   # ZJJ 预售合同网签
            "subsequent_signed": 0,  # ZJJ 现售合同网签
            "new_presale": 0,
        }

        # ── opendata：按类型汇总（排除全市行 district_id=5999）──────────────
        cur.execute("""
            SELECT property_type_id,
                   SUM(deal_count) AS deal,
                   SUM(presale_signed_count),
                   SUM(subsequent_signed_count)
            FROM transaction_data
            WHERE city_id=1 AND report_date=? AND district_id != 5999
            GROUP BY property_type_id
        """, (target_date,))
        rows = cur.fetchall()
        for r in rows:
            ptype, deal, presale, subsequent = r
            if ptype == 1:  # 新房
                result["new_total"] = deal or 0
                result["presale_signed"] = presale or 0
                result["subsequent_signed"] = subsequent or 0
            elif ptype == 2:  # 二手房
                result["esf_total"] = deal or 0

        # ── 当月累计（排除全市行）────────────────────────────────────────────
        year, month = target_date[:7].split("-")
        cur.execute("""
            SELECT SUM(deal_count) FROM transaction_data
            WHERE city_id=1 AND report_date LIKE ? AND district_id != 5999
        """, (f"{year}-{month}%",))
        row = cur.fetchone()
        result["cumulative"] = row[0] or 0 if row else 0

        return result
    finally:
        conn.close()


def format_huanbi(today: int, yesterday: int) -> str:
    """计算环比，返回文字描述"""
    if yesterday == 0:
        return "数据不足"
    ratio = today / yesterday
    if ratio > 1.005:
        return f"上涨{int((ratio - 1) * 100)}%"
    elif ratio < 0.995:
        return f"下跌{int((1 - ratio) * 100)}%"
    else:
        return "持平"


def get_cumulative(target_date: str) -> int:
    """
    获取指定日期的当月累计：从当月1日到指定日期的 deal_count 总和（排除全市行）。
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT SUM(deal_count) FROM transaction_data
            WHERE city_id=1 AND report_date LIKE ? AND district_id != 5999
        """, (target_date[:7] + "%",))
        row = cur.fetchone()
        return row[0] or 0 if row else 0
    finally:
        conn.close()


def calculate_huanbi(target_date: str) -> str:
    """
    计算当月累计环比：
    - 当月累计 = 月初到 target_date 的累计总量
    - 上月同期累计 = 上月同一天（如同是25日）的累计总量
    """
    dt = datetime.date.fromisoformat(target_date)

    current_cumulative = get_cumulative(target_date)

    # 获取上月同日
    last_month_dt = dt.replace(month=dt.month - 1) if dt.month > 1 else dt.replace(year=dt.year - 1, month=12)
    last_month_same_day = last_month_dt.isoformat()
    last_month_cumulative = get_cumulative(last_month_same_day)

    return format_huanbi(current_cumulative, last_month_cumulative)


def build_copy(target_date: str) -> Dict[str, Any]:
    """
    生成完整数据+文案
    """
    dt = datetime.date.fromisoformat(target_date)
    month = dt.month
    day = dt.day

    data = query_daily_data(target_date)

    # 新房总套数 = 预售合同网签 + 现售合同网签
    # （两套数据都来自 ZJJ，优先用 ZJJ，fallback 到 opendata）
    zjj_rengou = data["presale_signed"]
    zjj_xianshou = data["subsequent_signed"]

    if zjj_rengou > 0 or zjj_xianshou > 0:
        # ZJJ 数据优先：新房总数 = 预售 + 现售
        rengou = zjj_rengou + zjj_xianshou  # ← 预售+现售合并
        xianshou = 0  # 现售已合并到 rengou，不再单独列出
    else:
        # 无 ZJJ 数据，fallback 到 opendata
        rengou = data["new_total"]
        xianshou = 0

    esf = data["esf_total"]
    total = rengou + esf

    huanbi = calculate_huanbi(target_date)

    copy = COPY_TEMPLATE.format(
        month=month,
        day=day,
        rengou=rengou,
        esf=esf,
        total=total,
        huanbi=huanbi,
        cumulative=data["cumulative"],
    )

    title = TITLE_TEMPLATE.format(month=month, day=day)

    return {
        "title": title,
        "copy": copy,
        "date": target_date,
        "rengou": rengou,
        "xianshou": xianshou,
        "esf": esf,
        "total": total,
        "huanbi": huanbi,
        "cumulative": data["cumulative"],
        "data_source": "ZJJ" if zjj_rengou > 0 else "opendata",
    }


# ========== 飞书操作 ==========

def _load_config():
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return json.load(f)
    return {}


def lark_cli(args: list) -> dict:
    """执行 lark-cli，返回 JSON"""
    cmd = [str(LARK_CLI)] + args
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"lark-cli failed: {result.stderr}")
    return json.loads(result.stdout)


def _get_base_token() -> str:
    cfg = _load_config()
    base_token = cfg.get("FEISHU_BASE_TOKEN", os.environ.get("FEISHU_BASE_TOKEN", ""))
    if not base_token:
        raise RuntimeError("FEISHU_BASE_TOKEN not configured")
    return base_token


def find_existing_record_ids(target_date: str) -> list:
    """
    查找所有指定日期+日报类型的记录ID列表。
    返回 record_id 列表（可能为空）。
    """
    base_token = _get_base_token()

    result = lark_cli([
        "base", "+record-list",
        "--base-token", base_token,
        "--table-id", FEISHU_TABLE_ID,
        "--limit", "100",
    ])

    data = result.get("data", {})
    field_names = data.get("fields", []) or []
    record_ids = data.get("record_id_list", []) or []
    rows = data.get("data", []) or []

    try:
        title_idx = field_names.index("视频标题")
        vtype_idx = field_names.index("视频类型")
    except ValueError:
        return []

    # 生成目标日期对应的日报标题
    dt = datetime.date.fromisoformat(target_date)
    target_title = TITLE_TEMPLATE.format(month=dt.month, day=dt.day)

    matched = []
    for i, row in enumerate(rows):
        title = row[title_idx] if len(row) > title_idx else ""
        vtype = row[vtype_idx] if len(row) > vtype_idx else ""
        if isinstance(vtype, list):
            vtype = vtype[0] if vtype else ""

        if title == target_title and vtype == "日报":
            if i < len(record_ids):
                matched.append(record_ids[i])

    return matched


def delete_record(record_id: str) -> None:
    """删除指定记录"""
    base_token = _get_base_token()
    lark_cli([
        "base", "+record-delete",
        "--base-token", base_token,
        "--table-id", FEISHU_TABLE_ID,
        "--record-id", record_id,
        "--yes",
    ])


def upsert_record(copy_data: Dict[str, Any]) -> str:
    """
    插入新记录：先查重，有旧记录则全部删除，再插入新记录。
    返回 record_id。
    """
    target_date = copy_data["date"]

    # 查重（可能有多个重复）
    existing_ids = find_existing_record_ids(target_date)
    if existing_ids:
        print(f"   🗑 发现 {len(existing_ids)} 条旧记录，先删除...")
        for rid in existing_ids:
            delete_record(rid)

    # 构造字段
    title_for_desc = copy_data["title"].replace("\n", "")
    video_desc = (
        f"{title_for_desc} "
        "#深圳楼市 #深圳房产 #成交数据 #每日楼市 #深圳二手房 "
        "#深圳买房 #楼市分析 #买房 #深圳 #楼市 #"
    )

    fields = {
        "视频标题": copy_data["title"],
        "文案内容": copy_data["copy"],
        "发布状态": "待制作",
        "视频类型": "日报",
        "创建时间": datetime.datetime.now().isoformat(),
        "原创标志": True,
        "视频描述": video_desc,
    }

    # 插入
    base_token = _get_base_token()
    result = lark_cli([
        "base", "+record-upsert",
        "--base-token", base_token,
        "--table-id", FEISHU_TABLE_ID,
        "--json", json.dumps(fields, ensure_ascii=False),
    ])

    if not result.get("ok"):
        raise RuntimeError(f"创建记录失败: {result}")

    record_id = (result.get("data", {}) or {}).get("record", {}).get("record_id_list", [""])[0] or ""
    return record_id


def delete_record(record_id: str) -> None:
    """删除指定记录"""
    base_token = _get_base_token()
    lark_cli([
        "base", "+record-delete",
        "--base-token", base_token,
        "--table-id", FEISHU_TABLE_ID,
        "--record-id", record_id,
        "--yes",
    ])



# ========== 主流程 ==========

def main(target_date: Optional[str] = None):
    if target_date is None:
        # 默认查昨天（日报一般是早上发前一天的）
        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        target_date = yesterday.isoformat()

    print(f"📊 生成 {target_date} 深圳楼市日报文案...")

    try:
        data = build_copy(target_date)
    except Exception as e:
        print(f"❌ 查询数据失败: {e}")
        sys.exit(1)

    print(f"\n📝 文案预览：")
    print("=" * 50)
    print(data["copy"])
    print("=" * 50)
    print(f"\n📌 标题：{data['title']}")
    print(f"📌 原始数据：rengou={data['rengou']}, esf={data['esf']}, "
          f"xianshou={data['xianshou']}, total={data['total']}")
    print(f"📌 环比：{data['huanbi']}")
    print(f"📌 当月累计：{data['cumulative']}")
    print(f"📌 数据来源：{data['data_source']}")

    try:
        record_id = upsert_record(data)
        print(f"\n✅ 已写入飞书表格，记录ID：{record_id}")
    except Exception as e:
        print(f"\n❌ 写入飞书失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else None
    main(target)
