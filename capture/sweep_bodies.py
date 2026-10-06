"""Sweep plausible chat message bodies against the GenAI WebSocket.

Each candidate is sent on a fresh connection; anything other than the API
Gateway "Forbidden" reply (or a timeout) is reported. `action: "chat"` is the
only value the gateway accepts as a route, so every candidate keeps it.

Run:  python sweep_bodies.py [seconds-per-try]
"""
import asyncio
import json
import sys
import uuid

import websockets

TOKEN = "YOUR_ASSISTANT_KEY"
ACCOUNT = "YOUR_ACCOUNT_UUID"
UA = "GES%2F26.10.11190.3848%2FWin%2F10.0%2F1"
WAIT = float(sys.argv[1]) if len(sys.argv) > 1 else 12.0


def url(sid, tr):
    return ("wss://genai-ws.avast.com/?account-id=" + ACCOUNT +
            "&app-lang=zh-cn&authorization-token=" + TOKEN +
            "&enabled-features=0&guid=" + ACCOUNT + "&session-id=" + sid +
            "&subscription-id=YOUR_LICENCE_KEY&supported-response-modes=1&user-agent=" + UA +
            "&X-Gen-Partner-Id=1062590&X-Gen-Partner-Unit-Id=121686" +
            "&X-Gen-Tenant-Id=YOUR_TENANT_UUID" +
            "&X-Gen-Trace-Id=" + tr + "&X-Gen-User-Agent=" + UA)


def candidates(sid):
    base = {"action": "chat", "session_id": sid}
    out = []
    for key in ("text", "message", "content", "prompt", "query", "input",
                "chat_message", "user_message", "body"):
        b = dict(base)
        b[key] = "hello"
        out.append((f"action+{key}", b))
    for key in ("text", "message", "content"):
        b = dict(base)
        b[key] = "hello"
        b["intent"] = ""
        out.append((f"action+{key}+intent", b))
    for extra in ("feature_name", "featureName", "chip_id", "chipId",
                  "ui_launch_source", "response_mode", "response_modes",
                  "lang", "language", "device_id", "guid"):
        b = dict(base)
        b["text"] = "hello"
        b[extra] = "scam_asst" if "feature" in extra else (
            "1" if "response" in extra else "zh-cn" if "lang" in extra else ACCOUNT)
        out.append((f"action+text+{extra}", b))
    b = dict(base)
    b["text"] = "hello"
    b["intent"] = ""
    b["feature_name"] = "scam_asst"
    b["ui_launch_source"] = "dashboard"
    b["response_mode"] = 1
    out.append(("action+everything", b))
    for wrap in ("payload", "data", "body", "request"):
        out.append((f"action+{wrap}={{...}}",
                    {"action": "chat", wrap: {"session_id": sid, "text": "hello"}}))
    return out


async def one(name, body, wait):
    tr = str(uuid.uuid4())
    sid = str(uuid.uuid4())
    body = dict(body)
    if body.get("session_id"):
        body["session_id"] = sid
    for wrap in ("payload", "data", "body", "request"):
        if isinstance(body.get(wrap), dict) and body[wrap].get("session_id"):
            body[wrap]["session_id"] = sid
    try:
        async with websockets.connect(url(sid, tr), open_timeout=12,
                                      max_size=None, compression=None) as ws:
            await ws.send(json.dumps(body, ensure_ascii=False))
            try:
                reply = await asyncio.wait_for(ws.recv(), timeout=wait)
                text = str(reply)
                flag = "FORBIDDEN" if "Forbidden" in text else "*** REPLY ***"
                return f"{flag:14s} {name}: {text[:220]}"
            except asyncio.TimeoutError:
                return f"silent         {name}"
    except Exception as exc:  # noqa: BLE001
        return f"error          {name}: {type(exc).__name__}"


async def main():
    sid = str(uuid.uuid4())
    results = []
    for name, body in candidates(sid):
        line = await one(name, body, WAIT)
        print("  " + line, flush=True)
        results.append(line)
    print("\n=== non-Forbidden results ===")
    for line in results:
        if "FORBIDDEN" not in line:
            print("  " + line)


if __name__ == "__main__":
    asyncio.run(main())
