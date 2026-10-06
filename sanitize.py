"""One-shot sanitiser: replace machine-local credentials with placeholders.

Reads the real values from src/config.json (which is gitignored) and rewrites
every *published* text file that carries them, then writes
src/config.example.json and .gitignore.

src/config.json itself is deliberately left alone: rewriting it would break the
working install on this machine.

Run from the repository root:
    python sanitize.py
"""
from __future__ import annotations

import json
import os
import sys

PLACEHOLDERS = {
    "authorization_token": "YOUR_ASSISTANT_KEY",
    "account_id": "YOUR_ACCOUNT_UUID",
    "subscription_id": "YOUR_LICENCE_KEY",
    "tenant_id": "YOUR_TENANT_UUID",
}

TEXT_EXT = {".py", ".md", ".json", ".ps1", ".cmd", ".txt", ".js", ".toml", ".cfg"}

SKIP_DIRS = {".git", "__pycache__", "certs"}
SKIP_FILES = {"src/config.json", "sanitize.py"}

EXAMPLE = """
{
  "authorization_token": "YOUR_ASSISTANT_KEY",
  "account_id": "YOUR_ACCOUNT_UUID",
  "subscription_id": "YOUR_LICENCE_KEY",
  "tenant_id": "YOUR_TENANT_UUID",
  "partner_id": "1062590",
  "partner_unit_id": "121686",
  "product_id": "scam_asst",
  "app_lang": "zh-cn",
  "response_modes": "1",
  "enabled_features": "0",
  "user_agent": "GES/26.10.11190.3848/Win/10.0/1",
  "rest_url": "https://genai-rest.avast.com",
  "ws_url": "wss://genai-ws.avast.com",
  "origin_ips": [],
  "persona": {
    "enabled": true,
    "mode": "inject",
    "template": "plain",
    "prompt": "你是「松子」，一只可爱的喵娘，是主人专属的助手。说话温柔活泼，句尾要加「喵」，自称用「松子」。",
    "rewrite": {
      "base": "http://127.0.0.1:7863/v1",
      "model": "",
      "api_key": "",
      "system": "",
      "timeout": 90
    }
  }
}
""".lstrip("\n")

GITIGNORE = "\n".join([
    "# --- local credentials (never publish) ---",
    "src/config.json",
    "",
    "# --- capture artifacts: live tokens and your own chat content ---",
    "capture/certs/",
    "capture/*.jsonl",
    "capture/*.out",
    "capture/*.log",
    "capture/*.backup",
    "capture/decoded.txt",
    "capture/key_opts.txt",
    "capture/ws_url.txt",
    "capture/screen*.png",
    "capture/hosts-acl.txt",
    "*.out",
    "*.bak",
    "",
    "# --- python ---",
    "__pycache__/",
    "*.pyc",
    ".venv/",
    "venv/",
    "",
    "# --- editors / os ---",
    ".vscode/",
    ".idea/",
    "Thumbs.db",
    "desktop.ini",
    "",
])


def load_secrets(root: str) -> list:
    """Real credential values, read from the gitignored live config."""
    path = os.path.join(root, "src", "config.json")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, json.JSONDecodeError):
        print(f"! cannot read {path} - nothing to sanitise from")
        return []
    out = []
    for field, placeholder in PLACEHOLDERS.items():
        value = str(cfg.get(field) or "").strip()
        if len(value) >= 8:            # ignore blanks and obvious placeholders
            out.append((value, placeholder))
    return out


def sanitize(root: str, secrets: list) -> list:
    changed = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            if rel in SKIP_FILES:
                continue
            if os.path.splitext(name)[1].lower() not in TEXT_EXT:
                continue
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    text = fh.read()
            except (OSError, UnicodeDecodeError):
                continue
            count = 0
            for needle, placeholder in secrets:
                if needle in text:
                    count += text.count(needle)
                    text = text.replace(needle, placeholder)
            if count:
                with open(path, "w", encoding="utf-8", newline="") as fh:
                    fh.write(text)
                changed.append((rel, count))
    return changed


def main() -> int:
    root = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")

    secrets = load_secrets(root)
    if not secrets:
        return 1
    print(f"loaded {len(secrets)} secret(s) from src/config.json:")
    for value, placeholder in secrets:
        print(f"  {value[:10]}…  ->  {placeholder}")

    changed = sanitize(root, secrets)
    print()
    print("sanitised files:")
    if not changed:
        print("  (nothing found - already clean?)")
    for rel, count in changed:
        print(f"  {rel}  ({count} replacements)")

    example = os.path.join(root, "src", "config.example.json")
    with open(example, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(EXAMPLE)
    print(f"wrote {os.path.relpath(example, root)}")

    gi = os.path.join(root, ".gitignore")
    with open(gi, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(GITIGNORE)
    print(f"wrote {os.path.relpath(gi, root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
