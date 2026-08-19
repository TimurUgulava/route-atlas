#!/usr/bin/env python3
"""route-atlas: установка Real-ESRGAN одной командой.

Определяет вашу систему, скачивает нужную сборку с GitHub Releases, распаковывает
в ~/.claude/tools/realesrgan и на macOS снимает карантин. Дальше finalize.py
находит апскейлер сам.

Зачем: без него карта остаётся в размере, который отдала модель (обычно
1376×768) — для статьи маловато, для печати мало совсем.

Запуск:  python3 install_upscaler.py
         python3 install_upscaler.py --check     только проверить, установлен ли
         python3 install_upscaler.py --force     переустановить поверх
"""
import argparse
import io
import os
import platform
import shutil
import stat
import subprocess
import sys
import zipfile

try:
    import requests
except ImportError:
    sys.exit("Нужна библиотека requests:  pip install requests")

RELEASE = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0"
ASSETS = {
    "Darwin": "realesrgan-ncnn-vulkan-20220424-macos.zip",
    "Windows": "realesrgan-ncnn-vulkan-20220424-windows.zip",
    "Linux": "realesrgan-ncnn-vulkan-20220424-ubuntu.zip",
}
TARGET = os.path.normpath(os.path.expanduser("~/.claude/tools/realesrgan"))
BINARY = ("realesrgan-ncnn-vulkan.exe" if platform.system() == "Windows"
          else "realesrgan-ncnn-vulkan")


def installed_at():
    path = os.path.join(TARGET, BINARY)
    return path if os.path.isfile(path) else None


def download(url):
    print(f"Качаю {url.rsplit('/', 1)[-1]} ...")
    resp = requests.get(url, stream=True, timeout=180)
    if resp.status_code != 200:
        sys.exit(f"Не удалось скачать ({resp.status_code}). Проверьте интернет "
                 f"или скачайте вручную: {url}")
    total = int(resp.headers.get("content-length", 0))
    buf = io.BytesIO()
    got = 0
    for chunk in resp.iter_content(chunk_size=262144):
        buf.write(chunk)
        got += len(chunk)
        if total:
            pct = got * 100 // total
            print(f"\r  {pct}%  ({got // 1048576} из {total // 1048576} МБ)",
                  end="", flush=True)
    print()
    buf.seek(0)
    return buf


def unpack(buf, target):
    os.makedirs(target, exist_ok=True)
    with zipfile.ZipFile(buf) as zf:
        # в архивах бывает вложенная папка — раскладываем плоско
        for member in zf.namelist():
            if member.endswith("/"):
                continue
            rel = member.split("/", 1)[1] if "/" in member and not member.startswith("models/") \
                else member
            dest = os.path.join(target, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with zf.open(member) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)


def make_runnable(target):
    binary = os.path.join(target, BINARY)
    if not os.path.isfile(binary):
        for root, _, files in os.walk(target):   # вдруг лежит глубже
            if BINARY in files:
                binary = os.path.join(root, BINARY)
                break
    if not os.path.isfile(binary):
        return None
    if platform.system() != "Windows":
        os.chmod(binary, os.stat(binary).st_mode | stat.S_IXUSR | stat.S_IXGRP)
    if platform.system() == "Darwin":
        # без снятия карантина macOS не даст запустить скачанный бинарник
        subprocess.run(["xattr", "-dr", "com.apple.quarantine", target],
                       capture_output=True)
    return binary


def main():
    ap = argparse.ArgumentParser(description="Установка Real-ESRGAN для route-atlas")
    ap.add_argument("--check", action="store_true", help="только проверить")
    ap.add_argument("--force", action="store_true", help="переустановить поверх")
    args = ap.parse_args()

    system = platform.system()
    existing = installed_at()

    if args.check:
        print(f"Система: {system}")
        print(f"Апскейлер: {os.path.normpath(existing) if existing else 'не установлен'}")
        sys.exit(0 if existing else 1)

    if existing and not args.force:
        print(f"Уже установлен: {os.path.normpath(existing)}\nПереустановить: --force")
        return

    if system not in ASSETS:
        sys.exit(f"Не знаю сборки под систему «{system}». Скачайте вручную: {RELEASE}")

    buf = download(f"{RELEASE}/{ASSETS[system]}")
    print(f"Распаковываю в {os.path.normpath(TARGET)} ...")
    unpack(buf, TARGET)
    binary = make_runnable(TARGET)

    if not binary:
        sys.exit(f"Распаковал, но не нашёл {BINARY} внутри. Посмотрите папку {os.path.normpath(TARGET)}.")

    try:
        subprocess.run([binary], capture_output=True, timeout=30)
        works = True
    except Exception as exc:
        works = False
        print(f"Проверка запуска не удалась: {exc}", file=sys.stderr)

    print(f"\n✓ Готово: {os.path.normpath(binary)}")
    if works:
        print("✓ Запускается. Карты теперь будут собираться в 4k.")
    else:
        print("! Файл на месте, но запустить не вышло. На Linux может не хватать "
              "драйверов Vulkan; карта всё равно соберётся, только без апскейла.")


if __name__ == "__main__":
    main()
