"""Instagram e'loni uchun rasm: 1080x1350."""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from enturk import graphics as g  # noqa: E402

SP = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "elon" / "instagram"
W, H = 1080, 1350
RED, DEEP, MAGENTA, ORANGE, GOLD = "#E30A17", "#8E0A2E", "#C2185B", "#F57C00", "#FFC93C"
WHITE, INK = "#FFFFFF", "#1E1416"


def lerp(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(g._rgb(a), g._rgb(b)))


def gradient(w, h, stops):
    im = Image.new("RGB", (w, h))
    px = im.load()
    for y in range(h):
        for x in range(0, w):
            t = min(1, max(0, (x * 0.45 + y) / (w * 0.45 + h)))
            for i in range(len(stops) - 1):
                t0, c0 = stops[i]
                t1, c1 = stops[i + 1]
                if t0 <= t <= t1:
                    px[x, y] = lerp(c0, c1, (t - t0) / (t1 - t0))
                    break
    return im


def shadow(size, box, radius, blur=28, alpha=110, offset=(0, 18)):
    sh = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([box[0] + offset[0], box[1] + offset[1],
                                          box[2] + offset[0], box[3] + offset[1]],
                                         radius, fill=(40, 0, 20, alpha))
    return sh.filter(ImageFilter.GaussianBlur(blur))


# ---------------- fon ----------------
bg = gradient(W, H, [(0, DEEP), (0.38, RED), (0.72, MAGENTA), (1, ORANGE)]).convert("RGBA")
pat = Image.new("RGBA", (W, H), (0, 0, 0, 0))
g.tulip_pattern(ImageDraw.Draw(pat), (255, 255, 255, 26), step=130, height=H)
bg.alpha_composite(pat)
d = ImageDraw.Draw(bg)
# yorug' doiralar (bokeh)
glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
gd = ImageDraw.Draw(glow)
for cx, cy, r, a in [(930, 170, 210, 60), (120, 1080, 260, 50), (980, 980, 140, 45)]:
    gd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 220, 120, a))
bg.alpha_composite(glow.filter(ImageFilter.GaussianBlur(60)))

# ---------------- sarlavha ----------------
tag = Image.new("RGBA", (360, 90), (0, 0, 0, 0))
td = ImageDraw.Draw(tag)
td.rounded_rectangle([6, 6, 354, 84], 40, fill=GOLD)
td.text((180, 46), "YANGILIK!", font=g.font("sans", 40), fill=DEEP, anchor="mm")
tag = tag.rotate(-5, expand=True, resample=Image.BICUBIC)
bg.alpha_composite(tag, (62, 52))
g.put_emoji(bg, "🎉", 78, 430, 92, rot=12)

d = ImageDraw.Draw(bg)
d.text((70, 168), "Endi", font=g.font("display", 74), fill=WHITE)
d.text((66, 236), "INSTAGRAM'DA", font=g.font("display", 132), fill=WHITE)
hl = g.font("display", 132)
hb = d.textbbox((66, 370), "HAM BORMAN!", font=hl)
d.rounded_rectangle([hb[0] - 14, hb[1] - 6, hb[2] + 18, hb[3] + 14], 18, fill=GOLD)
d.text((66, 370), "HAM BORMAN!", font=hl, fill=DEEP)

# ---------------- telefon ----------------
PW, PH = 520, 760
phone = Image.new("RGBA", (PW + 80, PH + 80), (0, 0, 0, 0))
ph = ImageDraw.Draw(phone)
ox, oy = 40, 40
ph.rounded_rectangle([ox, oy, ox + PW, oy + PH], 70, fill="#151018")
sx0, sy0, sx1, sy1 = ox + 18, oy + 18, ox + PW - 18, oy + PH - 18
ph.rounded_rectangle([sx0, sy0, sx1, sy1], 54, fill=WHITE)
ph.rounded_rectangle([ox + PW / 2 - 60, sy0 + 14, ox + PW / 2 + 60, sy0 + 40], 13, fill="#151018")
# profil sarlavhasi
cx = sx0 + 96
cy = sy0 + 150
ring = Image.new("RGBA", (176, 176), (0, 0, 0, 0))
rg = gradient(176, 176, [(0, GOLD), (0.5, RED), (1, MAGENTA)]).convert("RGBA")
m = Image.new("L", (176, 176), 0)
ImageDraw.Draw(m).ellipse([0, 0, 175, 175], fill=255)
ring.paste(rg, (0, 0), m)
rd = ImageDraw.Draw(ring)
rd.ellipse([9, 9, 166, 166], fill=WHITE)
logo = g.logo_image(REPO / "assets" / "logo_white.png", 62, RED)
ring.alpha_composite(logo, (88 - logo.width // 2, 88 - logo.height // 2))
phone.alpha_composite(ring, (int(cx - 88), int(cy - 88)))
ph.text((sx0 + 210, cy - 52), "jasurturktili", font=g.font("sans", 34), fill=INK)
for i, (num, lab) in enumerate([("🇹🇷", "Turk tili"), ("A1→C1", "darajalar"), ("🎯", "sertifikat")]):
    x = sx0 + 222 + i * 92
    if num.startswith("🇹🇷") or num == "🎯":
        g.put_emoji(phone, num, 34, x + 20, cy + 6)
    else:
        ph.text((x + 20, cy + 6), num, font=g.font("sans", 22), fill=INK, anchor="mm")
    ph.text((x + 20, cy + 42), lab, font=g.font("sans_r", 18), fill="#6A5A5C", anchor="mm")
ph.text((sx0 + 36, cy + 104), "Jasur | Turk tili", font=g.font("sans", 28), fill=INK)
ph.text((sx0 + 36, cy + 142), "Turk tilini qiziqarli o'rganamiz!", font=g.font("sans_r", 22), fill="#4A3A3C")
by = cy + 186
ph.rounded_rectangle([sx0 + 34, by, sx1 - 34, by + 58], 16, fill=RED)
ph.text(((sx0 + sx1) / 2, by + 29), "Obuna bo'lish", font=g.font("sans", 28), fill=WHITE, anchor="mm")
# post to'ri
tiles = [("Merhaba!", "👋", "#FDE2E4", RED), ("Çay?", "☕", "#FFF1D6", "#B5651D"),
         ("Günaydın", "🌅", "#FFE3C2", "#D35400"), ("A1 → C1", "🚀", "#E3ECFF", "#1E4FBF"),
         ("Nazar", "🧿", "#DDF4F2", "#13807F"), ("Haydi!", "🔥", "#F3E3FF", "#7B2FA8")]
gx0, gy0 = sx0 + 10, by + 84
tw = (sx1 - sx0 - 20 - 8) / 3
for i, (word, em, fill, col) in enumerate(tiles):
    r, c = divmod(i, 3)
    x0 = gx0 + c * (tw + 4)
    y0 = gy0 + r * (tw + 4)
    ph.rectangle([x0, y0, x0 + tw, y0 + tw], fill=fill)
    g.put_emoji(phone, em, 56, x0 + tw / 2, y0 + tw / 2 - 18)
    ph.text((x0 + tw / 2, y0 + tw - 30), word, font=g.font("sans", 22), fill=col, anchor="mm")
phone = phone.rotate(-6, expand=True, resample=Image.BICUBIC)
pxp, pyp = 440, 470
shp = Image.new("RGBA", (W, H), (0, 0, 0, 0))
shp.alpha_composite(shadow((W, H), (pxp + 80, pyp + 70, pxp + 80 + PW, pyp + 70 + PH), 70, blur=34, alpha=140)
                    .crop((0, 0, W, H)))
bg.alpha_composite(shp)
bg.alpha_composite(phone, (pxp, pyp))

# ---------------- suzuvchi "bildirishnomalar" ----------------
def bubble(text, em, w, fill=WHITE, col=INK, rot=0):
    b = Image.new("RGBA", (w + 60, 150), (0, 0, 0, 0))
    bd = ImageDraw.Draw(b)
    bd.rounded_rectangle([30, 30, w + 30, 120], 45, fill=fill)
    g.put_emoji(b, em, 52, 86, 75)
    bd.text((126, 75), text, font=g.font("sans", 32), fill=col, anchor="lm")
    b = b.rotate(rot, expand=True, resample=Image.BICUBIC)
    s = Image.new("RGBA", b.size, (0, 0, 0, 0))
    s.paste((40, 0, 20, 90), (0, 8), b.split()[3])
    out = Image.new("RGBA", b.size, (0, 0, 0, 0))
    out.alpha_composite(s.filter(ImageFilter.GaussianBlur(12)))
    out.alpha_composite(b)
    return out

bg.alpha_composite(bubble("+1 obunachi", "❤️", 330, rot=5), (110, 560))
bg.alpha_composite(bubble("Merhaba!", "💬", 290, rot=-4), (60, 760))
bg.alpha_composite(bubble("Yangi reels", "🎬", 330, rot=3), (120, 950))
for em, px, x, y, rot in [("🇹🇷", 92, 980, 520, 14), ("✨", 70, 400, 520, 0), ("🧿", 84, 985, 150, -10)]:
    g.put_emoji(bg, em, px, x, y, rot=rot, sticker=True)

# ---------------- pastki brend tasmasi ----------------
band_y = H - 150
bandsh = shadow((W, H), (0, band_y, W, H + 60), 0, blur=24, alpha=90, offset=(0, -6))
bg.alpha_composite(bandsh)
d = ImageDraw.Draw(bg)
d.rectangle([0, band_y, W, H], fill=WHITE)
d.rectangle([0, band_y, W, band_y + 8], fill=GOLD)
lg = g.logo_image(REPO / "assets" / "logo_white.png", 100, RED)
bg.alpha_composite(lg, (46, band_y + 26))
d.text((W - 48, band_y + 50), "Instagram · Telegram", font=g.font("sans_r", 28), fill="#6A5A5C", anchor="rm")
d.text((W - 48, band_y + 98), "@jasurturktili", font=g.font("sans", 48), fill=RED, anchor="rm")

out = SP / "post.jpg"
bg.convert("RGB").save(out, "JPEG", quality=92)
print(out)
