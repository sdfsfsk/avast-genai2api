"""OpenAI-compatible gateway in front of the Avast Scam Assistant backend.

    POST /v1/chat/completions   chat, streaming and non-streaming
    GET  /v1/models             model list
    GET  /v1/topics             raw Avast intent topics
    GET  /health                readiness

Run:  python server.py            (defaults to 127.0.0.1:8787)
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from avast_client import (  # noqa: E402
    CONFIG_PATH,
    AvastCredentials,
    AvastGenAIClient,
    AvastGenAIError,
)
from persona import Persona, RewriteError  # noqa: E402

HOST = os.environ.get("AVAST_GATEWAY_HOST", "127.0.0.1")
PORT = int(os.environ.get("AVAST_GATEWAY_PORT", "8787"))
MODEL_ID = os.environ.get("AVAST_MODEL_ID", "avast-assistant")

_creds: AvastCredentials | None = None
_persona: Persona | None = None


def creds() -> AvastCredentials:
    global _creds
    if _creds is None:
        _creds = AvastCredentials.load()
    return _creds


def persona() -> Persona:
    """Persona layer, read from config.json so it can be changed without code."""
    global _persona
    if _persona is None:
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, json.JSONDecodeError):
            raw = {}
        _persona = Persona(raw.get("persona") or {})
    return _persona


def reload_persona() -> Persona:
    global _persona
    _persona = None
    return persona()


def sse(obj: dict) -> bytes:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode()


def chunk(cid: str, model: str, delta: dict, finish: str | None = None) -> dict:
    return {
        "id": cid, "object": "chat.completion.chunk", "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "avast-genai2api"

    def log_message(self, fmt, *args):
        print(f"[{time.strftime('%H:%M:%S')}] {self.address_string()} {fmt % args}", flush=True)

    # ------------------------------------------------------------------

    def _json(self, code: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    # ------------------------------------------------------------------

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/health":
            return self._json(200, {"status": "ok", "model": MODEL_ID})
        if path == "/v1/models":
            return self._json(200, {"object": "list", "data": [
                {"id": MODEL_ID, "object": "model", "owned_by": "avast"}]})
        if path == "/v1/topics":
            try:
                return self._json(200, AvastGenAIClient(creds()).intent_topics())
            except AvastGenAIError as exc:
                return self._json(502, {"error": {"message": str(exc)}})
        if path in ("/v1/status", "/status"):
            return self._json(200, self._status())
        if path == "/v1/persona":
            if "reload" in self.path:
                return self._json(200, reload_persona().describe())
            return self._json(200, persona().describe())
        return self._json(404, {"error": {"message": f"unknown path {path}"}})

    def _status(self) -> dict:
        """Report which upstream capabilities currently work."""
        try:
            client = AvastGenAIClient(creds())
        except Exception as exc:  # noqa: BLE001
            return {"config": f"error: {exc}"}
        out = {"config": "ok", "model": MODEL_ID}
        try:
            topics = client.intent_topics()
            out["rest_intent_topics"] = f"ok ({len(topics.get('topics', []))} topics)"
        except Exception as exc:  # noqa: BLE001
            out["rest_intent_topics"] = f"error: {exc}"
        try:
            session = client.open_chat()
            session.connect()
            out["ws_handshake"] = f"ok (session {session.session_id})"
            try:
                answer = session.ask("ping", timeout=25)
                preview = " ".join(answer.split())[:60]
                out["chat"] = f"ok ({len(answer)} chars: {preview!r})"
            except Exception as exc:  # noqa: BLE001
                out["chat"] = f"error: {exc}"
            try:
                session._sock.close()
            except Exception:
                pass
        except Exception as exc:  # noqa: BLE001
            out["ws_handshake"] = f"error: {exc}"
            out["chat"] = "unavailable"
        return out

    def _ws_raw(self):
        """Send an arbitrary JSON body on the chat socket and return every reply.

        Useful for pinning down the message shape the backend expects:

            curl -X POST http://127.0.0.1:8787/v1/ws/raw \\
                 -H "Content-Type: application/json" \\
                 -d '{"action":"chat","session_id":"auto","text":"hello"}'

        "session_id": "auto" is replaced with the live session id.
        """
        payload = self._read_json()
        wait = float(payload.pop("_wait", 25))
        try:
            client = AvastGenAIClient(creds())
            session = client.open_chat()
            session.connect()
            if payload.get("session_id") in (None, "", "auto"):
                payload["session_id"] = session.session_id
            session._send_frame(json.dumps(payload, ensure_ascii=False))
            replies = []
            deadline = time.time() + wait
            while time.time() < deadline:
                frame = session._recv_frame(max(1.0, deadline - time.time()))
                if frame is None:
                    break
                if frame:
                    replies.append(frame)
                    if len(replies) >= 20:
                        break
            try:
                session._sock.close()
            except Exception:
                pass
            return self._json(200, {"sent": payload, "replies": replies})
        except Exception as exc:  # noqa: BLE001
            return self._json(502, {"error": {"message": f"{type(exc).__name__}: {exc}"}})

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/v1/ws/raw":
            return self._ws_raw()
        if path != "/v1/chat/completions":
            return self._json(404, {"error": {"message": f"unknown path {path}"}})

        payload = self._read_json()
        messages = payload.get("messages") or []
        prompt = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content")
                prompt = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
                break
        if not prompt:
            return self._json(400, {"error": {"message": "no user message supplied"}})

        stream = bool(payload.get("stream"))
        cid = f"chatcmpl-{uuid.uuid4().hex[:24]}"
        model = payload.get("model") or MODEL_ID

        # The persona layer is applied on the way out (inject) and on the way
        # back (rewrite); see persona.py for what each mode does.
        pers = persona()
        try:
            outgoing = pers.preprocess(prompt)
        except Exception as exc:  # noqa: BLE001
            return self._json(500, {"error": {"message": f"persona: {exc}"}})

        try:
            client = AvastGenAIClient(creds())
            if stream:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(sse(chunk(cid, model, {"role": "assistant", "content": ""})))
                try:
                    with client.open_chat() as session:
                        for piece in session.stream(outgoing):
                            self.wfile.write(sse(chunk(cid, model, {"content": piece})))
                except AvastGenAIError as exc:
                    self.wfile.write(sse({"error": {"message": str(exc)}}))
                self.wfile.write(sse(chunk(cid, model, {}, finish="stop")))
                self.wfile.write(b"data: [DONE]\n\n")
                return

            answer = client.chat(outgoing)
            if pers.active and pers.mode in ("rewrite", "both"):
                try:
                    answer = pers.postprocess(answer)
                except RewriteError as exc:
                    # Never lose the upstream answer just because restyling failed.
                    answer = f"{answer}\n\n[persona rewrite failed: {exc}]"
            return self._json(200, {
                "id": cid, "object": "chat.completion", "created": int(time.time()),
                "model": model,
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": answer}}],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            })
        except AvastGenAIError as exc:
            return self._json(502, {"error": {"message": str(exc), "type": "upstream_error"}})
        except Exception as exc:  # noqa: BLE001
            return self._json(500, {"error": {"message": f"{type(exc).__name__}: {exc}"}})


def main():
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"avast-genai2api listening on http://{HOST}:{PORT}  model={MODEL_ID}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
