#!/usr/bin/env python3
"""route-atlas v2: слой маршрута — линия и точки, детерминированно.

Маршрут рисуется НЕ генеративной моделью, а этим скриптом: сглаженный сплайн
плюс точки, поверх любой базы. Поэтому он всегда лежит ровно там, где ехал
человек, не рвётся, не уходит за финиш и не деградирует от правок.

Геометрия — geometry.json (оцифровка скриншота, см. production.md):
  {"route": [[x,y],...], "waypoints": {"Имя точки": [x,y], ...}}
  координаты нормированные, 0..1 кадра.

Пластика — route-style.json пользователя (создаётся в студии стиля из шаблона
assets/route-style-template.json: цвет — фирменный из паспорта, толщина и размер
точек подбираются на пробниках). Без --style берётся шаблон с нейтральными
значениями — годится для проб, но не для финала.

Технически линия рисуется «штампованием» кругов вдоль сплайна: PIL-ломаная
с шириной даёт зазубрины на стыках сегментов.

Пример:
  python3 scripts/draw_route.py --base painted.png --geometry geometry.json \
      --style route-style.json --out with-route.png
"""
import argparse
import json
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from scipy import interpolate

REF_W = 2752  # ширина кадра, для которой заданы радиусы в style-файле
TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets",
                        "route-style-template.json")


def stamp(draw, xs, ys, r, fill):
    for x, y in zip(np.atleast_1d(xs), np.atleast_1d(ys)):
        draw.ellipse([x - r, y - r, x + r, y + r], fill=fill)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="база (покрашенная или terrain)")
    ap.add_argument("--geometry", required=True)
    ap.add_argument("--style", default=TEMPLATE,
                    help="route-style.json пользователя (default: нейтральный шаблон)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--endpoints", default=None,
                    help="имена конечных точек через ';' (default: первая и последняя)")
    args = ap.parse_args()

    if os.path.abspath(args.style) == os.path.abspath(TEMPLATE):
        print("⚠ Рисую по нейтральному шаблону. Для финала нужен route-style.json "
              "пользователя с его фирменным цветом (студия стиля).")
    std = json.load(open(args.style))
    base = Image.open(args.base).convert("RGBA")
    W, H = base.size
    k = W / REF_W
    ss = 2 if W < 3000 else 1

    geo = json.load(open(args.geometry))
    pts = np.array(geo["route"], float) * [W, H]
    tck, _ = interpolate.splprep([pts[:, 0], pts[:, 1]],
                                 s=len(pts) * std["spline_smoothing_per_point"])
    n = max(4000, int(6000 * k))
    sx, sy = np.array(interpolate.splev(np.linspace(0, 1, n), tck)) * ss

    L, sh = std["line"], std["line"]["shadow"]
    size = (W * ss, H * ss)

    shadow = Image.new("RGBA", size, (0, 0, 0, 0))
    stamp(ImageDraw.Draw(shadow), sx + sh["offset"][0] * k * ss,
          sy + sh["offset"][1] * k * ss, sh["r"] * k * ss,
          tuple(sh["rgba"][:3]) + (255,))
    shadow = shadow.filter(ImageFilter.GaussianBlur(sh["blur"] * k))
    shadow.putalpha(shadow.split()[3].point(lambda a: int(a * sh["rgba"][3] / 255)))

    line = Image.new("RGBA", size, (0, 0, 0, 0))
    dl = ImageDraw.Draw(line)
    stamp(dl, sx, sy, L["casing_r"] * k * ss, tuple(L["casing_rgb"]) + (255,))
    stamp(dl, sx, sy, L["fill_r"] * k * ss, tuple(L["fill_rgb"]) + (255,))

    layers = [shadow, line]
    if L.get("highlight_r", 0) and L.get("highlight_rgba", [0, 0, 0, 0])[3]:
        hi = Image.new("RGBA", size, (0, 0, 0, 0))
        stamp(ImageDraw.Draw(hi), sx - 2 * k * ss, sy - 4 * k * ss,
              L["highlight_r"] * k * ss, tuple(L["highlight_rgba"][:3]) + (255,))
        hi.putalpha(hi.split()[3].point(lambda a: int(a * L["highlight_rgba"][3] / 255)))
        layers.append(hi)

    names = list(geo["waypoints"])
    ends = set(args.endpoints.split(";")) if args.endpoints else {names[0], names[-1]}
    C = std["dot_colors"]
    dots = Image.new("RGBA", size, (0, 0, 0, 0))
    dsh = Image.new("RGBA", size, (0, 0, 0, 0))
    dd, dds = ImageDraw.Draw(dots), ImageDraw.Draw(dsh)
    for name, (x, y) in geo["waypoints"].items():
        p = std["endpoint"] if name in ends else std["waypoint"]
        r1, r2 = p["ring_r"] * k * ss, p["core_r"] * k * ss
        X, Y = x * W * ss, y * H * ss
        dds.ellipse([X + 10 * k - r1, Y + 14 * k - r1, X + 10 * k + r1, Y + 14 * k + r1],
                    fill=(60, 40, 10, 120))
        dd.ellipse([X - r1, Y - r1, X + r1, Y + r1], fill=tuple(C["ring"]) + (255,))
        dd.ellipse([X - r2, Y - r2, X + r2, Y + r2], fill=tuple(C["core"]) + (255,))
        dd.ellipse([X - r2 * 0.85, Y - r2 * 0.85, X + r2 * 0.2, Y + r2 * 0.2],
                   fill=tuple(C["gleam"]) + (255,))
    dsh = dsh.filter(ImageFilter.GaussianBlur(8 * k))
    layers += [dsh, dots]

    out = base
    for layer in layers:
        if layer.size != (W, H):
            layer = layer.resize((W, H), Image.LANCZOS)
        out = Image.alpha_composite(out, layer)
    out.convert("RGB").save(args.out)
    print(f"-> {args.out} ({W}x{H}, масштаб пластики {k:.2f})")


if __name__ == "__main__":
    main()
