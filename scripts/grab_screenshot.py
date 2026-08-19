#!/usr/bin/env python3
"""route-atlas: достать скриншот из буфера обмена в файл.

Человек делает скриншот карты и держит его в буфере — ассистенту он оттуда
недоступен. Скрипт кладёт картинку из буфера в файл, кроссплатформенно.
Если в буфере пусто — показывает свежие картинки из типовых папок, чтобы
можно было взять последнюю.

Запуск:  python3 grab_screenshot.py --output screenshot.png
         python3 grab_screenshot.py --recent      только показать свежие файлы
"""
import argparse
import glob
import os
import platform
import subprocess
import sys
import time

try:
    from PIL import Image, ImageGrab
except ImportError:
    sys.exit("Нужен Pillow:  pip install pillow")

PICTURE_DIRS = ["~/Desktop", "~/Downloads", "~/Pictures", "~/Pictures/Screenshots",
                "~/OneDrive/Изображения", "~/OneDrive/Pictures", "~/Изображения"]
EXTS = ("png", "jpg", "jpeg", "webp", "bmp")


def from_clipboard():
    """Картинка из буфера. На Linux ImageGrab не работает — пробуем xclip."""
    try:
        img = ImageGrab.grabclipboard()
    except Exception:
        img = None
    if isinstance(img, Image.Image):
        return img
    if isinstance(img, list) and img:          # буфер содержит путь к файлу
        for entry in img:
            if os.path.isfile(entry):
                return Image.open(entry)
    if platform.system() == "Linux":
        for tool, args in (("xclip", ["-selection", "clipboard", "-t", "image/png", "-o"]),
                           ("wl-paste", ["--type", "image/png"])):
            binary = shutil_which(tool)
            if not binary:
                continue
            try:
                out = subprocess.run([binary] + args, capture_output=True, timeout=15)
                if out.returncode == 0 and out.stdout:
                    import io
                    return Image.open(io.BytesIO(out.stdout))
            except Exception:
                continue
    return None


def shutil_which(name):
    import shutil
    return shutil.which(name)


def recent_images(limit=8, max_age_hours=48, max_depth=3):
    """Свежие картинки в типовых папках, включая вложенные (скриншоты часто
    складывают в подпапки вроде Downloads/images/сессия)."""
    found = []
    now = time.time()
    for d in PICTURE_DIRS:
        base = os.path.expanduser(d)
        if not os.path.isdir(base):
            continue
        base_depth = base.rstrip(os.sep).count(os.sep)
        for root, dirs, files in os.walk(base):
            if root.rstrip(os.sep).count(os.sep) - base_depth >= max_depth:
                dirs[:] = []          # глубже не спускаемся
            dirs[:] = [x for x in dirs if not x.startswith(".")]
            for name in files:
                if not name.lower().rsplit(".", 1)[-1] in EXTS:
                    continue
                path = os.path.join(root, name)
                try:
                    mtime = os.path.getmtime(path)
                except OSError:
                    continue
                age = (now - mtime) / 3600
                if age <= max_age_hours:
                    found.append((mtime, path, age))
    found.sort(reverse=True)
    return found[:limit]


def show_recent():
    items = recent_images()
    if not items:
        print("Свежих картинок в Рабочем столе, Загрузках и Изображениях не нашлось.")
        return
    print("Свежие картинки (возможно, среди них ваш скриншот):\n")
    for _, path, age in items:
        hours = int(age)
        when = "меньше часа назад" if hours < 1 else f"{hours} ч назад"
        print(f"  {path}\n      {when}")


def main():
    ap = argparse.ArgumentParser(description="Скриншот из буфера обмена в файл")
    ap.add_argument("--output", help="куда сохранить (png)")
    ap.add_argument("--recent", action="store_true", help="показать свежие картинки и выйти")
    args = ap.parse_args()

    if args.recent:
        show_recent()
        return

    if not args.output:
        ap.error("нужен --output (или --recent)")

    img = from_clipboard()
    if img is None:
        print("В буфере обмена картинки нет.\n")
        show_recent()
        print("\nСкопируйте скриншот в буфер и повторите, либо укажите файл из списка выше.")
        sys.exit(1)

    os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
    img.convert("RGB").save(args.output)
    print(f"-> {args.output} ({img.size[0]}x{img.size[1]})")


if __name__ == "__main__":
    main()
