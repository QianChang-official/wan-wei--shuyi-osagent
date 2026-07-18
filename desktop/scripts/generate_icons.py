#!/usr/bin/env python3
"""生成麒麟桌面应用所需的多尺寸 PNG 图标。
调用：python3 scripts/generate_icons.py
输出：desktop/build/icons/{16,24,32,48,64,128,256,512}x{...}.png
"""
import math
from pathlib import Path
from PIL import Image, ImageDraw

OUT_DIR = Path(__file__).resolve().parent.parent / "build" / "icons"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SIZES = [16, 24, 32, 48, 64, 128, 256, 512]
BG_PAPER = (246, 241, 231)   # 宣纸色（#F6F1E7）
CINNABAR = (184, 69, 60)     # 朱砂
ROUGE = (217, 112, 142)      # 胭脂
GOLD = (201, 162, 75)          # 藤黄金线
STONE = (46, 90, 108)        # 黛蓝


def draw_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = size // 12

    # 宣纸圆角底
    d.rounded_rectangle([0, 0, size, size], radius=r, fill=BG_PAPER + (255,))

    cx = cy = size / 2

    # 5 瓣梅花（胭脂花瓣）
    petals = 5
    petal_r = size * 0.22
    for i in range(petals):
        a = math.pi * 2 * i / petals - math.pi / 2
        px = cx + petal_r * 0.55 * math.cos(a)
        py = cy + petal_r * 0.55 * math.sin(a)
        pr = size * 0.08
        d.ellipse([px - pr, py - pr, px + pr, py + pr], fill=ROUGE + (230,))

    # 中心花托（朱砂）
    d.ellipse(
        [cx - size*0.11, cy - size*0.11, cx + size*0.11, cy + size*0.11],
        fill=CINNABAR + (255,),
    )

    # 花蕊（金线）
    d.ellipse(
        [cx - size*0.05, cy - size*0.05, cx + size*0.05, cy + size*0.05],
        fill=GOLD + (255,),
    )

    # 月洞门弧线（黛蓝）
    arc_box = [cx - size*0.42, cy - size*0.42, cx + size*0.42, cy + size*0.42]
    d.arc(arc_box, start=200, end=340, fill=STONE + (200,), width=max(1, size//50))

    return img


def main():
    base = draw_icon(512)
    for s in SIZES:
        ico = base.resize((s, s), Image.Resampling.LANCZOS)
        ico.save(OUT_DIR / f"{s}x{s}.png")
        print(f"generated {s}x{s}.png")
    base.save(OUT_DIR / "icon.png")
    print("generated icon.png")


if __name__ == "__main__":
    main()
