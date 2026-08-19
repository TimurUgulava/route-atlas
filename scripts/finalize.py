#!/usr/bin/env python3
"""route-atlas: подписи и разрешение — финальный шаг сборки карты.

Делает две вещи, которые генеративная модель делает плохо:
  1. Ставит подписи-капсулы ПРОГРАММНО — ровным шрифтом, одним кеглем, без
     единой опечатки. Модели врут в тексте (особенно в кириллице), поэтому
     карта генерится без надписей вообще, а имена ставятся здесь.
  2. Поднимает разрешение через Real-ESRGAN. Не установлен — предлагает поставить
     (scripts/install_upscaler.py) и мягко увеличивает через Lanczos, чтобы карта
     не осталась в размере 1376×768.

Как задавать подписи (JSON). Рекомендуемый способ — привязка к точке маршрута:
  [
    {"text": "Москва", "anchor": [0.424, 0.820], "side": "below", "gap": 0.006},
    {"text": "Переславль-Залесский", "anchor": [0.613, 0.349], "side": "left"}
  ]
  anchor — координаты САМОЙ ТОЧКИ на карте (её видно, снять легко);
  side   — с какой стороны лечь капсуле: left / right / above / below;
  gap    — зазор от точки до края капсулы, в долях ширины кадра. Одинаковый
           у всех подписей → визуально ровный ряд. По умолчанию 0.006.
  Ширину капсулы считает скрипт — снаружи её знать неоткуда.

Старый способ (координата = ЦЕНТР капсулы) продолжает работать:
  {"text": "Москва", "x": 0.42, "y": 0.82}

Режимы:
  place   (по умолчанию) — рисует капсулы с нуля. Карта генерилась БЕЗ текста.
  overlay — находит капсулу, нарисованную моделью, и перекрывает её ровной.

Порядок работы: сначала черновые прогоны с --no-upscale (быстро, координаты
подбираются за секунды), в конце — финальный прогон без этого флага.

Апскейл идёт ДО простановки подписей намеренно: тогда текст рисуется сразу
в конечном разрешении и остаётся идеально резким. Если апскейлить после,
Real-ESRGAN обработает и буквы, а это ровно та резкость, ради которой подписи
и делаются программно.

Примеры:
  # черновой прогон: сетка для координат, без ожидания апскейлера
  python3 finalize.py --input map.png --labels labels.json --output draft.png \
      --grid --no-upscale
  # финальный прогон
  python3 finalize.py --input map.png --labels labels.json --output final.png \
      --dot-color C25B3A --also-half
"""
import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from collections import deque

try:
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
except ImportError:
    sys.exit("Нужны Pillow и numpy:  pip install pillow numpy")

# --- шрифты: кандидаты по платформам (все перечисленные поддерживают кириллицу) ---
FONT_CANDIDATES = {
    "Darwin": [
        ("/System/Library/Fonts/HelveticaNeue.ttc", "Medium"),
        ("/System/Library/Fonts/Supplemental/Arial.ttf", None),
        ("/Library/Fonts/Arial.ttf", None),
        ("/System/Library/Fonts/Geneva.ttf", None),
    ],
    "Linux": [
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", None),
        ("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf", None),
        ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", None),
        ("/usr/share/fonts/TTF/DejaVuSans.ttf", None),
    ],
    "Windows": [
        (r"C:\Windows\Fonts\segoeui.ttf", None),
        (r"C:\Windows\Fonts\arial.ttf", None),
        (r"C:\Windows\Fonts\tahoma.ttf", None),
    ],
}
UPSCALER_DIRS = [
    os.path.expanduser("~/.claude/tools/realesrgan"),
    os.path.expanduser("~/.local/share/realesrgan"),
    os.path.expanduser("~/realesrgan"),
    "/usr/local/share/realesrgan",
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "realesrgan"),
    os.path.join(os.environ.get("USERPROFILE", ""), "realesrgan"),
]
UPSCALER_NAMES = (["realesrgan-ncnn-vulkan.exe", "realesrgan-ncnn-vulkan"]
                  if platform.system() == "Windows" else ["realesrgan-ncnn-vulkan"])
PY = "python" if platform.system() == "Windows" else "python3"
SIDES = ("left", "right", "above", "below")
DEFAULT_GAP = 0.006


def upscaler_howto():
    """Инструкция по установке — только для текущей системы, без чужих платформ."""
    here = os.path.dirname(os.path.abspath(__file__))
    installer = os.path.join(here, "install_upscaler.py")
    lines = ["Real-ESRGAN не установлен — чёткого 4k не будет.",
             "Поставить одной командой (скачает нужную сборку под вашу систему):",
             f"    {PY} {installer}"]
    if platform.system() == "Darwin":
        lines.append("Скрипт сам снимет карантин macOS — руками ничего делать не нужно.")
    elif platform.system() == "Windows":
        lines.append(r"Скрипт распакует всё в C:\Users\<вы>\.claude\tools\realesrgan.")
    return "\n".join(lines)


def font_covers(path, index, text):
    """Проверяет, что в шрифте есть все нужные глифы (если доступен fontTools)."""
    try:
        from fontTools.ttLib import TTFont, TTCollection
    except ImportError:
        return True  # проверить нечем — доверяем списку кандидатов
    try:
        if path.lower().endswith(".ttc"):
            fonts = TTCollection(path).fonts
            font = fonts[index if index is not None and index < len(fonts) else 0]
        else:
            font = TTFont(path, fontNumber=0, lazy=True)
        cmap = set()
        for table in font["cmap"].tables:
            cmap.update(table.cmap.keys())
        return all(ord(ch) in cmap for ch in text if ch.strip())
    except Exception:
        return True


def resolve_font(sample_text, explicit=None):
    """Возвращает (path, index, name). Ищет шрифт, покрывающий нужные символы."""
    if explicit:
        return explicit, 0, os.path.basename(explicit)

    for path, want_style in FONT_CANDIDATES.get(platform.system(), []):
        if not os.path.isfile(path):
            continue
        if want_style:  # .ttc: ищем нужное начертание среди вложенных
            for idx in range(12):
                try:
                    f = ImageFont.truetype(path, 24, index=idx)
                except Exception:
                    break
                name = " ".join(f.getname())
                low = name.lower()
                if want_style.lower() in low and "italic" not in low and "oblique" not in low:
                    if font_covers(path, idx, sample_text):
                        return path, idx, name
        else:
            if font_covers(path, 0, sample_text):
                try:
                    f = ImageFont.truetype(path, 24)
                    return path, 0, " ".join(f.getname())
                except Exception:
                    continue

    for path, _ in FONT_CANDIDATES.get(platform.system(), []):
        if os.path.isfile(path):
            return path, 0, os.path.basename(path) + " (без проверки глифов)"
    sys.exit("Не найден системный шрифт. Укажите его явно: --font /путь/к/шрифту.ttf")


def find_upscaler(explicit=None):
    is_windows = platform.system() == "Windows"
    for d in ([explicit] if explicit else []) + UPSCALER_DIRS:
        if not d:
            continue
        for name in UPSCALER_NAMES:
            binary = os.path.join(d, name)
            # на Windows бит исполняемости не значит ничего — достаточно наличия файла
            if os.path.isfile(binary) and (is_windows or os.access(binary, os.X_OK)):
                return binary, os.path.join(d, "models")
    for name in UPSCALER_NAMES:
        found = shutil.which(name)
        if found:
            return found, None
    return None, None


def upscale(src, dst, binary, models, scale=4):
    cmd = [binary, "-i", src, "-o", dst, "-n", "realesrgan-x4plus", "-s", str(scale)]
    if models and os.path.isdir(models):
        cmd += ["-m", models]
    subprocess.run(cmd, check=True, capture_output=True)


# --- режим overlay: найти капсулу, нарисованную моделью ---
def bfs_component(light, start, max_w, max_h):
    h, w = light.shape
    seen = {start}
    q = deque([start])
    minx = maxx = start[0]
    miny = maxy = start[1]
    while q:
        cx, cy = q.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = cx + dx, cy + dy
            if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in seen and light[ny, nx]:
                if abs(nx - start[0]) > max_w or abs(ny - start[1]) > max_h:
                    continue
                seen.add((nx, ny))
                q.append((nx, ny))
                minx, maxx = min(minx, nx), max(maxx, nx)
                miny, maxy = min(miny, ny), max(maxy, ny)
    return minx, miny, maxx, maxy, seen


def find_capsule(arr, seed_xy, scale):
    h, w, _ = arr.shape
    sx, sy = seed_xy
    win = int(45 * scale)
    min_pixels = int(500 * scale * scale)
    x0, x1 = max(0, sx - win), min(w, sx + win)
    y0, y1 = max(0, sy - win), min(h, sy + win)
    minv = arr.min(axis=2)
    for thr in (248, 241, 235):
        light = minv > thr
        excluded = np.zeros_like(light)
        for _ in range(6):
            sub = np.where(excluded[y0:y1, x0:x1], 0, minv[y0:y1, x0:x1])
            if sub.max() <= thr:
                break
            yy, xx = np.unravel_index(np.argmax(sub), sub.shape)
            minx, miny, maxx, maxy, seen = bfs_component(
                light, (x0 + xx, y0 + yy), int(300 * scale), int(46 * scale))
            if len(seen) >= min_pixels and (maxx - minx) > 2.8 * (maxy - miny):
                return minx, miny, maxx, maxy
            for (px, py) in seen:
                excluded[py, px] = True
    return None


def capsule_center(item, W, H, width, cap_h, default_gap):
    """Где встанет центр капсулы.

    Есть anchor — считаем от точки: ширину капсулы знает только скрипт,
    поэтому и зазор выдерживает он, одинаковый у всех подписей.
    Нет anchor — старое поведение: координата и есть центр.
    """
    if "anchor" in item:
        ax, ay = item["anchor"][0] * W, item["anchor"][1] * H
        gap = item.get("gap", default_gap) * W
        side = item.get("side", "left")
        if side not in SIDES:
            sys.exit(f"Неизвестная сторона «{side}» у подписи «{item['text']}». "
                     f"Допустимые: {', '.join(SIDES)}")
        if side == "left":
            return ax - gap - width / 2, ay
        if side == "right":
            return ax + gap + width / 2, ay
        if side == "above":
            return ax, ay - gap - cap_h / 2
        return ax, ay + gap + cap_h / 2  # below
    if "x" not in item or "y" not in item:
        sys.exit(f"У подписи «{item['text']}» нет ни anchor, ни пары x/y.")
    return item["x"] * W, item["y"] * H


def draw_labels(img, labels, font_path, font_idx, mode, size_ratio,
                text_color, capsule_color, dot_color, default_gap):
    W, H = img.size
    cap_h = max(14, int(H * size_ratio))
    font = ImageFont.truetype(font_path, max(9, int(cap_h * 0.60)), index=font_idx)

    overlay_boxes = None
    if mode == "overlay":
        arr = np.array(img.convert("RGB"))
        scale = W / 1376.0  # пороги калиброваны под типовой вывод модели
        overlay_boxes = []
        for item in labels:
            seed_x = item.get("x", item.get("anchor", [0, 0])[0])
            seed_y = item.get("y", item.get("anchor", [0, 0])[1])
            box = find_capsule(arr, (int(seed_x * W), int(seed_y * H)), scale)
            if box is None:
                print(f"  !! капсула не найдена: {item['text']} — проверьте координаты "
                      f"или используйте режим place", file=sys.stderr)
                return None
            overlay_boxes.append(box)
            cap_h = max(cap_h, box[3] - box[1] + 1)
        font = ImageFont.truetype(font_path, max(9, int(cap_h * 0.60)), index=font_idx)

    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    sh_draw = ImageDraw.Draw(shadow)
    top = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(top)
    blur = max(1.0, cap_h * 0.09)

    for i, item in enumerate(labels):
        text = item["text"]
        tw = draw.textlength(text, font=font)
        pad = cap_h * 0.52
        width = tw + 2 * pad

        if overlay_boxes is not None:
            minx, miny, maxx, maxy = overlay_boxes[i]
            cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
            width = max(width, maxx - minx + 1)
        else:
            cx, cy = capsule_center(item, W, H, width, cap_h, default_gap)

        dot = item.get("dot")
        if dot is True and "anchor" in item:   # нарисовать точку прямо в якоре
            dot = item["anchor"]
        if dot:
            if dot_color is None:
                sys.exit("У подписи есть точка, но не задан её цвет. Укажите --dot-color "
                         "цветом маршрута из вашего паспорта стиля, например --dot-color C25B3A.")
            r = cap_h * 0.22
            dx, dy = dot[0] * W, dot[1] * H
            sh_draw.ellipse([dx - r, dy - r + blur, dx + r, dy + r + blur],
                            fill=(20, 30, 40, 70))
            draw.ellipse([dx - r, dy - r, dx + r, dy + r], fill=dot_color,
                         outline=(255, 255, 255, 255), width=max(1, int(cap_h * 0.06)))

        x0, x1 = cx - width / 2, cx + width / 2
        y0, y1 = cy - cap_h / 2, cy + cap_h / 2
        radius = cap_h / 2
        sh_draw.rounded_rectangle([x0, y0 + blur, x1, y1 + blur], radius=radius,
                                  fill=(20, 30, 40, 80))
        draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=capsule_color)
        draw.text((cx, cy - cap_h * 0.04), text, font=font, fill=text_color, anchor="mm")

        if not (0 <= x0 and x1 <= W and 0 <= y0 and y1 <= H):
            print(f"  !! подпись «{text}» вылезает за край кадра — подвиньте anchor "
                  f"или смените side", file=sys.stderr)

    shadow = shadow.filter(ImageFilter.GaussianBlur(blur))
    out = Image.alpha_composite(img.convert("RGBA"), shadow)
    return Image.alpha_composite(out, top)


def save_grid(img, path, step=0.05):
    """Копия карты с координатной сеткой — чтобы снимать anchor не на глаз."""
    W, H = img.size
    grid = img.convert("RGB").copy()
    draw = ImageDraw.Draw(grid, "RGBA")
    font_path, font_idx, _ = resolve_font("0123456789.")
    font = ImageFont.truetype(font_path, max(10, int(H * 0.018)), index=font_idx)
    n = int(round(1 / step))
    for i in range(n + 1):
        v = i * step
        x, y = v * W, v * H
        major = i % 2 == 0
        color = (255, 60, 60, 190) if major else (255, 255, 255, 110)
        draw.line([(x, 0), (x, H)], fill=color, width=1)
        draw.line([(0, y), (W, y)], fill=color, width=1)
        if major:
            label = f"{v:.2f}"
            draw.rectangle([x + 2, 2, x + 4 + font.getlength(label), 4 + font.size],
                           fill=(0, 0, 0, 150))
            draw.text((x + 3, 3), label, font=font, fill=(255, 255, 255, 255))
            draw.rectangle([2, y + 2, 4 + font.getlength(label), y + 4 + font.size],
                           fill=(0, 0, 0, 150))
            draw.text((3, y + 3), label, font=font, fill=(255, 255, 255, 255))
    grid.save(path)
    return path


def parse_color(value, default_alpha=255):
    value = value.strip().lstrip("#")
    if len(value) == 6:
        r, g, b = (int(value[i:i + 2], 16) for i in (0, 2, 4))
        return (r, g, b, default_alpha)
    if len(value) == 8:
        r, g, b, a = (int(value[i:i + 2], 16) for i in (0, 2, 4, 6))
        return (r, g, b, a)
    raise argparse.ArgumentTypeError(f"цвет должен быть RRGGBB или RRGGBBAA, получено: {value}")


def main():
    ap = argparse.ArgumentParser(description="route-atlas: подписи + разрешение")
    ap.add_argument("--input", required=True, help="карта, сгенерированная моделью")
    ap.add_argument("--labels", required=True, help="JSON с подписями")
    ap.add_argument("--output", required=True, help="итоговый файл (png/jpg)")
    ap.add_argument("--mode", choices=["place", "overlay"], default="place")
    ap.add_argument("--font", help="путь к шрифту (иначе подбирается системный)")
    ap.add_argument("--font-size-ratio", type=float, default=0.031,
                    help="высота капсулы в долях высоты кадра (по умолчанию 0.031)")
    ap.add_argument("--gap", type=float, default=DEFAULT_GAP,
                    help="зазор от точки до капсулы в долях ширины кадра (по умолчанию 0.006)")
    ap.add_argument("--text-color", type=parse_color, default=parse_color("303036"))
    ap.add_argument("--capsule-color", type=parse_color, default=parse_color("FFFFFF"))
    ap.add_argument("--dot-color", type=parse_color, default=None,
                    help="цвет точек-маркеров — берите цвет маршрута из паспорта стиля")
    ap.add_argument("--grid", action="store_true",
                    help="сохранить копию с координатной сеткой (для снятия anchor)")
    ap.add_argument("--no-upscale", action="store_true")
    ap.add_argument("--upscaler-dir", help="папка с realesrgan-ncnn-vulkan")
    ap.add_argument("--also-half", action="store_true",
                    help="дополнительно сохранить версию в половину размера (для веба)")
    args = ap.parse_args()

    with open(args.labels, encoding="utf-8") as fh:
        labels = json.load(fh)
    if not labels:
        sys.exit("Список подписей пуст.")

    sample = "".join(item["text"] for item in labels)
    font_path, font_idx, font_name = resolve_font(sample, args.font)
    print(f"Шрифт: {font_name}")

    # Сетка — инструмент для подбора координат, поэтому рисуется ДО апскейла,
    # в исходном разрешении: файл лёгкий и готов сразу, ждать Real-ESRGAN незачем.
    if args.grid:
        grid_path = os.path.splitext(args.output)[0] + "-grid.png"
        save_grid(Image.open(args.input), grid_path)
        print(f"-> {grid_path} (сетка 0.05 для снятия anchor)")

    source = args.input
    if not args.no_upscale:
        binary, models = find_upscaler(args.upscaler_dir)
        if binary:
            tmp = os.path.join(tempfile.gettempdir(), "route-atlas-upscaled.png")
            print("Апскейл Real-ESRGAN x4...")
            try:
                upscale(source, tmp, binary, models)
                source = tmp
            except subprocess.CalledProcessError as exc:
                print(f"Апскейл не удался ({exc}), продолжаю без него.", file=sys.stderr)
        else:
            print(upscaler_howto(), file=sys.stderr)
            print("Пока увеличиваю мягким Lanczos ×2 — это не даёт резкости "
                  "Real-ESRGAN, но лучше, чем исходный размер.\n", file=sys.stderr)
            img0 = Image.open(source)
            tmp = os.path.join(tempfile.gettempdir(), "route-atlas-lanczos.png")
            img0.resize((img0.width * 2, img0.height * 2), Image.LANCZOS).save(tmp)
            source = tmp

    img = Image.open(source)
    print(f"Холст: {img.size[0]}x{img.size[1]}, подписей: {len(labels)}")

    result = draw_labels(img, labels, font_path, font_idx, args.mode,
                         args.font_size_ratio, args.text_color,
                         args.capsule_color, args.dot_color, args.gap)
    if result is None:
        sys.exit(1)

    os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
    rgb = result.convert("RGB")
    rgb.save(args.output, quality=95)
    print(f"-> {args.output} ({rgb.size[0]}x{rgb.size[1]})")

    if args.also_half:
        half_path = os.path.splitext(args.output)[0] + "-half.jpg"
        rgb.resize((rgb.size[0] // 2, rgb.size[1] // 2), Image.LANCZOS).save(
            half_path, quality=92)
        print(f"-> {half_path} ({rgb.size[0] // 2}x{rgb.size[1] // 2})")


if __name__ == "__main__":
    main()
