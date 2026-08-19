#!/usr/bin/env python3
"""route-atlas: проверка готовности окружения.

Показывает, что уже есть и чего не хватает, с точными командами для установки.
Ключей не печатает и не просит — только факт подключения.

Запуск:  python3 check_setup.py
"""
import importlib
import os
import platform
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

OK, WARN, MISS = "✓", "!", "·"


def line(mark, title, detail=""):
    print(f"  {mark} {title}" + (f" — {detail}" if detail else ""))


def check_python():
    print("\nБиблиотеки Python")
    required = {"PIL": "pillow", "numpy": "numpy", "requests": "requests"}
    optional = {"fontTools": "fonttools", "keyring": "keyring"}
    missing = []
    for module, package in required.items():
        try:
            importlib.import_module(module)
            line(OK, package)
        except ImportError:
            line(MISS, package, "обязательна")
            missing.append(package)
    is_windows = platform.system() == "Windows"
    for module, package in optional.items():
        try:
            importlib.import_module(module)
            line(OK, package, "необязательная")
        except ImportError:
            if package == "fonttools":
                line(WARN, package, "необязательная: проверка глифов шрифта")
            elif is_windows:
                # на Windows это почти обязательная: файл .env защищён слабее,
                # чем запись в Диспетчере учётных данных
                line(WARN, package, "на Windows желательна: ключ ляжет "
                                    "в Диспетчер учётных данных, а не в файл")
            else:
                line(WARN, package, "необязательная: хранение ключа "
                                    "в системном хранилище секретов")
    if missing:
        print(f"\n    Установить:  pip3 install {' '.join(missing)}")
    return not missing


def check_backends():
    print("\nДвижок генерации")
    try:
        from setup_key import BACKENDS, stored_key, verify
    except Exception as exc:
        line(MISS, "не удалось проверить", str(exc))
        return False
    working = False
    for name, cfg in BACKENDS.items():
        key, source = stored_key(name)
        if not key:
            line(MISS, name, "не подключён")
            continue
        ok, message = verify(name, key)
        line(OK if ok else WARN, name, f"{source}; {message}")
        working = working or ok
    if not working:
        print("\n    Вариант 1 — свой ключ (бесплатный тариф у Google есть):")
        print("        python3 setup_key.py --backend gemini")
        print("    Вариант 2 — у вас уже подключён MCP или скилл рисования:")
        print("        отдельный ключ не нужен, ассистент вызовет их напрямую.")
    return working


def check_fonts():
    print("\nШрифт для подписей")
    try:
        from finalize import resolve_font
        path, index, name = resolve_font("Азбука Cyrillic Ёё")
        line(OK, name, path)
        return True
    except SystemExit as exc:
        line(MISS, "не найден", str(exc))
        return False
    except Exception as exc:
        line(WARN, "проверка не удалась", str(exc))
        return False


def check_upscaler():
    print("\nПовышение разрешения (необязательно)")
    try:
        from finalize import find_upscaler, UPSCALER_HOWTO
    except Exception as exc:
        line(WARN, "проверка не удалась", str(exc))
        return False
    binary, _ = find_upscaler()
    if binary:
        line(OK, "Real-ESRGAN", binary)
        return True
    line(WARN, "Real-ESRGAN не найден", "карты будут в исходном разрешении")
    print("\n    " + UPSCALER_HOWTO.replace("\n", "\n    "))
    return False


def main():
    print("=" * 62)
    print(f"route-atlas — проверка окружения ({platform.system()}, "
          f"Python {sys.version.split()[0]})")
    print("=" * 62)

    deps = check_python()
    backend = check_backends()
    fonts = check_fonts()
    check_upscaler()

    print("\n" + "=" * 62)
    if deps and backend and fonts:
        print("Готово к работе. Скажите ассистенту: «нарисуй карту маршрута»")
        print("и приложите скриншот маршрута с карт.")
        code = 0
    else:
        print("Не хватает обязательного — см. команды выше.")
        code = 1
    print("=" * 62)
    sys.exit(code)


if __name__ == "__main__":
    main()
