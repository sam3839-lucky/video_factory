from PIL import Image, ImageDraw, ImageFont
import numpy as np

FONT = '/System/Library/Fonts/STHeiti Medium.ttc'
text = '深圳樓市成交數據來了'
f = ImageFont.truetype(FONT, 72)

results = []

# Method 1: fill then stroke (fill white on top of black)
img1 = Image.new('RGBA', (980, 120), (0,0,0,0))
d1 = ImageDraw.Draw(img1)
d1.text((50,30), text, font=f, fill=(255,255,255,255))
d1.text((50,30), text, font=f, fill=(0,0,0,255))
arr1 = np.array(img1)
w1 = ((arr1[:,:,0]>200) & (arr1[:,:,3]>50)).sum()
b1 = ((arr1[:,:,0]<50) & (arr1[:,:,3]>50)).sum()
results.append(f'fill_then_stroke: white={w1}, black={b1}')

# Method 2: stroke then fill
img2 = Image.new('RGBA', (980, 120), (0,0,0,0))
d2 = ImageDraw.Draw(img2)
d2.text((50,30), text, font=f, fill=(0,0,0,255))
d2.text((50,30), text, font=f, fill=(255,255,255,255))
arr2 = np.array(img2)
w2 = ((arr2[:,:,0]>200) & (arr2[:,:,3]>50)).sum()
b2 = ((arr2[:,:,0]<50) & (arr2[:,:,3]>50)).sum()
results.append(f'stroke_then_fill: white={w2}, black={b2}')

# Method 3: stroke param
img3 = Image.new('RGBA', (980, 120), (0,0,0,0))
d3 = ImageDraw.Draw(img3)
d3.text((50,30), text, font=f, fill=(255,255,255,255), stroke_fill=(0,0,0,255), stroke_width=3)
arr3 = np.array(img3)
w3 = ((arr3[:,:,0]>200) & (arr3[:,:,3]>50)).sum()
b3 = ((arr3[:,:,0]<50) & (arr3[:,:,3]>50)).sum()
results.append(f'stroke_param: white={w3}, black={b3}')

for r in results:
    print(r)
