#!/usr/bin/env python3
"""route-atlas: безопасное подключение API-ключа.

Ключ вводится ВАМИ, вручную, в невидимом поле. Он не проходит через чат,
не попадает в историю команд и не виден ассистенту — тот узнаёт только
результат проверки: «ключ рабочий» или «ключ не принят».

Куда кладётся (по убыванию надёжности):
  1. Системное хранилище секретов — если установлена библиотека keyring:
     Связка ключей на macOS, Диспетчер учётных данных на Windows,
     Secret Service на Linux. Рекомендуемый путь: pip install keyring
  2. Файл .env рядом с проектом, закрытый от посторонних и от git.
     Как именно закрыт, зависит от системы: на macOS и Linux — права 600,
     на Windows — icacls (права вида 600 там ничего не значат).

Запуск:  python3 setup_key.py            (спросит, какой сервис)
         python3 setup_key.py --backend gemini
         python3 setup_key.py --status    (только проверить, что подключено)
         python3 setup_key.py --forget    (удалить сохранённый ключ)
"""
import argparse
import getpass
import os
import platform
import stat
import subprocess
import sys

try:
    import requests
except ImportError:
    sys.exit("Нужна библиотека requests:  pip3 install requests")

try:
    import keyring
    HAS_KEYRING = True
except ImportError:
    HAS_KEYRING = False

SERVICE = "route-atlas"
BACKENDS = {
    "gemini": {
        "title": "Google AI (Gemini) — рекомендуется для карт",
        "env": "GOOGLE_AI_API_KEY",
        "alt_env": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        "get_url": "https://aistudio.google.com/apikey",
        "check_url": "https://generativelanguage.googleapis.com/v1beta/models",
        "header": lambda k: {"x-goog-api-key": k},
        "note": "Есть бесплатный тариф. В режиме редактирования сохраняет\n"
                "     географию исходного скриншота — для карт это решающее.",
    },
    "openai": {
        "title": "OpenAI (GPT Image)",
        "env": "OPENAI_API_KEY",
        "alt_env": (),
        "get_url": "https://platform.openai.com/api-keys",
        "check_url": "https://api.openai.com/v1/models",
        "header": lambda k: {"Authorization": f"Bearer {k}"},
        "note": "Нужен пополненный баланс. Географию исходника держит хуже:\n"
                "     референс для него подсказка, а не фиксация.",
    },
}
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(PROJECT_ROOT, ".env")


def read_env_file():
    values = {}
    try:
        with open(ENV_PATH, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    values[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return values


def stored_key(backend):
    """Ищет ключ, НЕ показывая его. Возвращает (значение, источник) или (None, None)."""
    cfg = BACKENDS[backend]
    for name in (cfg["env"],) + cfg["alt_env"]:
        if os.environ.get(name):
            return os.environ[name], f"переменная окружения {name}"
    if HAS_KEYRING:
        try:
            value = keyring.get_password(SERVICE, backend)
            if value:
                return value, "системное хранилище секретов"
        except Exception:
            pass
    values = read_env_file()
    for name in (cfg["env"],) + cfg["alt_env"]:
        if values.get(name):
            return values[name], f"файл .env ({name})"
    return None, None


def verify(backend, key):
    cfg = BACKENDS[backend]
    try:
        resp = requests.get(cfg["check_url"], headers=cfg["header"](key), timeout=30)
    except requests.RequestException as exc:
        return False, f"сеть недоступна: {exc}"
    if resp.status_code == 200:
        return True, "ключ принят сервисом"
    if resp.status_code in (401, 403):
        return False, "сервис отклонил ключ (неверный или без нужных прав)"
    if resp.status_code == 429:
        return True, "ключ похож на рабочий, но исчерпана квота запросов"
    return False, f"неожиданный ответ сервиса: {resp.status_code}"


def restrict_file_access(path):
    """Закрывает файл от посторонних. Возвращает (защищён, чем именно).

    Права вида 600 — это мир macOS и Linux. На Windows они не значат ничего,
    поэтому там доступ ограничивается штатным icacls: снимается наследование
    и остаётся одна учётная запись — ваша.
    """
    if platform.system() == "Windows":
        user = os.environ.get("USERNAME") or os.environ.get("USER")
        if not user:
            return False, "не удалось определить учётную запись"
        try:
            subprocess.run(["icacls", path, "/inheritance:r", "/grant:r", f"{user}:F"],
                           check=True, capture_output=True)
            return True, "доступ только у вашей учётной записи (icacls)"
        except Exception as exc:
            return False, f"icacls не отработал ({exc})"
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    return True, "права 600, только владелец"


def save_to_env_file(cfg, key):
    values = read_env_file()
    values[cfg["env"]] = key
    with open(ENV_PATH, "w", encoding="utf-8") as fh:
        fh.write("# route-atlas: секреты. НЕ коммитить, НЕ пересылать.\n")
        for k, v in values.items():
            fh.write(f"{k}={v}\n")
    protected, how = restrict_file_access(ENV_PATH)

    gitignore = os.path.join(PROJECT_ROOT, ".gitignore")
    lines = []
    if os.path.isfile(gitignore):
        with open(gitignore, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    if ".env" not in lines:
        with open(gitignore, "a", encoding="utf-8") as fh:
            fh.write("\n# секреты\n.env\n")
    return protected, how


def save(backend, key):
    if HAS_KEYRING:
        try:
            keyring.set_password(SERVICE, backend, key)
            store = ("Диспетчер учётных данных Windows"
                     if platform.system() == "Windows" else "системное хранилище секретов")
            return store
        except Exception:
            pass

    if platform.system() == "Windows":
        print("\n⚠️  Библиотека keyring не установлена, поэтому ключ ляжет в файл .env.")
        print("    На Windows файл защищён слабее, чем запись в Диспетчере учётных данных.")
        print("    Надёжнее прервать (Ctrl+C), выполнить  pip install keyring  и повторить.")

    protected, how = save_to_env_file(BACKENDS[backend], key)
    suffix = how if protected else f"⚠️  ФАЙЛ НЕ ЗАЩИЩЁН: {how}"
    return f"{ENV_PATH}\n  ({suffix}; добавлен в .gitignore)"


def show_status():
    print("Подключение к сервисам генерации:\n")
    any_ok = False
    for name, cfg in BACKENDS.items():
        key, source = stored_key(name)
        if key:
            ok, message = verify(name, key)
            mark = "✓" if ok else "✗"
            print(f"  {mark} {name:7} — {source}; {message}")
            any_ok = any_ok or ok
        else:
            print(f"  ·  {name:7} — не подключён")
    if not any_ok:
        print("\nНи одного рабочего ключа. Запустите: python3 setup_key.py")
    if not HAS_KEYRING:
        print("\nСовет: pip3 install keyring — тогда ключ ляжет в системное\n"
              "хранилище секретов вместо файла .env.")
    return 0 if any_ok else 1


def choose_backend():
    print("Какой сервис подключаем?\n")
    names = list(BACKENDS)
    for i, name in enumerate(names, 1):
        cfg = BACKENDS[name]
        print(f"  [{i}] {cfg['title']}\n      {cfg['note']}\n")
    while True:
        raw = input(f"Номер (1-{len(names)}), Enter = 1: ").strip() or "1"
        if raw.isdigit() and 1 <= int(raw) <= len(names):
            return names[int(raw) - 1]
        print("Не понял, попробуйте ещё раз.")


def main():
    ap = argparse.ArgumentParser(description="Безопасное подключение API-ключа")
    ap.add_argument("--backend", choices=list(BACKENDS))
    ap.add_argument("--status", action="store_true", help="показать, что подключено")
    ap.add_argument("--forget", action="store_true", help="удалить сохранённый ключ")
    args = ap.parse_args()

    if args.status:
        sys.exit(show_status())

    backend = args.backend or (choose_backend() if not args.forget else "gemini")

    if args.forget:
        if HAS_KEYRING:
            try:
                keyring.delete_password(SERVICE, backend)
            except Exception:
                pass
        values = read_env_file()
        if values.pop(BACKENDS[backend]["env"], None) is not None:
            with open(ENV_PATH, "w", encoding="utf-8") as fh:
                for k, v in values.items():
                    fh.write(f"{k}={v}\n")
            os.chmod(ENV_PATH, stat.S_IRUSR | stat.S_IWUSR)
        print(f"Ключ {backend} удалён из хранилищ, которыми управляет скрипт.")
        return

    cfg = BACKENDS[backend]
    existing, source = stored_key(backend)
    if existing:
        print(f"Ключ {backend} уже подключён ({source}).")
        if (input("Заменить? [y/N]: ").strip().lower() or "n") != "y":
            return

    print(f"\nГде взять ключ: {cfg['get_url']}")
    print("\nВставьте ключ — поле НЕ показывает символы, это нормально.")
    print("Ключ никуда не отправляется, кроме самого сервиса, и не пишется в историю команд.")
    try:
        key = getpass.getpass("Ключ: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nОтменено.")
        return
    if not key:
        sys.exit("Пустой ввод — ничего не сохранено.")

    print("\nПроверяю ключ у сервиса...")
    ok, message = verify(backend, key)
    if not ok:
        sys.exit(f"✗ {message}. Ничего не сохранено.")

    where = save(backend, key)
    print(f"✓ {message}")
    print(f"✓ Сохранено: {where}")
    print("\nГотово. Скрипты route-atlas найдут ключ сами — передавать его\n"
          "в командах или в переписке не нужно никогда.")


if __name__ == "__main__":
    main()
