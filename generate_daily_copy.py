#!/usr/bin/env python3
"""
深圳楼市日报文案生成 → 飞书多维表格

thin wrapper：核心逻辑在 property_clawer V2
  /Users/sam/Projects/property_clawer/app/services/daily_copy_generator.py

用法不变：
  python3 generate_daily_copy.py              # 昨天
  python3 generate_daily_copy.py 2026-05-28   # 指定日期
"""
import sys
import os

_PC_DIR = "/Users/sam/Projects/property_clawer"
if _PC_DIR not in sys.path:
    sys.path.insert(0, _PC_DIR)

from app.services.daily_copy_generator import (
    generate_daily_copy, map_video_copy_data, write_to_feishu,
)

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else None
    result = generate_daily_copy(target)
    cumulative_raw = result.pop('_cumulative_raw', {})
    result.pop('_opendata', None)
    result.pop('_contract', None)
    copy_data = map_video_copy_data(result, cumulative_raw)
    record_id = write_to_feishu(copy_data)
    print(f"record_id: {record_id}")
    if record_id:
        print(f"title: {copy_data['title']}")
        print(f"copy: {copy_data['copy']}")
