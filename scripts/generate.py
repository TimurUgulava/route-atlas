#!/usr/bin/env python3
"""route-atlas: универсальный слой генерации изображений.

Нужен только тем, у кого НЕТ подключённого MCP или скилла рисования: работает
напрямую по API-ключу. Если MCP есть — ассистент вызывает его сам, этот скрипт
не нужен.

Бэкенды:
  gemini  (по умолчанию) — Google AI. Единственный, кто в режиме редактирования
          надёжно сохраняет географию исходного скриншота.
  openai  — GPT Image. Референс работает как стилевая подсказка, а не фиксация:
          картинка красивая, берег и маршрут поплывут. Для карт — запасной путь.

Ключ подключается один раз через setup_key.py и дальше ищется сам:
переменные окружения → системное хранилище секретов → .env с правами 600.
Передать ключ аргументом нельзя намеренно — аргументы видны в списке процессов
и остаются в истории оболочки.

Примеры:
  python3 setup_key.py                       # один раз: подключить ключ
  python3 generate.py --prompt "..." --input map.jpg --output out.png
  python3 generate.py --prompt "..." --input map.jpg --reference style.png \
      --aspect 16:9 --output out.png
  python3 generate.py --list-backends
"""
import argparse
import base64
import json
import mimetypes
import os
import sys

try:
    import requests
except ImportError:
    sys.exit("Нужна библиотека requests:  pip3 install requests")

GEMINI_KEYS = ("GOOGLE_AI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY")
OPENAI_KEYS = ("OPENAI_API_KEY",)
GEMINI_MODEL = "gemini-3-pro-image-preview"
OPENAI_MODEL = "gpt-image-2"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
OPENAI_EDIT_URL = "https://api.openai.com/v1/images/edits"
OPENAI_GEN_URL = "https://api.openai.com/v1/images/generations"

HOWTO_GEMINI = """Ключ Google AI (Gemini) не подключён — бесплатный тариф есть.
  Подключение одной командой, ключ вводится в невидимом поле:
      python3 setup_key.py --backend gemini
  Где взять ключ: https://aistudio.google.com/apikey"""
HOWTO_OPENAI = """Ключ OpenAI не подключён.
      python3 setup_key.py --backend openai
  Где взять ключ: https://platform.openai.com/api-keys
  Нужен пополненный баланс; возможна верификация организации."""


def load_dotenv_values():
    """Читает .env рядом со скриптом и в текущей папке. Окружение приоритетнее."""
    values = {}
    here = os.path.dirname(os.path.abspath(__file__))
    for path in (os.path.join(here, ".env"), os.path.join(here, "..", ".env"), ".env"):
        try:
            with open(path) as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    values.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        except OSError:
            continue
    return values


def find_key(names, backend=None):
    """Ищет ключ: окружение → системное хранилище секретов → .env.

    Ключ намеренно НЕЛЬЗЯ передать аргументом командной строки: аргументы видны
    в списке процессов и оседают в истории оболочки. Подключение — через
    setup_key.py, он вводится вручную в невидимом поле.
    """
    for n in names:
        if os.environ.get(n):
            return os.environ[n]
    if backend:
        try:
            import keyring
            value = keyring.get_password("route-atlas", backend)
            if value:
                return value
        except Exception:
            pass
    dotenv = load_dotenv_values()
    for n in names:
        if dotenv.get(n):
            return dotenv[n]
    return None


def detect_backends():
    return {
        "gemini": bool(find_key(GEMINI_KEYS, "gemini")),
        "openai": bool(find_key(OPENAI_KEYS, "openai")),
    }


def b64_of(path):
    with open(path, "rb") as fh:
        return base64.b64encode(fh.read()).decode()


def mime_of(path):
    return mimetypes.guess_type(path)[0] or "image/png"


def run_gemini(args, key):
    parts = [{"text": args.prompt}]
    for path in [p for p in [args.input] if p] + list(args.reference or []):
        parts.append({"inline_data": {"mime_type": mime_of(path), "data": b64_of(path)}})

    body = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"responseModalities": ["IMAGE"]},
    }
    if args.aspect:
        body["generationConfig"]["imageConfig"] = {"aspectRatio": args.aspect}

    resp = requests.post(
        GEMINI_URL.format(model=args.model or GEMINI_MODEL),
        headers={"x-goog-api-key": key, "Content-Type": "application/json"},
        json=body, timeout=args.timeout)

    if resp.status_code != 200:
        detail = resp.text[:400]
        if resp.status_code in (401, 403):
            sys.exit(f"Google API отклонил ключ ({resp.status_code}).\n{HOWTO_GEMINI}\n{detail}")
        if resp.status_code == 429:
            sys.exit(f"Лимит запросов Google API (429). Подождите или поднимите квоту.\n{detail}")
        sys.exit(f"Ошибка Google API {resp.status_code}: {detail}")

    data = resp.json()
    for cand in data.get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            blob = part.get("inlineData") or part.get("inline_data")
            if blob and blob.get("data"):
                return base64.b64decode(blob["data"])
    reason = json.dumps(data)[:400]
    sys.exit("Модель не вернула изображение (возможна модерация промпта).\n" + reason)


def run_openai(args, key):
    headers = {"Authorization": f"Bearer {key}"}
    model = args.model or OPENAI_MODEL
    if args.input:
        files = []
        opened = []
        for path in [args.input] + list(args.reference or []):
            fh = open(path, "rb")
            opened.append(fh)
            files.append(("image[]", (os.path.basename(path), fh, mime_of(path))))
        payload = {"model": model, "prompt": args.prompt, "quality": "high"}
        if args.size:
            payload["size"] = args.size
        try:
            resp = requests.post(OPENAI_EDIT_URL, headers=headers, data=payload,
                                 files=files, timeout=args.timeout)
        finally:
            for fh in opened:
                fh.close()
    else:
        payload = {"model": model, "prompt": args.prompt, "quality": "high"}
        if args.size:
            payload["size"] = args.size
        resp = requests.post(OPENAI_GEN_URL, headers={**headers,
                             "Content-Type": "application/json"},
                             json=payload, timeout=args.timeout)

    if resp.status_code != 200:
        detail = resp.text[:400]
        if resp.status_code == 401:
            sys.exit(f"OpenAI отклонил ключ (401).\n{HOWTO_OPENAI}\n{detail}")
        if resp.status_code == 403:
            sys.exit("OpenAI требует верификации организации для этой модели (403).\n"
                     "https://platform.openai.com/settings/organization/general\n" + detail)
        sys.exit(f"Ошибка OpenAI {resp.status_code}: {detail}")

    data = resp.json()
    try:
        return base64.b64decode(data["data"][0]["b64_json"])
    except (KeyError, IndexError):
        sys.exit("OpenAI не вернул изображение: " + json.dumps(data)[:400])


def main():
    ap = argparse.ArgumentParser(description="route-atlas: генерация карты через доступный API")
    ap.add_argument("--prompt", help="текст промпта")
    ap.add_argument("--input", help="исходное изображение (скриншот карты) для режима редактирования")
    ap.add_argument("--reference", action="append", help="референс стиля (можно несколько)")
    ap.add_argument("--output", help="куда сохранить результат")
    ap.add_argument("--backend", choices=["auto", "gemini", "openai"], default="auto")
    ap.add_argument("--model", help="переопределить модель бэкенда")
    ap.add_argument("--aspect", default="16:9", help="пропорция для gemini (16:9, 3:2, 1:1, ...)")
    ap.add_argument("--size", help="размер для openai (1536x1024, 1024x1024, ...)")
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--list-backends", action="store_true", help="показать, что доступно, и выйти")
    args = ap.parse_args()

    available = detect_backends()
    if args.list_backends:
        print(json.dumps(available, indent=2))
        if not any(available.values()):
            print("\nНи одного ключа не найдено.\n\n" + HOWTO_GEMINI)
        return

    if not args.prompt or not args.output:
        ap.error("нужны --prompt и --output (или --list-backends)")

    backend = args.backend
    if backend == "auto":
        if available["gemini"]:
            backend = "gemini"
        elif available["openai"]:
            backend = "openai"
            print("⚠️  Ключа Google AI нет, работаю через OpenAI. Для карт это хуже: "
                  "география исходника будет искажена — модель перерисует берег по-своему.",
                  file=sys.stderr)
        else:
            sys.exit("Не найден ни один ключ.\n\n" + HOWTO_GEMINI + "\n\n" + HOWTO_OPENAI)

    keys = GEMINI_KEYS if backend == "gemini" else OPENAI_KEYS
    key = find_key(keys, backend)
    if not key:
        sys.exit((HOWTO_GEMINI if backend == "gemini" else HOWTO_OPENAI))

    runner = run_gemini if backend == "gemini" else run_openai
    image_bytes = runner(args, key)

    os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
    with open(args.output, "wb") as fh:
        fh.write(image_bytes)
    print(json.dumps({"backend": backend, "output": args.output,
                      "bytes": len(image_bytes)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
