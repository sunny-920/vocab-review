"""產生程式圖示：app/static/icon.ico、favicon.png、icon.svg

需要 Pillow（不在 requirements 裡，只有改圖示時才用）：
    python -m pip install --target <暫存資料夾> pillow
    set PYTHONPATH=<暫存資料夾> && python tools/make_icon.py

設計：藍底圓角方塊上一疊單字卡，前面那張寫著 Aa，右上角一顆綠燈（＝已經會了）。
小尺寸（32px 以下）只畫一張卡和 A，才看得清楚。
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "app" / "static"
FONT = r"C:\Windows\Fonts\georgiab.ttf"

BLUE = (47, 87, 200)       # 比網頁的 accent 再深一點
INK = (28, 32, 39)
GREEN = (47, 158, 94)
WHITE = (255, 255, 255)
S = 1024                   # 先畫大圖再縮小，邊緣比較乾淨


def rounded(draw, box, r, fill):
    draw.rounded_rectangle(box, radius=r, fill=fill)


def card_layer(w, h, r, fill):
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    rounded(ImageDraw.Draw(im), (0, 0, w - 1, h - 1), r, fill)
    return im


def text_center(draw, cx, cy, text, size):
    font = ImageFont.truetype(FONT, size)
    draw.text((cx, cy), text, font=font, fill=INK, anchor="mm")


def big():
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    rounded(d, (40, 40, S - 40, S - 40), 210, BLUE)

    cw, ch = 500, 620
    cx, cy = S // 2 + 30, S // 2 + 20
    # 後面那張：半透明、斜一點
    back = card_layer(cw, ch, 56, (255, 255, 255, 95)).rotate(9, resample=Image.BICUBIC, expand=True)
    im.alpha_composite(back, (cx - back.width // 2 - 70, cy - back.height // 2 - 40))
    # 前面那張
    front = card_layer(cw, ch, 56, WHITE)
    im.alpha_composite(front, (cx - cw // 2, cy - ch // 2))
    d = ImageDraw.Draw(im)
    text_center(d, cx, cy + 20, "Aa", 250)
    # 綠燈
    gx, gy, gr = cx + cw // 2 - 78, cy - ch // 2 + 78, 34
    d.ellipse((gx - gr, gy - gr, gx + gr, gy + gr), fill=GREEN)
    return im


def small():
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    rounded(d, (0, 0, S - 1, S - 1), 200, BLUE)
    cw, ch = 640, 760
    cx, cy = S // 2, S // 2
    rounded(d, (cx - cw // 2, cy - ch // 2, cx + cw // 2, cy + ch // 2), 90, WHITE)
    text_center(d, cx, cy + 30, "A", 560)
    return im


def main():
    hi, lo = big(), small()
    sizes = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]
    frames = [(lo if n <= 32 else hi).resize((n, n), Image.LANCZOS) for n in sizes]
    frames[-1].save(OUT / "icon.ico", format="ICO", sizes=[(n, n) for n in sizes],
                    append_images=frames[:-1])
    # 手機「加入主畫面」：iPhone 會自己切圓角，透明的角會變黑，所以鋪滿藍底
    full = Image.new("RGBA", hi.size, BLUE + (255,))
    full.alpha_composite(hi)
    for n in (180, 192, 512):
        full.convert("RGB").resize((n, n), Image.LANCZOS).save(OUT / f"icon-{n}.png")
    lo.resize((32, 32), Image.LANCZOS).save(OUT / "favicon.png")
    # 預覽圖
    sheet = Image.new("RGBA", (sum(sizes) + 20 * len(sizes) + 20, 300), (245, 246, 248, 255))
    x = 20
    for f in frames:
        sheet.alpha_composite(f, (x, 280 - f.height))
        x += f.width + 20
    return sheet


if __name__ == "__main__":
    import sys
    main().save(sys.argv[1] if len(sys.argv) > 1 else "icon-preview.png")
    print("ok")
