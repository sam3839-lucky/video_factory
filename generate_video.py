#!/usr/bin/env python3
"""
深圳楼市成交日报 - 视频生成脚本 v7
数字人窗口（中间嵌入）+ 字幕叠加
数字转换：只有后面跟着量词才转阿拉伯数字
"""
import sys, os, subprocess, re

os.environ["IMAGEMAGICK_BINARY"] = "/opt/homebrew/bin/magick"

ROOT_DIR = "/Users/sam/MoneyPrinterV2"
MP_DIR = os.path.expanduser("~/Videos")
os.makedirs(MP_DIR, exist_ok=True)

SCRIPT = (
    "深圳楼市成交数据来了！4月21日新房认购网签90套，"
    "现房购房合同网签71套；二手房成交374套，一手新房与二手房一共成交535套。"
    "4月累计成交7731套，环比上涨54.65%。自4月以来，一手房新批准预售0套，"
    "想买到称心如意的房子，一定要学会看数据，知行情。"
    "关注我，感知深圳楼市温度！"
)

WIDTH, HEIGHT = 1080, 1920
FPS = 30
FONT_PATH = "/System/Library/Fonts/STHeiti Medium.ttc"
SUB_Y = 920  # 字幕位置（ffmpeg overlay坐标）

# 数字人视频窗口（高占一半，款90%）
DV_W = 972
DV_H = 960
DV_X = (WIDTH - DV_W) // 2   # 54
DV_Y = (HEIGHT - DV_H) // 2  # 480


def fmt_time(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def _parse_cn_str(s):
    """解析纯中文数字字符串，返回整数值"""
    if not s:
        return 0
    cn_digit = {'零':0,'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'〇':0}
    cn_unit = {'億':100000000,'亿':100000000,'萬':10000,'万':10000,
               '千':1000,'仟':1000,'百':100,'佰':100,'十':10,'拾':10}
    result = 0
    prev = 0
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        if ch in cn_digit:
            prev = prev * 10 + cn_digit[ch]
            i += 1
        elif ch in cn_unit:
            v = cn_unit[ch]
            if prev > 0:
                result += prev * v
                prev = 0
            else:
                result += v
            i += 1
        else:
            i += 1
    return result + prev


def cn_to_arabic(text):
    """
    只有后面跟着量词/单位的中文数字才转阿拉伯数字
    量词：套、次、户、人、元、月、年、倍、%、亿、万、千、百
    百分比：百分之X → X%
    小数：三点五 → 3.5
    """
    # 百分比
    text = re.sub(r'百分之([零一二三四五六七八九〇十拾百千万億万]+)[點点]([零一二三四五六七八九〇十拾百千万億万]+)',
                   lambda m: f"{_parse_cn_str(m.group(1))}.{_parse_cn_str(m.group(2))}%", text)
    text = re.sub(r'百分之([零一二三四五六七八九〇十拾百千万億万]+)',
                   lambda m: f"{_parse_cn_str(m.group(1))}%", text)
    # 数字+量词
    text = re.sub(
        r'([零一二三四五六七八九〇十拾百千万億万仟佰]+)([套次户人元月年倍%％亿万千百])',
        lambda m: str(_parse_cn_str(m.group(1))) + m.group(2),
        text
    )
    # 小数
    text = re.sub(r'([零一二三四五六七八九〇十拾]+)[點点]([零一二三四五六七八九〇十拾]+)',
                   lambda m: f"{_parse_cn_str(m.group(1))}.{_parse_cn_str(m.group(2))}", text)
    return text


def generate_tts(text):
    aiff = os.path.join(MP_DIR, "temp_tts.aiff")
    wav = os.path.join(MP_DIR, "audio.wav")
    for f in [aiff, wav]:
        if os.path.exists(f):
            os.remove(f)
    subprocess.run(["say", "-v", "Tingting", "-o", aiff, text], check=True)
    subprocess.run(["ffmpeg", "-y", "-i", aiff, "-ar", "44100", "-ac", "2", wav],
                   check=True, capture_output=True)
    os.remove(aiff)
    return wav


def get_audio_duration(wav_path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", wav_path],
        capture_output=True, text=True, check=True
    )
    return float(result.stdout.strip())


def split_text(text, max_chars=16):
    sentences = re.split(r'([。；，、！？\n]+)', text)
    segments = []
    current = ""
    for i in range(0, len(sentences), 2):
        part = sentences[i]
        punct = sentences[i+1] if i+1 < len(sentences) else ""
        combined = current + part + punct
        if len(combined) > max_chars and current:
            segments.append(current.strip())
            current = part + punct
        else:
            current = combined
    if current.strip():
        segments.append(current.strip())
    return segments


def render_subtitle_image(text, width=1080, font_path=None):
    """用PIL渲染字幕为PNG底片（黑底白字描边）"""
    from PIL import Image, ImageDraw, ImageFont
    if font_path is None:
        font_path = FONT_PATH
    font_size = 50
    line_h = 60
    margin_x = 40
    max_w = width - margin_x * 2

    try:
        font = ImageFont.truetype(font_path, font_size)
    except Exception:
        font = ImageFont.load_default()

    # 切行
    lines = []
    current_line = ""
    for ch in text:
        test = current_line + ch
        bbox = font.getbbox(test)
        if bbox[2] - bbox[0] <= max_w:
            current_line = test
        else:
            if current_line:
                lines.append(current_line)
            current_line = ch
    if current_line:
        lines.append(current_line)

    img_h = len(lines) * line_h + 20
    img = Image.new('RGBA', (width, img_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        bbox = font.getbbox(line)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        x = (width - text_w) // 2
        y = i * line_h + (line_h - text_h) // 2 + 5
        # 黑色描边 + 白色填充
        for dx in [-2, 2, 0, 0]:
            for dy in [-2, 2, 0, 0]:
                if dx == 0 and dy == 0:
                    draw.text((x, y), line, font=font, fill=(255, 255, 255, 255))
                else:
                    draw.text((x, y), line, font=font, fill=(0, 0, 0, 200))
    return img


def build_subtitle_segments(segments, audio_duration):
    total = len(segments)
    avg_time = audio_duration / total
    subs = []
    for i, seg in enumerate(segments):
        start = i * avg_time + 0.2
        end = (i + 1) * avg_time - 0.1
        if i == total - 1:
            end = audio_duration
        subs.append((start, end, seg))
    return subs


def make_bg_with_avatar():
    from PIL import Image, ImageDraw
    bg_path = os.path.join(MP_DIR, "bg_with_avatar.png")
    bg = Image.new('RGB', (WIDTH, HEIGHT), '#1a1a2e')
    draw = ImageDraw.Draw(bg)
    for y in range(0, 300, 80):
        draw.rectangle([0, y, WIDTH, y+40], fill='#16213e')
    # 数字人窗口占位
    dv = Image.new('RGB', (DV_W, DV_H), '#6a0dad')
    dv_draw = ImageDraw.Draw(dv)
    dv_draw.rectangle([0, 0, DV_W-1, DV_H-1], outline='#ffffff', width=4)
    dv_draw.text((DV_W//2 - 150, DV_H//2 - 20), "数字人视频区域", fill='white')
    bg.paste(dv, (DV_X, DV_Y))
    bg.save(bg_path)
    return bg_path


def composite_video(bg_path, output_path, duration):
    vf = f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2,fps={FPS}"
    subprocess.run([
        "ffmpeg", "-y",
        "-loop", "1", "-i", bg_path,
        "-t", str(duration),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast",
        "-pix_fmt", "yuv420p",
        output_path
    ], check=True, capture_output=True)


def add_audio(video_path, audio_path, output_path):
    subprocess.run([
        "ffmpeg", "-y",
        "-i", video_path, "-i", audio_path,
        "-c:v", "copy", "-c:a", "aac",
        "-shortest",
        output_path
    ], check=True, capture_output=True)


def overlay_subtitles_simple(video_path, subs, output_path):
    """
    用PIL逐帧叠加字幕：提取帧 → 叠加PNG → 重新合成视频
    """
    if not subs:
        subprocess.run(["cp", video_path, output_path])
        return

    import tempfile
    frames_dir = tempfile.mkdtemp(prefix="video_frames_")
    try:
        # [1] 把视频每一帧提取成PNG
        print(f"  提取帧到 {frames_dir} ...")
        subprocess.run([
            "ffmpeg", "-y",
            "-i", video_path,
            "-vf", f"fps={FPS},scale={WIDTH}:{HEIGHT}",
            "-q:v", "2",
            os.path.join(frames_dir, "frame_%04d.png")
        ], check=True, capture_output=True)

        # [2] 生成字幕PNG（黑色背景透明字）
        sub_pngs = []
        for idx, (s, e, txt) in enumerate(subs):
            img = render_subtitle_image(txt, WIDTH)
            p = os.path.join(frames_dir, f"sub_{idx:02d}.png")
            img.save(p)
            sub_pngs.append((s, e, p))
        frame_count = len([f for f in os.listdir(frames_dir) if f.startswith("frame_")])
        print(f"  共 {frame_count} 帧, {len(sub_pngs)} 条字幕")

        # [3] 逐帧叠加字幕
        print("  逐帧叠加字幕...")
        from PIL import Image
        done = 0
        for i in range(1, frame_count + 1):
            frame_path = os.path.join(frames_dir, f"frame_{i:04d}.png")
            frame = Image.open(frame_path).convert("RGBA")
            # 找当前帧对应的字幕
            t = (i - 1) / FPS
            for s, e, sub_png_path in sub_pngs:
                if s <= t < e:
                    sub = Image.open(sub_png_path).convert("RGBA")
                    # 字幕贴到正确位置
                    sw = frame.width
                    sx = (sw - sub.width) // 2
                    frame.paste(sub, (sx, SUB_Y), sub)
                    break
            # 保存回原路径（覆盖原帧）
            out_frame = frame.convert("RGB")
            out_frame.save(frame_path, "PNG", quality=95)
            done += 1
            if done % 100 == 0:
                print(f"  已处理 {done}/{frame_count} 帧")

        # [4] 重新合成视频
        print("  重新合成视频...")
        temp_video = os.path.join(frames_dir, "video_with_subs.mp4")
        subprocess.run([
            "ffmpeg", "-y",
            "-framerate", str(FPS),
            "-i", os.path.join(frames_dir, "frame_%04d.png"),
            "-i", video_path,
            "-map", "0:v", "-map", "1:a",
            "-c:v", "libx264", "-preset", "fast",
            "-pix_fmt", "yuv420p",
            "-shortest",
            temp_video
        ], check=True, capture_output=True)

        # [5] 移到最终路径
        subprocess.run(["mv", temp_video, output_path])
        print(f"  完成字幕叠加: {output_path}")

    finally:
        # 清理临时帧文件
        import shutil
        shutil.rmtree(frames_dir, ignore_errors=True)


def main():
    print("[1/5] 生成TTS...")
    wav_path = generate_tts(SCRIPT)
    duration = get_audio_duration(wav_path)
    print(f"  音频时长: {duration:.1f}s")

    print("[2/5] 切分字幕...")
    raw_segments = split_text(SCRIPT)
    converted = [cn_to_arabic(seg) for seg in raw_segments]
    print(f"  原文本: {raw_segments}")
    print(f"  转换后: {converted}")
    subs = build_subtitle_segments(converted, duration)
    print(f"  字幕段数: {len(subs)}")

    print("[3/5] 生成背景+数字人窗口...")
    bg_path = make_bg_with_avatar()

    print("[4/5] 生成视频+混音频...")
    raw_video = os.path.join(MP_DIR, "raw_video.mp4")
    composite_video(bg_path, raw_video, duration)
    audio_video = os.path.join(MP_DIR, "raw_video_audio.mp4")
    add_audio(raw_video, wav_path, audio_video)

    print("[5/5] 叠加字幕...")
    final = os.path.join(MP_DIR, "shenzhen_realestate.mp4")
    overlay_subtitles_simple(audio_video, subs, final)
    print(f"\n完成: {final}")


if __name__ == "__main__":
    main()
