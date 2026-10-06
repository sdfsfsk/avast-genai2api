"""CMD chat client for the Avast Assistant.

    python cli.py                       talk to the local gateway (default)
    python cli.py --ask "question"      ask one question and exit
    python cli.py --direct              skip the gateway, call Avast directly

Plain console output, no browser. One WebSocket session is kept open for the
whole conversation, which is both faster and closer to how the real client
behaves (Connect once, then SendMessage repeatedly).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DEFAULT_BASE = os.environ.get("AVAST_GATEWAY_BASE", "http://127.0.0.1:8787/v1")
DEFAULT_MODEL = os.environ.get("AVAST_MODEL_ID", "avast-assistant")


def c(text: str) -> str:
    """Keep console output inside the active code page."""
    enc = sys.stdout.encoding or "utf-8"
    try:
        text.encode(enc)
        return text
    except (UnicodeEncodeError, LookupError):
        return text.encode(enc, "replace").decode(enc, "replace")


class Busy:
    """Print a heartbeat while the answer is being produced."""

    def __init__(self, label="thinking"):
        self.label = label
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = 0.0

    def __enter__(self):
        self._started = time.time()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def _run(self):
        dots = 0
        while not self._stop.wait(0.7):
            dots += 1
            sys.stdout.write("\r" + c(f"  {self.label}{'.' * (dots % 4)}   "))
            sys.stdout.flush()

    def __exit__(self, *exc):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
        sys.stdout.write("\r" + " " * 40 + "\r")
        sys.stdout.flush()
        print(c(f"  ({time.time() - self._started:.1f}s)"), flush=True)
        return False


# --------------------------------------------------------------- backends


class GatewayBackend:
    def __init__(self, base: str, model: str, timeout: float):
        self.base = base.rstrip("/")
        self.model = model
        self.timeout = timeout

    def ask(self, question: str) -> str:
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": question}],
            "stream": False,
        }).encode("utf-8")
        req = urllib.request.Request(
            self.base + "/chat/completions", data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer local"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.load(resp)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            try:
                detail = json.loads(detail)["error"]["message"]
            except Exception:
                pass
            raise RuntimeError(f"gateway HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"cannot reach the gateway at {self.base} ({exc.reason}). "
                "Start it first by running 启动.cmd") from exc
        return data["choices"][0]["message"]["content"]

    def close(self):
        pass


class DirectBackend:
    """Keeps one WebSocket session alive for the whole conversation."""

    def __init__(self, timeout: float):
        from avast_client import AvastCredentials, AvastGenAIClient, AvastGenAIError

        self._errors = (AvastGenAIError,)
        self.timeout = timeout
        self.client = AvastGenAIClient(AvastCredentials.load())
        self.session = None

    def _ensure(self):
        if self.session is None:
            self.session = self.client.open_chat()
            self.session.connect()
        return self.session

    def ask(self, question: str) -> str:
        session = self._ensure()
        try:
            return session.ask(question, timeout=self.timeout)
        except Exception:
            # one transparent retry on a fresh socket
            try:
                session._sock.close()
            except Exception:
                pass
            self.session = None
            session = self._ensure()
            return session.ask(question, timeout=self.timeout)

    def close(self):
        try:
            if self.session:
                self.session._sock.close()
        except Exception:
            pass


# ------------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser(add_help=True, description="Avast Assistant CMD client")
    ap.add_argument("--ask", "-a", help="ask a single question and exit")
    ap.add_argument("--direct", action="store_true",
                    help="bypass the local gateway and talk to Avast directly")
    ap.add_argument("--base", default=DEFAULT_BASE,
                    help=f"gateway base url (default {DEFAULT_BASE})")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--timeout", type=float, default=90.0)
    args = ap.parse_args()

    backend = (DirectBackend(args.timeout) if args.direct
               else GatewayBackend(args.base, args.model, args.timeout))

    def run(question: str) -> str:
        with Busy():
            return backend.ask(question)

    if args.ask:
        try:
            print(c(run(args.ask)))
        except Exception as exc:  # noqa: BLE001
            print(c(f"[error] {exc}"), file=sys.stderr)
            return 1
        finally:
            backend.close()
        return 0

    where = "direct to Avast" if args.direct else args.base
    print("=" * 60)
    print(c(f"  Avast Assistant  ·  {where}"))
    print(c("  输入问题后回车；exit / quit 退出，Ctrl+C 中断"))
    print(c("  首次提问要建立连接，通常 5~25 秒；之后会快很多"))
    print("=" * 60)

    if hasattr(backend, "_ensure"):
        try:
            with Busy("connecting"):
                backend._ensure()
            print(c("  已连接。"))
        except Exception as exc:  # noqa: BLE001
            print(c(f"[error] 连接失败: {exc}"))
            return 1

    try:
        while True:
            try:
                question = input(c("\n你> ")).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not question:
                continue
            if question.lower() in ("exit", "quit", "q"):
                break
            try:
                answer = run(question)
            except KeyboardInterrupt:
                print(c("\n  (已中断)"))
                continue
            except Exception as exc:  # noqa: BLE001
                print(c(f"[error] {exc}"))
                continue
            print(c(f"\n助手> {answer}"))
    finally:
        backend.close()
    print(c("bye"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
