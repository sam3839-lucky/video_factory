#!/usr/bin/env python3
"""修复飞书视频描述字段末尾多余的 #"""
import subprocess, json, time

record_ids = [
    ("recviQWAlop2QY", "深圳5月1日楼市行情"),
    ("recviQWBaBqGPf", "深圳5月2日楼市行情"),
    ("recviQWBY8x9Ce", "深圳5月3日楼市行情"),
    ("recviQWCSamWpA", "深圳5月4日楼市行情"),
    ("recviQWDFKyVy4", "深圳5月5日楼市行情"),
    ("recviSKdhXqyQ2", "深圳5月6日楼市行情"),
    ("recviYGb37RdoL", "深圳5月7日楼市行情"),
]

BASE_TOKEN = "XX8abIKw7a9GwBsVt57crlbHnOe"
TABLE_ID = "tblHptO4dDJckuFF"

for rid, title in record_ids:
    new_desc = f"{title} #深圳楼市 #深圳房产 #成交数据 #每日楼市 #深圳二手房 #深圳买房 #楼市分析 #买房 #深圳 #楼市"
    
    cmd = [
        "lark-cli", "base", "+record-upsert",
        "--base-token", BASE_TOKEN,
        "--table-id", TABLE_ID,
        "--record-id", rid,
        "--json", json.dumps({"视频描述": new_desc}, ensure_ascii=False),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    data = json.loads(result.stdout)
    if data.get("ok"):
        print(f"✅ {title}: 已修复")
    else:
        print(f"❌ {title}: {data.get('error', {}).get('message', 'unknown')}")
    time.sleep(0.5)

print("\n全部完成!")
