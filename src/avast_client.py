"""Client for the Avast / Gen Digital "Scam Assistant" GenAI backend.

Endpoints and header names were recovered from the Avast Premium Security
client (AvastUI.exe) and confirmed against live traffic:

    REST  https://genai-rest.avast.com/intent_topics   (GET)
    WS    wss://genai-ws.avast.com/                    (chat channel)

The credential set lives in setup/config.def under [ScamAssistant].
"""
from __future__ import annotations

import json
import os
import socket
import ssl
import uuid
from dataclasses import dataclass, field

REST_HOST = "genai-rest.avast.com"
WS_HOST = "genai-ws.avast.com"

CONFIG_PATH = os.environ.get(
    "AVAST_CONFIG",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json"),
)


@dataclass
class AvastCredentials:
    authorization_token: str = ""
    account_id: str = ""
    subscription_id: str = ""
    tenant_id: str = ""
    partner_id: str = ""
    partner_unit_id: str = ""
    product_id: str = "scam_asst"
    app_lang: str = "zh-cn"
    response_modes: str = "1"
    enabled_features: str = "0"
    user_agent: str = "GES/26.10.11190.3848/Win/10.0/1"
    rest_url: str = f"https://{REST_HOST}"
    ws_url: str = f"wss://{WS_HOST}"
    origin_ips: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, path: str | None = None) -> "AvastCredentials":
        path = path or CONFIG_PATH
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in raw.items() if k in known})

    def headers(self, session_id: str | None = None, trace_id: str | None = None) -> dict:
        h = {
            "account-id": self.account_id,
            "app-lang": self.app_lang,
            "authorization-token": self.authorization_token,
            "enabled-features": self.enabled_features,
            "guid": self.account_id,
            "subscription-id": self.subscription_id,
            "supported-response-modes": self.response_modes,
            "user-agent": self.user_agent,
            "X-Gen-Partner-Id": self.partner_id,
            "X-Gen-Partner-Unit-Id": self.partner_unit_id,
            "X-Gen-Tenant-Id": self.tenant_id,
            "X-Gen-User-Agent": self.user_agent,
        }
        if session_id:
            h["session-id"] = session_id
        if trace_id:
            h["X-Gen-Trace-Id"] = trace_id
        return h

    def ws_request_target(self, session_id: str, trace_id: str | None = None) -> str:
        """WebSocket URL, with every credential carried as a query parameter.

        This is the detail that made header-only handshakes fail with 401: the
        `$connect` authorizer reads its identity source from the query string,
        and the client sends *no* auth headers at all on this connection.
        Parameter order matches the client exactly.
        """
        import urllib.parse

        params = [
            ("account-id", self.account_id),
            ("app-lang", self.app_lang),
            ("authorization-token", self.authorization_token),
            ("enabled-features", self.enabled_features),
            ("guid", self.account_id),
            ("session-id", session_id),
            ("subscription-id", self.subscription_id),
            ("supported-response-modes", self.response_modes),
            ("user-agent", self.user_agent),
            ("X-Gen-Partner-Id", self.partner_id),
            ("X-Gen-Partner-Unit-Id", self.partner_unit_id),
            ("X-Gen-Tenant-Id", self.tenant_id),
            ("X-Gen-Trace-Id", trace_id or str(uuid.uuid4())),
            ("X-Gen-User-Agent", self.user_agent),
        ]
        query = urllib.parse.urlencode(params)
        return f"/?{query}"


class AvastGenAIError(RuntimeError):
    pass


def _connect(host: str, origin_ips: list[str] | None = None) -> ssl.SSLSocket:
    ctx = ssl.create_default_context()
    last: Exception | None = None
    for ip in origin_ips or []:
        try:
            return ctx.wrap_socket(socket.create_connection((ip, 443), timeout=25),
                                   server_hostname=host)
        except Exception as exc:  # try the next address
            last = exc
    try:
        return ctx.wrap_socket(socket.create_connection((host, 443), timeout=25),
                               server_hostname=host)
    except Exception as exc:
        raise AvastGenAIError(f"cannot reach {host}: {last or exc}") from exc


def _read_http(sock: ssl.SSLSocket) -> tuple[str, dict, bytes]:
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(8192)
        if not chunk:
            break
        buf += chunk
    head, _, rest = buf.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    status = lines[0]
    headers = {}
    for ln in lines[1:]:
        if ":" in ln:
            k, _, v = ln.partition(":")
            headers[k.strip().lower()] = v.strip()
    body = rest
    if "content-length" in headers:
        need = int(headers["content-length"])
        while len(body) < need:
            chunk = sock.recv(65536)
            if not chunk:
                break
            body += chunk
    return status, headers, body


class AvastGenAIClient:
    def __init__(self, creds: AvastCredentials):
        self.creds = creds

    # ---------------------------------------------------------------- REST

    def intent_topics(self) -> dict:
        sock = _connect(REST_HOST, self.creds.origin_ips)
        try:
            h = self.creds.headers(session_id=str(uuid.uuid4()),
                                   trace_id=str(uuid.uuid4()))
            req = ("GET /intent_topics HTTP/1.1\r\n"
                   + f"Host: {REST_HOST}\r\n"
                   + "".join(f"{k}: {v}\r\n" for k, v in h.items())
                   + "Connection: Keep-Alive\r\n\r\n")
            sock.sendall(req.encode())
            status, _, body = _read_http(sock)
            if "200" not in status:
                raise AvastGenAIError(f"intent_topics {status}: {body[:200]!r}")
            return json.loads(body.decode("utf-8"))
        finally:
            sock.close()

    # ------------------------------------------------------------ WebSocket

    def open_chat(self, session_id: str | None = None):
        return AvastChatSession(self, session_id or str(uuid.uuid4()))

    def chat(self, message: str, timeout: float = 25.0) -> str:
        with self.open_chat() as session:
            return session.ask(message, timeout=timeout)


class AvastChatSession:
    """One chat session on the GenAI WebSocket channel."""

    def __init__(self, client: AvastGenAIClient, session_id: str):
        self.client = client
        self.session_id = session_id
        self._sock: ssl.SSLSocket | None = None
        self._buf = b""

    def connect(self) -> None:
        import base64
        import os as _os

        creds = self.client.creds
        sock = _connect(WS_HOST, creds.origin_ips)
        target = creds.ws_request_target(self.session_id)
        key = base64.b64encode(_os.urandom(16)).decode()
        head = {
            "Host": WS_HOST,
            "Connection": "Upgrade",
            "Upgrade": "websocket",
            "Sec-WebSocket-Version": "13",
            "Sec-WebSocket-Key": key,
        }
        req = (f"GET {target} HTTP/1.1\r\n"
               + "".join(f"{k}: {v}\r\n" for k, v in head.items())
               + "\r\n")
        sock.sendall(req.encode())
        status, headers, _ = _read_http(sock)
        if "101" not in status:
            sock.close()
            raise AvastGenAIError(f"websocket handshake failed: {status}")
        if "permessage-deflate" in headers.get("sec-websocket-extensions", ""):
            sock.close()
            raise AvastGenAIError("server negotiated permessage-deflate; not supported")
        self._sock = sock

    # -- framing -------------------------------------------------------

    def _send_frame(self, payload: str) -> None:
        import os as _os
        import struct

        data = payload.encode("utf-8")
        mask = _os.urandom(4)
        header = bytearray([0x81])
        n = len(data)
        if n < 126:
            header.append(0x80 | n)
        elif n < 1 << 16:
            header.append(0x80 | 126)
            header += struct.pack(">H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", n)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        assert self._sock
        self._sock.sendall(bytes(header) + mask + masked)

    def _recv_frame(self, timeout: float) -> str | None:
        import struct

        assert self._sock
        self._sock.settimeout(timeout)
        while len(self._buf) < 2:
            try:
                chunk = self._sock.recv(65536)
            except (TimeoutError, OSError):
                return ""
            if not chunk:
                return None
            self._buf += chunk
        b0, b1 = self._buf[0], self._buf[1]
        opcode = b0 & 0x0F
        length = b1 & 0x7F
        off = 2
        if length == 126:
            while len(self._buf) < 4:
                try:
                    self._buf += self._sock.recv(65536)
                except (TimeoutError, OSError):
                    return ""
            length = struct.unpack(">H", self._buf[2:4])[0]
            off = 4
        elif length == 127:
            while len(self._buf) < 10:
                try:
                    self._buf += self._sock.recv(65536)
                except (TimeoutError, OSError):
                    return ""
            length = struct.unpack(">Q", self._buf[2:10])[0]
            off = 10
        while len(self._buf) < off + length:
            try:
                chunk = self._sock.recv(65536)
            except (TimeoutError, OSError):
                return ""
            if not chunk:
                return None
            self._buf += chunk
        payload = self._buf[off:off + length]
        self._buf = self._buf[off + length:]
        if opcode == 8:
            return None
        if opcode == 9:
            return ""
        try:
            return payload.decode("utf-8")
        except UnicodeDecodeError:
            return payload.decode("utf-8", "replace")

    # -- protocol ------------------------------------------------------

    def ask(self, message: str, timeout: float = 25.0) -> str:
        return "".join(self.stream(message, timeout=timeout))

    def stream(self, message: str, timeout: float = 25.0):
        """Yield assistant text fragments as they arrive.

        Raises AvastGenAIError if the backend accepts the frame but sends
        nothing back - that is the current state of the message-body research.
        """
        import time

        if self._sock is None:
            self.connect()
        # Wire format, confirmed against the live backend: the payload sits
        # inside a "data" object next to the API Gateway route key.
        self._frame = json.dumps({
            "action": "chat",
            "data": {
                "session_id": self.session_id,
                "text": message,
            },
        }, ensure_ascii=False)
        self._send_frame(self._frame)

        produced = False
        deadline = time.time() + timeout
        while time.time() < deadline:
            frame = self._recv_frame(max(1.0, deadline - time.time()))
            if frame is None:
                break
            if not frame:
                continue
            try:
                data = json.loads(frame)
            except json.JSONDecodeError:
                continue
            for text in _extract_text(data):
                produced = True
                yield text
            if _is_complete(data):
                break
        if not produced:
            raise AvastGenAIError(
                "no reply from the assistant backend: the frame was accepted by the "
                "chat route but nothing came back, so the exact message body is still "
                "unknown. See README (WebSocket chat) for the state of that research.")

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc):
        try:
            if self._sock:
                self._sock.close()
        finally:
            self._sock = None
        return False

def _extract_text(payload: dict) -> list[str]:
    """Pull assistant text out of a server frame.

    Server frames look like::

        {"status_code": 200,
         "message": {"message_id": "...", "response_mode": "single",
                     "response_completed": true,
                     "rich_contents": [{"messages": [{"lang": "en-US",
                                                     "body": "..."}]}]}}
    """
    out: list[str] = []
    message = payload.get("message") if isinstance(payload, dict) else None
    if not isinstance(message, dict):
        return out
    rich = message.get("rich_contents")
    if isinstance(rich, list):
        for block in rich:
            if not isinstance(block, dict):
                continue
            body = block.get("body")
            if isinstance(body, str):
                out.append(body)
            for msg in block.get("messages") or []:
                if isinstance(msg, dict) and isinstance(msg.get("body"), str):
                    out.append(msg["body"])
    for key in ("body", "text", "chat_message"):
        value = message.get(key)
        if isinstance(value, str):
            out.append(value)
    return out


def _is_complete(payload: dict) -> bool:
    message = payload.get("message") if isinstance(payload, dict) else None
    if isinstance(message, dict) and message.get("response_completed"):
        return True
    return bool(isinstance(payload, dict) and payload.get("response_completed"))
