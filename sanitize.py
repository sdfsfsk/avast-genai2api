"""One-shot sanitiser: replace machine-local credentials with placeholders.

Run from the repository root. It rewrites every published text file that
carries secrets recovered on the author's machine, writes src/config.example.json
and a .gitignore, and reports what changed.

src/config.json is deliberately left alone: it is gitignored, and rewriting it
would break the working install on this machine.
"""
from __future__ import annotations

import os
import sys

REPLACEMENTS = [
    # the shared client key from [ScamAssistant] in config.def
    ("YOUR_ASSISTANT_KEY", "YOUR_ASSISTANT_KEY"),
    # the author's Avast account UUID
    ("YOUR_ACCOUNT_UUID", "YOUR_ACCOUNT_UUID"),
    # the author's licence key
    ("YOUR_LICENCE_KEY", "YOUR_LICENCE_KEY"),
    # tenant id observed on the author's install
    ("YOUR_TENANT_UUID", "YOUR_TENANT_UUID"),
]

TEXT_EXT = {".py", ".md", ".json", ".ps1", ".cmd", ".txt", ".js", ".toml", ".cfg"}

SKIP_DIRS = {".git", "__pycache__", "certs"}
SKIP_FILES = {"src/config.json"}

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
  "origin_ips": []
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


def sanitize(root: str) -> list:
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
            for needle, placeholder in REPLACEMENTS:
                if needle in text:
                    count += text.count(needle)
                    text = text.replace(needle, placeholder)
            if count:
                with open(path, "w", encoding="utf-8", newline="") as fh:
                    fh.write(text)
                changed.append((rel, count))
    return changed


def write_if_absent(path: str, content: str) -> bool:
    if os.path.exists(path):
        return False
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)
    return True


def main() -> int:
    root = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")

    changed = sanitize(root)
    print("sanitised files:")
    if not changed:
        print("  (nothing found - already clean?)")
    for rel, count in changed:
        print(f"  {rel}  ({count} replacements)")

    example = os.path.join(root, "src", "config.example.json")
    if write_if_absent(example, EXAMPLE):
        print(f"wrote {os.path.relpath(example, root)}")

    gi = os.path.join(root, ".gitignore")
    with open(gi, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(GITIGNORE)
    print(f"wrote {os.path.relpath(gi, root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
