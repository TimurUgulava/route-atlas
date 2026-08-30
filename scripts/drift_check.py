#!/usr/bin/env python3
"""route-atlas v2: контроль дрейфа географии после художественной покраски.

Генеративная модель, перекрашивая базу, иногда «улучшает» географию — двигает
берег, упрощает заливы, выдумывает острова. Глазом это ловится плохо (картинка
красивая), поэтому проверяет скрипт: сравнивает море на покрашенной картинке
(классификация по цвету) с истинной маской суши из render_terrain.py.

Метрики:
  · IoU моря — доля совпадения акваторий (1.0 = идеал);
  · сдвиг берега — медиана и 90-й перцентиль расстояния от берега покраски
    до истинного берега, в пикселях.

Гейт по умолчанию: PASS при IoU ≥ 0.80 и медиане ≤ 5 px. Числа выведены из
живого замера: покраска БЕЗ референса-картинки дала IoU 0.84 и медиану 3 px,
покраска С референсом-эталоном — IoU 0.37 (треть географии перерисована).

Провал гейта — не «на глаз вроде нормально», а перегенерация покраски с другой
формулировкой ЛИБО откат на детерминированную базу render_terrain.py.

Для маршрутов без моря (континентальных) проверка по воде не работает —
скрипт честно скажет об этом и предложит визуальную сверку по рекам и озёрам.

Пример:
  python3 scripts/drift_check.py --painted painted.png --landmask landmask.npy
"""
import argparse
import sys

import numpy as np
from PIL import Image
from scipy import ndimage


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--painted", required=True, help="покрашенная база")
    ap.add_argument("--landmask", required=True, help="маска суши .npy от render_terrain.py")
    ap.add_argument("--min-iou", type=float, default=0.80)
    ap.add_argument("--max-median-shift", type=float, default=5.0)
    args = ap.parse_args()

    land = np.load(args.landmask)
    H, W = land.shape
    sea_true = ~land
    if sea_true.mean() < 0.02:
        print("В кадре почти нет воды — контроль по морю не работает.")
        print("Сверь покраску с terrain-базой глазами: русла рек, озёра, "
              "долины обязаны совпадать. Сомневаешься — откат на базу.")
        return

    a = np.asarray(Image.open(args.painted).convert("RGB").resize((W, H)), np.int16)
    R, G, B = a[..., 0], a[..., 1], a[..., 2]
    sea_nb = ndimage.binary_closing((B > R + 8) & (G > R - 5) & (B > 90), iterations=3)

    iou = (sea_nb & sea_true).sum() / max(1, (sea_nb | sea_true).sum())
    edge_true = sea_true ^ ndimage.binary_erosion(sea_true)
    edge_nb = sea_nb ^ ndimage.binary_erosion(sea_nb)
    dist = ndimage.distance_transform_edt(~edge_true)
    shifts = dist[edge_nb] if edge_nb.any() else np.array([np.inf])
    med, p90 = float(np.median(shifts)), float(np.percentile(shifts, 90))

    print(f"IoU моря: {iou:.3f}   сдвиг берега: медиана {med:.1f} px, p90 {p90:.1f} px")
    if iou >= args.min_iou and med <= args.max_median_shift:
        print("PASS — география уцелела, можно накладывать слои.")
    else:
        print("FAIL — покраска снесла географию. Перегенерируй покраску "
              "(и проверь, что в неё НЕ передан референс-картинка) или "
              "откатись на детерминированную базу render_terrain.py.")
        sys.exit(1)


if __name__ == "__main__":
    main()
