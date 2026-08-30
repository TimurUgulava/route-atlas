#!/usr/bin/env python3
"""route-atlas v2: настоящий рельеф из открытых данных высот.

По bbox из georef.json скачивает открытые тайлы высот Terrarium (зеркало AWS,
без ключей и регистрации; в данных есть глубины моря, поэтому береговая линия
рисуется сама) и рендерит базовую карту: гипсометрическая раскраска +
многонаправленная светотень + песчаные отмели + море с глубинным градиентом.

Эта база — вход для художественной покраски (см. production.md). Она же —
запасной финал: если движок покраски недоступен или не прошёл контроль дрейфа,
карта собирается прямо на ней, и это честная точная карта.

Палитра настраивается файлом (--palette), который собирает студия стиля;
без файла используются нейтральные природные цвета. Формат:
  {
    "land_stops": [[0,[196,196,140]], [400,[104,140,72]], [1800,[178,168,128]]],
    "sea_shallow": [168,203,188], "sea_deep": [104,148,152],
    "sand": [228,214,170]
  }

Дополнительно сохраняет маску суши (--landmask) — её потом ест drift_check.py.

Пример:
  python3 scripts/render_terrain.py --georef georef.json \
      --out terrain.png --landmask landmask.npy
"""
import argparse
import json
import math
import os
import tempfile

import numpy as np
import requests
from PIL import Image
from scipy import ndimage

TILE_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"

DEFAULT_PALETTE = {
    "land_stops": [[0, [196, 196, 140]], [60, [172, 182, 112]], [200, [140, 166, 92]],
                   [420, [104, 140, 72]], [700, [82, 116, 60]], [1000, [96, 118, 66]],
                   [1400, [150, 148, 104]], [1800, [178, 168, 128]]],
    "sea_shallow": [168, 203, 188],
    "sea_deep": [104, 148, 152],
    "sand": [228, 214, 170],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--georef", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--landmask", help="куда сохранить маску суши (.npy)")
    ap.add_argument("--palette", help="JSON с палитрой из студии стиля")
    ap.add_argument("--width", type=int, default=2752)
    ap.add_argument("--zoom", type=int, default=11,
                    help="зум тайлов высот: 11 для областей, 12-13 для коротких маршрутов")
    ap.add_argument("--zex", type=float, default=3.2, help="вертикальное преувеличение")
    args = ap.parse_args()

    pal = dict(DEFAULT_PALETTE)
    if args.palette:
        pal.update(json.load(open(args.palette)))
    bb = json.load(open(args.georef))["bbox"]
    Z, N = args.zoom, 2 ** args.zoom
    cache = os.path.join(tempfile.gettempdir(), "route-atlas-dem")
    os.makedirs(cache, exist_ok=True)

    def lon2tx(lon):
        return (lon + 180) / 360 * N

    def lat2ty(lat):
        return (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * N

    tx0, tx1 = int(lon2tx(bb["lon_w"])), int(lon2tx(bb["lon_e"]))
    ty0, ty1 = int(lat2ty(bb["lat_n"])), int(lat2ty(bb["lat_s"]))
    print(f"Тайлы высот: {(tx1-tx0+1)*(ty1-ty0+1)} шт, zoom {Z}")

    s = requests.Session()
    mosaic = np.zeros(((ty1 - ty0 + 1) * 256, (tx1 - tx0 + 1) * 256), np.float32)
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            fp = f"{cache}/{Z}-{tx}-{ty}.png"
            if not os.path.exists(fp):
                r = s.get(TILE_URL.format(z=Z, x=tx, y=ty), timeout=30)
                r.raise_for_status()
                open(fp, "wb").write(r.content)
            a = np.asarray(Image.open(fp).convert("RGB"), np.float32)
            mosaic[(ty - ty0) * 256:(ty - ty0 + 1) * 256,
                   (tx - tx0) * 256:(tx - tx0 + 1) * 256] = \
                a[:, :, 0] * 256 + a[:, :, 1] + a[:, :, 2] / 256 - 32768

    my0 = math.asinh(math.tan(math.radians(bb["lat_n"])))
    my1 = math.asinh(math.tan(math.radians(bb["lat_s"])))
    aspect = math.radians(bb["lon_e"] - bb["lon_w"]) / (my0 - my1)
    W = args.width
    H = int(round(W / aspect))

    xs = np.linspace((lon2tx(bb["lon_w"]) - tx0) * 256, (lon2tx(bb["lon_e"]) - tx0) * 256, W)
    ys = np.linspace((lat2ty(bb["lat_n"]) - ty0) * 256, (lat2ty(bb["lat_s"]) - ty0) * 256, H)
    gx, gy = np.meshgrid(xs, ys)
    elev = ndimage.map_coordinates(mosaic, [gy.ravel(), gx.ravel()], order=1).reshape(H, W)
    elev = ndimage.gaussian_filter(elev, 1.2)

    lat_mid = (bb["lat_n"] + bb["lat_s"]) / 2
    m_px = (bb["lon_e"] - bb["lon_w"]) * 111320 * math.cos(math.radians(lat_mid)) / W
    land = elev > 0
    if args.landmask:
        np.save(args.landmask, land)

    dy, dx = np.gradient(elev * args.zex, m_px)
    slope = np.arctan(np.hypot(dx, dy))
    aspect_a = np.arctan2(-dx, dy)

    def hs(az, alt):
        a, l = math.radians(az), math.radians(alt)
        return np.clip(np.sin(l) * np.cos(slope) +
                       np.cos(l) * np.sin(slope) * np.cos(a - aspect_a), 0, 1)

    shade = 0.55 * hs(315, 42) + 0.25 * hs(270, 38) + 0.20 * hs(0, 55)
    lit = np.clip(hs(315, 42) - 0.55, 0, 1)
    shad = np.clip(0.45 - hs(315, 42), 0, 1)

    stops = [(e, tuple(c)) for e, c in pal["land_stops"]]
    e_max = stops[-1][0]
    e = np.clip(elev, 0, e_max)
    base = np.zeros((H, W, 3), np.float32)
    for (e0, c0), (e1, c1) in zip(stops, stops[1:]):
        m = (e >= e0) & (e <= e1)
        t = ((e - e0) / (e1 - e0))[m]
        for k in range(3):
            base[..., k][m] = c0[k] + (c1[k] - c0[k]) * t
    valley = np.clip(1 - slope / 0.25, 0, 1) * np.clip(1 - e / 500, 0, 1)
    base += valley[..., None] * np.array((36, 26, -14))
    base += lit[..., None] * np.array((34, 24, -6))
    base -= shad[..., None] * np.array((26, 14, -10))
    base *= (0.42 + 0.72 * shade)[..., None]

    coast_land = ndimage.distance_transform_edt(land) * m_px
    sand = np.clip(1 - coast_land / 700, 0, 1) * np.clip(1 - e / 80, 0, 1) * land
    base = base * (1 - sand[..., None] * 0.8) + \
        np.array(pal["sand"], float) * (sand * 0.8)[..., None]

    depth = np.clip(-elev, 0, 2500) / 2500
    sea = np.zeros((H, W, 3), np.float32)
    c_sh, c_dp = np.array(pal["sea_shallow"], float), np.array(pal["sea_deep"], float)
    for k in range(3):
        sea[..., k] = c_sh[k] + (c_dp[k] - c_sh[k]) * np.sqrt(depth)
    coast_sea = ndimage.distance_transform_edt(~land) * m_px
    shal = np.clip(1 - coast_sea / 900, 0, 1)
    sea = sea * (1 - (shal * 0.6)[..., None]) + \
        np.array((212, 220, 196)) * (shal * 0.6)[..., None]

    img = np.where(land[..., None], base, sea)
    Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save(args.out)
    print(f"-> {args.out} ({W}x{H}, {m_px:.0f} м/px)")


if __name__ == "__main__":
    main()
