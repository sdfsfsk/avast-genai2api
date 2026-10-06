"""Create src/config.json from the Avast installation on this machine.

Every user of this project supplies their own credentials; nothing is shipped
in the repository. The values live in Avast's client configuration file:

    C:\\Program Files\\Avast Software\\Avast\\setup\\config.def

which is UTF-16 and holds a [ScamAssistant] section. Reading it needs
administrator rights (the file is protected by Avast self-defense), so run this
from an elevated prompt if the default path fails.

Usage:
    python init_config.py                 read the default config.def
    python init_config.py --path FILE     read a specific config.def
    python init_config.py --show          print the parsed values, write nothing
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

DEFAULT_DEF = r"C:\Program Files\Avast Software\Avast\setup\config.def"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

SECTION = "ScamAssistant"

TEMPLATE = {
    "authorization_token": "",
    "account_id": "",
    "subscription_id": "",
    "tenant_id": "",
    "partner_id": "",
    "partner_unit_id": "",
    "product_id": "scam_asst",
    "app_lang": "zh-cn",
    "response_modes": "1",
    "enabled_features": "0",
    "user_agent": "",
    "rest_url": "https://genai-rest.avast.com",
    "ws_url": "wss://genai-ws.avast.com",
    "origin_ips": [],
}


def read_text(path: str) -> str:
    raw = open(path, "rb").read()
    for enc in ("utf-16", "utf-16-le", "utf-8-sig", "utf-8", "latin-1"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return raw.decode("latin-1", "replace")


def parse_section(text: str, section: str) -> dict:
    values: dict[str, str] = {}
    inside = False
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            inside = line[1:-1].strip().lower() == section.lower()
            continue
        if not inside or "=" not in line or line.startswith(";"):
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def find_credentials() -> dict:
    """Read the ConfigKey + URLs from the Avast client configuration."""
    defs = [DEFAULT_DEF]
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    defs.append(os.path.join(program_files, "Avast Software", "Avast", "setup", "config.def"))
    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    defs.append(os.path.join(program_files_x86, "AVG", "Antivirus", "setup", "config.def"))

    for path in defs:
        if not os.path.exists(path):
            continue
        section = parse_section(read_text(path), SECTION)
        if section:
            return section | {"_source": path}
    raise SystemExit(
        "Could not find a [ScamAssistant] section.\n"
        f"Looked in:\n  " + "\n  ".join(defs) +
        "\n\nPass --path if Avast is installed elsewhere. Run as administrator "
        "if the file exists but cannot be read.")


LOG_DIRS = [
    r"C:\ProgramData\Avast Software\Avast\log",
    r"C:\ProgramData\Avast Software\AVG\log",
]

# The service log carries the very URL template the client builds, which is the
# easiest place to read the per-machine account and licence values from.
URL_KEYS = {
    "account-id": "account_id",
    "subscription-id": "subscription_id",
    "X-Gen-Partner-Id": "partner_id",
    "X-Gen-Partner-Unit-Id": "partner_unit_id",
    "X-Gen-Tenant-Id": "tenant_id",
    "app-lang": "app_lang",
    "supported-response-modes": "response_modes",
    "enabled-features": "enabled_features",
    "user-agent": "user_agent",
}


def _read_log(path: str) -> str:
    """Read a log file, falling back to findstr when Avast holds it locked."""
    try:
        with open(path, "rb") as fh:
            return fh.read().decode("utf-8", "replace")
    except OSError:
        pass
    try:
        proc = subprocess.run(
            ["findstr", "/C:genai-ws", "/C:Current psn", "/C:ACC=", path],
            capture_output=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return proc.stdout.decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return ""


def scrape_logs() -> dict:
    """Pull the URL query values out of Avast's own log files."""
    found: dict[str, str] = {}
    pattern = re.compile(r"[?&]([A-Za-z0-9_-]+)=([^&'\"]+)")
    acc_pattern = re.compile(r"ACC='([0-9a-fA-F-]{36})'")
    psn_pattern = re.compile(r"Current psn:\s*([A-Z0-9]{8,20})")

    for directory in LOG_DIRS:
        if not os.path.isdir(directory):
            continue
        for name in sorted(os.listdir(directory)):
            path = os.path.join(directory, name)
            blob = _read_log(path)
            if not blob:
                continue
            for key, value in pattern.findall(blob):
                if key in URL_KEYS and value and "{'+" not in value and value != "''":
                    found.setdefault(URL_KEYS[key], value)
            match = acc_pattern.search(blob)
            if match:
                found.setdefault("account_id", match.group(1))
            match = psn_pattern.search(blob)
            if match:
                found.setdefault("subscription_id", match.group(1))
    return found


def fill() -> dict:
    section = find_credentials()
    cfg = dict(TEMPLATE)
    cfg["authorization_token"] = section.get("Key", "")
    for key, field in (("RestUrl", "rest_url"), ("WSUrl", "ws_url")):
        if section.get(key):
            cfg[field] = section[key]
    if section.get("SupportedResponseModes"):
        cfg["response_modes"] = section["SupportedResponseModes"]
    if section.get("EnabledFeatures"):
        cfg["enabled_features"] = section["EnabledFeatures"]

    scraped = scrape_logs()
    for key, value in scraped.items():
        if key in cfg and value:
            cfg[key] = value

    cfg["_source"] = section["_source"]
    cfg["_scraped"] = ", ".join(sorted(scraped)) or "nothing"
    return cfg


def main() -> int:
    ap = argparse.ArgumentParser(description="Build config.json for avast-genai2api")
    ap.add_argument("--path", help="path to config.def")
    ap.add_argument("--show", action="store_true", help="print, do not write")
    ap.add_argument("--account-id", help="Avast account UUID (see README)")
    ap.add_argument("--subscription-id", help="Avast licence key (see README)")
    ap.add_argument("--tenant-id", help="X-Gen-Tenant-Id (see README)")
    ap.add_argument("--partner-id", default="")
    ap.add_argument("--partner-unit-id", default="")
    args = ap.parse_args()

    global DEFAULT_DEF
    if args.path:
        DEFAULT_DEF = args.path

    cfg = fill()
    src = cfg.pop("_source")
    scraped = cfg.pop("_scraped", "")

    for name, value in (("account_id", args.account_id),
                        ("subscription_id", args.subscription_id),
                        ("tenant_id", args.tenant_id),
                        ("partner_id", args.partner_id),
                        ("partner_unit_id", args.partner_unit_id)):
        if value:
            cfg[name] = value

    print(f"read {src}")
    print(f"  log scrape         : {scraped}")
    print(f"  authorization_token : {cfg['authorization_token'][:8]}…")
    print(f"  rest_url            : {cfg['rest_url']}")
    print(f"  ws_url              : {cfg['ws_url']}")

    missing = [k for k in ("account_id", "subscription_id", "tenant_id")
               if not cfg.get(k)]
    if missing:
        print()
        print("These still need values; see README 'Filling in config.json':")
        for key in missing:
            print(f"  --{key.replace('_', '-')}")
        print()
        print("Where to find them (all three are in Avast's own logs):")
        print()
        print(r"  account-id      C:\ProgramData\Avast Software\Avast\log\AvastSvc.log")
        print("                  search for  ACC='          (a 36-char UUID)")
        print(r"  subscription-id C:\ProgramData\Avast Software\Avast\log\lim.log")
        print("                  search for  Current psn:    (your licence key)")
        print(r"  X-Gen-Tenant-Id C:\ProgramData\Avast Software\Avast\log\AvastSvc.log")
        print("                  search for  X-Gen-Tenant-Id=")
        print()
        print("Or simply run the Avast assistant once and capture its traffic; see")
        print("capture/README-capture.md for the tooling.")
        print()
        print("Then re-run this script with:")
        print("  --account-id UUID --subscription-id KEY --tenant-id UUID")
        if not args.show:
            print("\nconfig.json NOT written (incomplete).")

    if args.show:
        print(json.dumps(cfg, indent=2, ensure_ascii=False))
        return 0

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(f"\nwrote {OUT}")
    if missing:
        print("Some fields are still blank - fill them in before starting the gateway.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
