#!/usr/bin/env python3
"""
深圳城市风格背景图生成器 v3
目标：亮度充足、视觉吸引、字幕区域清晰可读
"""
from PIL import Image, ImageDraw, ImageFont
import numpy as np
import os

WIDTH, HEIGHT = 1080, 1920


def create_bg(output_path):
    """生成深圳城市风格明亮背景"""
    font_path = "/System/Library/Fonts/STHeiti Medium.ttc"

    # ── 渐变天空背景（从顶部深蓝到底部浅橙紫） ──────────────
    img = Image.new("RGB", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(img)

    # 天空渐变：深蓝 → 紫色 → 橙红色 → 浅粉
    for y in range(HEIGHT):
        ratio = y / HEIGHT
        if ratio < 0.3:
            # 上部：深蓝到蓝紫
            t = ratio / 0.3
            r = int(10 + t * 40)
            g = int(20 + t * 30)
            b = int(60 + t * 80)
        elif ratio < 0.6:
            # 中部：蓝紫到橙红
            t = (ratio - 0.3) / 0.3
            r = int(50 + t * 180)
            g = int(50 + t * 80)
            b = int(140 - t * 60)
        elif ratio < 0.85:
            # 下部：橙红到浅粉
            t = (ratio - 0.6) / 0.25
            r = int(230 - t * 80)
            g = int(130 - t * 40)
            b = int(80 - t * 20)
        else:
            # 底部：浅粉白
            t = (ratio - 0.85) / 0.15
            r = int(150 + t * 80)
            g = int(90 + t * 60)
            b = int(60 + t * 80)
        draw.line([(0, y), (WIDTH, y)], fill=(r, g, b))

    # ── 远处城市天际线（暗色剪影，透明度混合） ─────────────
    # 创建用于天际线的临时图像
    sky_region = img.crop((0, 0, WIDTH, HEIGHT - 400))
    sky_arr = np.array(sky_region)
    skyline_base = HEIGHT - 450

    # 绘制多层次建筑剪影
    def draw_skyline(y_base, height_scale, color_base):
        buildings = []
        x = 0
        while x < WIDTH:
            w = 30 + (x * 7 % 50)
            h = int((100 + (x * 13 % 150)) * height_scale)
            buildings.append((x, y_base))
            buildings.append((x + w, y_base - h))
            x += w + 2
        buildings.append((WIDTH, y_base))
        # 用暗淡色块填充
        overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        pts = [(min(WIDTH-1, p[0]), min(HEIGHT-1, p[1])) for p in buildings]
        if pts:
            overlay_draw.polygon(pts, fill=(*color_base, 180))
        # 与原图合并
        img.paste(Image.alpha_composite(img.convert("RGBA"), overlay), (0, 0))

    # 第一层：远处高层建筑（深蓝灰）
    draw_skyline(HEIGHT - 300, 0.8, (20, 30, 60))

    # 第二层：中等建筑（中蓝）
    draw_skyline(HEIGHT - 220, 0.6, (15, 25, 55))

    # ── 顶部标题区域（半透明黑色确保标题可读） ───────────────
    title_overlay = Image.new("RGBA", (WIDTH, 180), (0, 0, 0, 160))
    img.paste(title_overlay, (0, 0), title_overlay)

    # ── 右下角装饰光晕（城市灯光效果） ─────────────────────
    glow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    # 右下橙色暖光
    for r in range(200, 0, -3):
        alpha = int(30 * (1 - r / 200))
        glow_draw.ellipse(
            [WIDTH - 300 - r, HEIGHT - 500 - r,
             WIDTH - 300 + r, HEIGHT - 500 + r],
            fill=(255, 120, 50, alpha)
        )
    # 左下蓝色冷光
    for r in range(150, 0, -3):
        alpha = int(25 * (1 - r / 150))
        glow_draw.ellipse(
            [100 - r, HEIGHT - 400 - r, 100 + r, HEIGHT - 400 + r],
            fill=(50, 100, 255, alpha)
        )
    img.paste(Image.alpha_composite(img.convert("RGBA"), glow), (0, 0))

    # ── 底部数据卡片区域（深色确保数据可读） ─────────────────
    card_y = HEIGHT - 430
    card_h = 370

    # 底部半透明遮罩
    card_overlay = Image.new("RGBA", (WIDTH, card_h + 30), (10, 15, 40, 220))
    img.paste(card_overlay, (0, card_y - 15), card_overlay)

    # ── 文字 ───────────────────────────────────────────────
    try:
        title_font = ImageFont.truetype(font_path, 44)
        sub_font = ImageFont.truetype(font_path, 30)
        num_font = ImageFont.truetype(font_path, 72)
        small_font = ImageFont.truetype(font_path, 26)
    except:
        title_font = sub_font = num_font = small_font = ImageFont.load_default()

    # 标题（白字）
    draw = ImageDraw.Draw(img)
    draw.text((40, 30), "深圳楼市每日成交", font=title_font, fill=(255, 255, 255))
    draw.text((40, 82), "数据驱动买房决策", font=sub_font, fill=(180, 200, 255))

    # ── 数据卡片 ───────────────────────────────────────────
    box_w = (WIDTH - 80) // 3
    data_y = card_y + 20

    # 数据1
    draw.rounded_rectangle([40, data_y, 40+box_w-10, data_y+130], radius=12, fill=(25, 45, 90))
    draw.text((55, data_y+10), "新房认购网签", font=small_font, fill=(140, 180, 255))
    draw.text((55, data_y+55), "90", font=num_font, fill=(255, 255, 255))
    draw.text((55, data_y+120), "套", font=small_font, fill=(140, 180, 255))

    # 数据2
    x2 = 40 + box_w
    draw.rounded_rectangle([x2, data_y, x2+box_w-10, data_y+130], radius=12, fill=(25, 45, 90))
    draw.text((x2+15, data_y+10), "现房购房合同", font=small_font, fill=(140, 180, 255))
    draw.text((x2+15, data_y+55), "71", font=num_font, fill=(255, 255, 255))
    draw.text((x2+15, data_y+120), "套", font=small_font, fill=(140, 180, 255))

    # 数据3
    x3 = 40 + box_w * 2
    draw.rounded_rectangle([x3, data_y, x3+box_w-10, data_y+130], radius=12, fill=(25, 45, 90))
    draw.text((x3+15, data_y+10), "二手房成交", font=small_font, fill=(140, 180, 255))
    draw.text((x3+15, data_y+55), "374", font=num_font, fill=(255, 255, 255))
    draw.text((x3+15, data_y+120), "套", font=small_font, fill=(140, 180, 255))

    # 第二行数据
    data_y2 = data_y + 155
    draw.rounded_rectangle([40, data_y2, WIDTH-40, data_y2+140], radius=12, fill=(20, 40, 85))
    draw.text((60, data_y2+10), "4月21日总成交", font=small_font, fill=(140, 180, 255))
    draw.text((60, data_y2+50), "535", font=num_font, fill=(255, 220, 60))
    draw.text((230, data_y2+70), "套", font=small_font, fill=(140, 180, 255))
    draw.text((320, data_y2+55), "4月累计 7731 套", font=sub_font, fill=(120, 220, 150))
    draw.text((320, data_y2+95), "环比上涨 +54.65%", font=small_font, fill=(100, 255, 150))

    # 保存
    img_rgb = img.convert("RGB")
    img_rgb.save(output_path)

    arr = np.array(img_rgb)
    brightness = arr.mean()
    print(f"背景图已生成: {output_path}, 亮度均值: {brightness:.1f}")


if __name__ == "__main__":
    create_bg("/Users/sam/video_factory/bg_shenzhen.png")
