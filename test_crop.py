from PIL import Image, ImageDraw, ImageFont
import numpy as np

FONT = '/System/Library/Fonts/STHeiti Medium.ttc'
text = '深圳樓市成交數據來了'
f = ImageFont.truetype(FONT, 72)

img = Image.new('RGBA', (980, 120), (0,0,0,0))
d = ImageDraw.Draw(img)
x, y = 50, 30
d.text((x, y), text, font=f, fill=(0,0,0,255))  # black stroke
d.text((x, y), text, font=f, fill=(255,255,255,255))  # white fill

bbox = d.textbbox((0, 0), text, font=f)
print(f'bbox (from 0,0): {bbox}')

# Test with different paddings
for pad in [10, 20, 30]:
    cropped = img.crop((
        max(0, bbox[0]-pad), max(0, bbox[1]-pad),
        min(980, bbox[2]+pad), min(120, bbox[3]+pad)
    ))
    arr = np.array(cropped)
    w = ((arr[:,:,0]>200) & (arr[:,:,3]>50)).sum()
    b = ((arr[:,:,0]<50) & (arr[:,:,3]>50)).sum()
    print(f'padding={pad}: white={w}, black={b}, cropped_size={cropped.size}')

# Save test PNGs
for pad in [10, 30]:
    cropped = img.crop((
        max(0, bbox[0]-pad), max(0, bbox[1]-pad),
        min(980, bbox[2]+pad), min(120, bbox[3]+pad)
    ))
    cropped.save(f'/Users/sam/Videos/test_crop_pad{pad}.png')
print('Saved test PNGs')
