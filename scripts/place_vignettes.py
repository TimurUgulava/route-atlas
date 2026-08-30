#!/usr/bin/env python3
"""route-atlas v2: слой виньеток — вырезка, вживление, тени, сплавка швов.

Виньетки генерятся движком ПО ОДНОЙ на чисто-белом фоне, в стиле самой карты
(стилевой референс — покрашенная база: виньетке референс безопасен, у неё нет
географии, которую можно снести). Всё остальное — детерминированно, здесь:

  · белый фон срезается заливкой от краёв кадра — белые ЧАСТИ объекта
    (белая машина, белые стены) при этом не страдают;
  · цвет слегка подгоняется под палитру карты;
  · контактная тень у «ног» + мягкая падающая по свету сцены (СЗ → ЮВ);
  · лёгкий живописный фильтр по зоне вклейки сплавляет швы с картиной.

Расстановка — placement.json; позиции нормированные, ширины в пикселях
эталонного кадра 2752 (масштабируются автоматически):
  [{"file": "vign-car.png", "x": 0.360, "y": 0.428, "width": 250}, ...]

Сажай виньетки К МАРШРУТУ (машина — на линию, зверь — к дороге, здание — к своей
точке): посадка в сцену и даёт эффект «рисованной книги» вместо парения поверх.

Пример:
  python3 scripts/place_vignettes.py --base with-route.png \
      --placement placement.json --sprites vignettes/ --out full.png
"""
import argparse
import json
import os

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter
from scipy import ndimage

REF_W = 2752


def cut(path):
    im = Image.open(path).convert("RGBA")
    a = np.asarray(im).copy()
    white = (a[..., :3] > 240).all(2)
    lbl, _ = ndimage.label(white)
    border = set(np.concatenate([lbl[0, :], lbl[-1, :], lbl[:, 0], lbl[:, -1]]))
    border.discard(0)
    a[..., 3] = np.where(np.isin(lbl, list(border)), 0, 255)
    im = Image.fromarray(a)
    im.putalpha(im.split()[3].filter(ImageFilter.GaussianBlur(1.5)))
    return im.crop(im.getbbox())


def grade(sp):
    """Лёгкая подгонка к палитре карты: чуть теплее, чуть спокойнее."""
    sp = ImageEnhance.Color(sp).enhance(0.93)
    a = np.asarray(sp, np.float32)
    a[..., 0] = np.clip(a[..., 0] * 1.03 + 3, 0, 255)
    a[..., 1] = np.clip(a[..., 1] * 1.02 + 2, 0, 255)
    a[..., 2] = np.clip(a[..., 2] * 0.97, 0, 255)
    return Image.fromarray(a.astype(np.uint8))


def kuwahara(a, r):
    out = np.zeros_like(a)
    best = np.full(a.shape[:2], 1e18, np.float32)
    lum = a.mean(2)
    for sy in (-r, r):
        for sx in (-r, r):
            shl = np.roll(np.roll(lum, sy, 0), sx, 1)
            mean = ndimage.uniform_filter(shl, r)
            var = ndimage.uniform_filter(shl ** 2, r) - mean ** 2
            var = np.roll(np.roll(var, -sy, 0), -sx, 1)
            pick = var < best
            best[pick] = var[pick]
            for k in range(3):
                shc = np.roll(np.roll(a[..., k], sy, 0), sx, 1)
                mc = ndimage.uniform_filter(shc, r)
                mc = np.roll(np.roll(mc, -sy, 0), -sx, 1)
                out[..., k][pick] = mc[pick]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="база с уже нарисованным маршрутом")
    ap.add_argument("--placement", required=True)
    ap.add_argument("--sprites", required=True, help="папка с генерациями виньеток")
    ap.add_argument("--out", required=True)
    ap.add_argument("--no-melt", action="store_true",
                    help="без сплавляющего фильтра (для чётких графичных стилей)")
    args = ap.parse_args()

    base = Image.open(args.base).convert("RGBA")
    W, H = base.size
    k = W / REF_W
    items = json.load(open(args.placement))
    regions = []

    for it in items:
        sp = grade(cut(os.path.join(args.sprites, it["file"])))
        w = int(it["width"] * k)
        h = int(sp.height * w / sp.width)
        sp = sp.resize((w, h), Image.LANCZOS)
        X, Y = int(it["x"] * W - w / 2), int(it["y"] * H - h / 2)
        alpha = sp.split()[3]

        contact = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        dc = ImageDraw.Draw(contact)
        ew, eh = int(w * 0.72), max(14, int(h * 0.13))
        cx, cy = X + w // 2 + int(w * 0.03), Y + h - eh // 3
        dc.ellipse([cx - ew // 2, cy - eh // 2, cx + ew // 2, cy + eh // 2],
                   fill=(50, 36, 14, 120))
        base.alpha_composite(contact.filter(ImageFilter.GaussianBlur(10 * k)))

        sh = Image.new("RGBA", sp.size, (0, 0, 0, 0))
        sh.paste(Image.new("RGBA", sp.size, (50, 36, 14, 95)), (0, 0), alpha)
        base.alpha_composite(sh.filter(ImageFilter.GaussianBlur(7 * k)),
                             (X + int(9 * k), Y + int(12 * k)))
        base.alpha_composite(sp, (X, Y))
        pad = int(14 * k)
        regions.append((max(0, X - pad), max(0, Y - pad),
                        min(W, X + w + pad), min(H, Y + h + pad)))

    img = np.asarray(base.convert("RGB"), np.float32)
    if not args.no_melt:
        r = max(3, int(round(3 * k)))
        for (x0, y0, x1, y1) in regions:
            crop = img[y0:y1, x0:x1]
            img[y0:y1, x0:x1] = crop * 0.5 + kuwahara(crop, r) * 0.5
    Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save(args.out)
    print(f"-> {args.out} (виньеток: {len(items)}, масштаб {k:.2f})")


if __name__ == "__main__":
    main()
