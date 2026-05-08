#!/usr/bin/env python3
"""
生成深圳楼市日报文案，写入飞书多维表格（状态=待制作）

v2：框架固定 + 话术池轮换
  [钩子] → [数据] → [解读] → [互动]
  每段从话术池按规则选取，避免每天一模一样

数据来源：property_clawer 的 SQLite 数据库
  - ZJJ 数据优先（presale_signed, subsequent_signed）
  - fallback 到 opendata 新房总量

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
from typing import Optional, Dict, Any, Tuple

# ========== 路径配置 ==========
PROPERTY_DB = Path("/Users/sam/property_clawer/data/property.db")
CONFIG_PATH = Path("/Users/sam/Library/Application Support/video_factory/config.json")
CTA_LOG_PATH = Path("/Users/sam/Library/Application Support/video_factory/cta_log.json")
LARK_CLI = Path("/Users/sam/.npm-global/bin/lark-cli")

# 飞书表格
FEISHU_TABLE_ID = "tblHptO4dDJckuFF"  # 视频发布记录

TITLE_TEMPLATE = "深圳{month}月{day}日\n楼市行情"


# =============================================================
# 行情判断：近7日均量 + 分类
# =============================================================

def get_recent_avg(target_date: str, days: int = 7) -> float:
    """
    查 target_date 之前最近 N 天的日均成交（新房+二手）。
    跳过 target_date 当天，只算历史数据。
    """
    dt = datetime.date.fromisoformat(target_date)
    conn = sqlite3.connect(str(PROPERTY_DB))
    try:
        cur = conn.cursor()
        # 从 target_date-1 往前取 N 天
        dates = []
        for i in range(1, days + 1):
            d = dt - datetime.timedelta(days=i)
            dates.append(d.isoformat())

        placeholders = ",".join("?" for _ in dates)
        cur.execute(
            f"SELECT SUM(deal_count) FROM transaction_data "
            f"WHERE city_id=1 AND district_id!=5999 "
            f"AND report_date IN ({placeholders})",
            dates,
        )
        total = cur.fetchone()[0] or 0
        # 只算有数据的天数
        cur.execute(
            f"SELECT COUNT(DISTINCT report_date) FROM transaction_data "
            f"WHERE city_id=1 AND district_id!=5999 "
            f"AND report_date IN ({placeholders})",
            dates,
        )
        valid_days = cur.fetchone()[0] or 1
        return total / valid_days
    finally:
        conn.close()


def classify_market(total: int, avg: float) -> str:
    """根据当日总量 vs 近7日均量，返回行情分类"""
    if total == 0:
        return "zero"       # 0套，通常是周末
    if avg == 0:
        return "normal"     # 无历史数据
    ratio = total / avg
    if ratio > 1.3:
        return "surge"      # 放量
    elif ratio > 1.1:
        return "up"         # 小幅回升
    elif ratio > 0.7:
        return "normal"     # 平稳
    else:
        return "dip"        # 缩量


def is_weekend(target_date: str) -> bool:
    """判断目标日期是否为周六/周日"""
    dt = datetime.date.fromisoformat(target_date)
    return dt.weekday() >= 5


def is_monday(target_date: str) -> bool:
    dt = datetime.date.fromisoformat(target_date)
    return dt.weekday() == 0


def is_friday(target_date: str) -> bool:
    dt = datetime.date.fromisoformat(target_date)
    return dt.weekday() == 4


# =============================================================
# 话术池
# =============================================================

# ── 钩子池（8个，按场景选） ──

HOOK_POOL = {
    "monday": "过个周末，深圳一天只卖了{total}套，节后凉了？",
    "friday": "这周最后一天，深圳成交{total}套。整周数据你猜涨了还是跌了？",
    "month_start": "{month}月开局，深圳一天成交{total}套，是涨是跌？",
    "month_mid": "{month}月过半，深圳这个月卖了多少？昨天{total}套——",
    "month_end": "{month}月还剩几天，深圳这个月成交了多少？昨天{total}套——",
    "surge": "爆了！深圳昨天一天卖了{total}套，有人在抢跑",
    "dip": "深圳昨天只卖了{total}套，买房的人都在等什么？",
    "normal": "深圳昨天成交{total}套，现在买房是不是时机？",
}


def pick_hook(target_date: str, total: int, market: str) -> str:
    """
    按优先级选钩子：特定日期 > 数据特征 > 通用
    返回选中的话术（已填充数据）
    """
    dt = datetime.date.fromisoformat(target_date)

    # 周末/假期 0 套，走周末钩子
    if total == 0 and is_weekend(target_date):
        return f"周末不更新网签，想蹲周一数据的评论区扣1"

    if total == 0:
        return f"昨天深圳成交{total}套，数据还没更新，先看看趋势"

    month = dt.month
    day = dt.day

    # 优先级：周一 > 周五 > 月初 > 月中 > 月末 > 数据特征 > 普通
    if is_monday(target_date):
        key = "monday"
    elif is_friday(target_date):
        key = "friday"
    elif day <= 5:
        key = "month_start"
    elif 15 <= day <= 20:
        key = "month_mid"
    elif day >= 25:
        key = "month_end"
    elif market in HOOK_POOL:
        key = market
    else:
        key = "normal"

    hook = HOOK_POOL[key]
    return hook.format(total=total, month=month)


# ── 数据段（固定格式，数据每天变） ──

def build_data_section(rengou: int, esf: int, total: int,
                       cumulative: int, target_date: str) -> str:
    """数据播报段——格式固定，数据天然变化"""
    dt = datetime.date.fromisoformat(target_date)
    days_in_month = dt.day  # 当月已过天数
    avg_daily = cumulative // days_in_month if days_in_month > 0 else 0
    return (
        f"新房{rengou}套，二手房{esf}套，总共{total}套。"
        f"{dt.month}月累计{cumulative}套，日均{avg_daily}套。"
    )


# ── 解读池（5种，根据行情分类选） ──

INSIGHT_POOL = {
    "surge": "这个量比过去一周均值高了不少，有人在抢跑了",
    "up": "比前几天稍微热了一点，节后刚需在动了",
    "normal": "跟前几天差不多，买卖双方都在观望",
    "dip": "成交缩到近期低位了，观望的人越来越多，你也在犹豫吗？",
    "zero": "周末不更新网签，想看周一数据的蹲一下",
}


def pick_insight(market: str) -> str:
    return INSIGHT_POOL.get(market, "跟前几天差不多，市场还在横盘")


# ── 互动引导池（5个，文件轮换） ──

CTA_POOL = [
    "你觉得这个月能破2000套吗？评论区押一个",
    "评论区告诉我你关注哪个区，明天我单独拉数据",
    "正在看房的扣1，还在犹豫的扣2，我看看有多少人",
    "有人问我现在能不能买——评论区打「咨询」两个字，我帮你看看",
    "关注我，每天了解深圳最真实的成交数据",
]


def _load_cta_log() -> Dict[str, Any]:
    if CTA_LOG_PATH.exists():
        with open(CTA_LOG_PATH) as f:
            return json.load(f)
    return {"last_idx": -1, "last_date": "", "history": []}


def _save_cta_log(log: Dict[str, Any]):
    CTA_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CTA_LOG_PATH, "w") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


def pick_cta(target_date: str) -> str:
    """轮换选择互动引导，避免连续重复"""
    log = _load_cta_log()

    # 如果同一天已经选过，直接返回
    if log.get("last_date") == target_date and "last_idx" in log:
        idx = log["last_idx"]
        if 0 <= idx < len(CTA_POOL):
            return CTA_POOL[idx]

    last_idx = log.get("last_idx", -1)
    # 下一个编号，循环
    next_idx = (last_idx + 1) % len(CTA_POOL)

    log["last_idx"] = next_idx
    log["last_date"] = target_date
    log["history"] = (log.get("history", []) + [next_idx])[-50:]  # 保留最近50次
    _save_cta_log(log)
    return CTA_POOL[next_idx]


# =============================================================
# 数据库操作（不变）
# =============================================================

def get_connection():
    return sqlite3.connect(str(PROPERTY_DB))


def query_daily_data(target_date: str) -> Dict[str, Any]:
    conn = get_connection()
    try:
        cur = conn.cursor()
        result = {
            "new_total": 0,
            "esf_total": 0,
            "presale_signed": 0,
            "subsequent_signed": 0,
        }

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
            if ptype == 1:
                result["new_total"] = deal or 0
                result["presale_signed"] = presale or 0
                result["subsequent_signed"] = subsequent or 0
            elif ptype == 2:
                result["esf_total"] = deal or 0

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


# =============================================================
# 文案组装（替换旧的 COPY_TEMPLATE）
# =============================================================

def build_copy(target_date: str) -> Dict[str, Any]:
    dt = datetime.date.fromisoformat(target_date)
    month = dt.month
    day = dt.day

    data = query_daily_data(target_date)

    # 新房 = 预售 + 现售（ZJJ 优先）
    zjj_rengou = data["presale_signed"]
    zjj_xianshou = data["subsequent_signed"]

    if zjj_rengou > 0 or zjj_xianshou > 0:
        rengou = zjj_rengou + zjj_xianshou
    else:
        rengou = data["new_total"]

    esf = data["esf_total"]
    total = rengou + esf
    cumulative = data["cumulative"]

    # ── 行情判断 ──
    avg = get_recent_avg(target_date, days=7)
    market = classify_market(total, avg)

    # ── 4段式组装 ──
    hook = pick_hook(target_date, total, market)
    data_section = build_data_section(rengou, esf, total, cumulative, target_date)
    insight = pick_insight(market)
    cta = pick_cta(target_date)

    copy = f"{hook}\n\n{data_section}\n\n{insight}\n\n{cta}"

    title = TITLE_TEMPLATE.format(month=month, day=day)

    return {
        "title": title,
        "copy": copy,
        "date": target_date,
        "rengou": rengou,
        "xianshou": 0,
        "esf": esf,
        "total": total,
        "huanbi": "",
        "cumulative": cumulative,
        "data_source": "ZJJ" if zjj_rengou > 0 else "opendata",
        "market": market,
        "avg_7d": round(avg, 1),
    }


# =============================================================
# 飞书操作（不变）
# =============================================================

def _load_config():
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return json.load(f)
    return {}


def lark_cli(args: list) -> dict:
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
    base_token = _get_base_token()
    lark_cli([
        "base", "+record-delete",
        "--base-token", base_token,
        "--table-id", FEISHU_TABLE_ID,
        "--record-id", record_id,
        "--yes",
    ])


def upsert_record(copy_data: Dict[str, Any]) -> str:
    target_date = copy_data["date"]

    existing_ids = find_existing_record_ids(target_date)
    if existing_ids:
        print(f"   🗑 发现 {len(existing_ids)} 条旧记录，先删除...")
        for rid in existing_ids:
            delete_record(rid)

    title_for_desc = copy_data["title"].replace("\n", "")
    video_desc = (
        f"{title_for_desc} "
        "#深圳楼市 #深圳房产 #成交数据 #每日楼市 #深圳二手房 "
        "#深圳买房 #楼市分析 #买房 #深圳 #楼市"
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


# =============================================================
# 主流程
# =============================================================

def main(target_date: Optional[str] = None):
    if target_date is None:
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
    print(f"📌 行情：{data['market']}（近7日均量 {data['avg_7d']}）")
    print(f"📌 原始数据：rengou={data['rengou']}, esf={data['esf']}, total={data['total']}")
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
