#!/usr/bin/env python3
"""route-atlas v2: геопривязка скриншота — фундамент точной карты.

Вход — anchors.json: пиксели населённых пунктов на скриншоте плюс их реальные
координаты. Пиксели ассистент снимает по измерительной сетке (см. production.md),
координаты каждого города ПРОВЕРЯЕТ поиском, а не берёт из памяти. Формат:

  {
    "anchors": {
      "Переславль-Залесский": {"px": [755, 163], "lat": 56.7360, "lon": 38.8527},
      ...ещё 7-11 городов...
    },
    "plate": [638, 118, 2200, 997]   // рамка самой карты без панелей UI, px
  }

Скрипт подгоняет веб-меркаторную сетку (Яндекс/Гугл/OSM — все в Web Mercator)
методом наименьших квадратов, сам выбрасывает кривые якоря (остаток больше
max(25 px, 2×медианы)) и проверяет изотропию: масштабы по X и Y обязаны
совпасть с точностью долей процента, потому что у веб-карт пиксель квадратный.
Разошлись сильнее 1% — значит, какие-то якоря сняты или найдены неверно,
и скрипт честно останавливается вместо того, чтобы выдать кривую привязку.

Выход — georef.json с bbox рамки: дальше он кормит render_terrain.py.

Пример:
  python3 scripts/fit_georef.py --anchors anchors.json --out georef.json
"""
import argparse
import json
import math

import numpy as np


def merc_y(lat):
    return math.asinh(math.tan(math.radians(lat)))


def inv_merc_y(Y):
    return math.degrees(math.atan(math.sinh(Y)))


def fit(anchors, names):
    X = np.array([math.radians(anchors[n]["lon"]) for n in names])
    Y = np.array([merc_y(anchors[n]["lat"]) for n in names])
    px = np.array([anchors[n]["px"][0] for n in names], float)
    py = np.array([anchors[n]["px"][1] for n in names], float)
    a, b = np.polyfit(X, px, 1)
    c, d = np.polyfit(Y, py, 1)
    res = np.sqrt((a * X + b - px) ** 2 + (c * Y + d - py) ** 2)
    return (a, b, c, d), dict(zip(names, np.round(res, 1)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--anchors", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    spec = json.load(open(args.anchors))
    anchors, plate = spec["anchors"], spec["plate"]
    names = list(anchors)
    if len(names) < 4:
        raise SystemExit("Нужно минимум 4 якоря (лучше 8-12: запас на отсев).")

    (a, b, c, d), res = fit(anchors, names)
    med = float(np.median(list(res.values())))
    keep = [n for n in names if res[n] <= max(25, 2 * med)]
    dropped = [n for n in names if n not in keep]
    (a, b, c, d), res = fit(anchors, keep)

    iso = abs(a / -c - 1)
    print(f"Якорей в подгонке: {len(keep)} (выброшено: {dropped or 'нет'})")
    print(f"Остатки, px: {res}")
    print(f"Изотропия: kx={a:.1f}, ky={-c:.1f}, расхождение {iso*100:.2f}%")
    if iso > 0.01:
        raise SystemExit("⛔ Масштабы X/Y разошлись больше 1% — часть якорей "
                         "снята или найдена неверно. Перепроверь пиксели и "
                         "координаты, не пытайся ехать дальше на кривой привязке.")

    def px2ll(px, py):
        return inv_merc_y((py - d) / c), math.degrees((px - b) / a)

    nw, se = px2ll(plate[0], plate[1]), px2ll(plate[2], plate[3])
    json.dump({"a": a, "b": b, "c": c, "d": d, "plate": plate,
               "bbox": {"lat_n": nw[0], "lon_w": nw[1], "lat_s": se[0], "lon_e": se[1]},
               "residuals_px": {k: float(v) for k, v in res.items()},
               "dropped": dropped},
              open(args.out, "w"), ensure_ascii=False, indent=1)
    print(f"-> {args.out}  bbox: {nw[0]:.4f},{nw[1]:.4f} … {se[0]:.4f},{se[1]:.4f}")


if __name__ == "__main__":
    main()
