from generate_video import build_subtitle_segments, split_text, cn_to_arabic, fmt_time

SCRIPT = (
    "深圳楼市成交数据来了！4月21日新房认购网签90套，"
    "现房购房合同网签71套；二手房成交374套，一手新房与二手房一共成交535套。"
    "4月累计成交7731套，环比上涨54.65%。自4月以来，一手房新批准预售0套，"
    "想买到称心如意的房子，一定要学会看数据，知行情。"
    "关注我，感知深圳楼市温度！"
)

segs = split_text(SCRIPT)
converted = [cn_to_arabic(s) for s in segs]
subs = build_subtitle_segments(converted, 36.1)

def fmt_ass(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds % 1) * 100)
    return f'{h}:{m:02d}:{s:02d}.{cs:02d}'

ass_lines = [
    '[Script Info]',
    'Title: Generated',
    'ScriptType: v4.00+',
    '',
    '[V4+ Styles]',
    'Format: Name, Fontname, Fontsize, PrimaryColour, BackColour, Bold, Alignment, MarginL, MarginR, MarginV',
    'Style: Default,STHeiti Medium,50,&H00FFFFFF,&H00000000,-1,2,20,20,20',
    '',
    '[Events]',
    'Format: Layer, Start, End, Style, Text',
]
for i, (s, e, txt) in enumerate(subs):
    txt_escaped = txt.replace('\\', '\\\\').replace('{', '\\{').replace('}', '\\}')
    ass_lines.append(f'Dialogue: 0,{fmt_ass(s)},{fmt_ass(e)},Default,,0,0,0,,{txt_escaped}')

with open('/Users/sam/Videos/subtitles.ass', 'w', encoding='utf-16') as f:
    f.write('\n'.join(ass_lines))

print('ASS written, testing ffmpeg...')

import subprocess, os
MP_DIR = '/Users/sam/Videos'
audio_video = os.path.join(MP_DIR, 'raw_video_audio.mp4')
output = os.path.join(MP_DIR, 'test_ass.mp4')
result = subprocess.run([
    'ffmpeg', '-y', '-i', audio_video,
    '-vf', f'ass={MP_DIR}/subtitles.ass',
    '-c:a', 'copy', output
], capture_output=True, text=True)

print('stdout:', result.stdout[-500:] if result.stdout else '')
print('stderr:', result.stderr[-500:] if result.stderr else '')
print('returncode:', result.returncode)
