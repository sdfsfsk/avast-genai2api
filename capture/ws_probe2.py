import socket, ssl, base64, os, uuid

K = "YOUR_ASSISTANT_KEY"
ctx = ssl.create_default_context()

COMMON = [
    ("account-id", "YOUR_ACCOUNT_UUID"),
    ("app-lang", "zh-cn"),
    ("authorization-token", K),
    ("enabled-features", "0"),
    ("guid", "YOUR_ACCOUNT_UUID"),
    ("subscription-id", "YOUR_LICENCE_KEY"),
    ("supported-response-modes", "1"),
    ("user-agent", "GES/26.10.11190.3848/Win/10.0/1"),
    ("X-Gen-Partner-Id", "1062590"),
    ("X-Gen-Partner-Unit-Id", "121686"),
    ("X-Gen-Tenant-Id", "YOUR_TENANT_UUID"),
    ("X-Gen-User-Agent", "GES/26.10.11190.3848/Win/10.0/1"),
]


def hs(name, path, sid_header, sid_value):
    h = list(COMMON)
    if sid_header:
        h.append((sid_header, sid_value))
    h += [
        ("Host", "genai-ws.avast.com"),
        ("Upgrade", "websocket"),
        ("Connection", "Upgrade"),
        ("Sec-WebSocket-Key", base64.b64encode(os.urandom(16)).decode()),
        ("Sec-WebSocket-Version", "13"),
        ("Sec-WebSocket-Extensions", "permessage-deflate; client_max_window_bits"),
    ]
    try:
        s = ctx.wrap_socket(socket.create_connection(("184.73.97.174", 443), timeout=15),
                            server_hostname="genai-ws.avast.com")
        s.sendall(("GET " + path + " HTTP/1.1\r\n" + "".join(f"{k}: {v}\r\n" for k, v in h) + "\r\n").encode())
        s.settimeout(15)
        d = s.recv(2048)
        head = d.split(b"\r\n\r\n")[0].decode("latin-1")
        body = d.split(b"\r\n\r\n")[-1][:120].decode("utf-8", "replace")
        print(f"  {name:46s} -> {d.split(b'%s' % b'\r\n')[0].decode('latin-1')}")
        if not head.startswith("HTTP/1.1 101"):
            print("        ", body)
        else:
            print("         *** 101 SWITCHING PROTOCOLS ***")
        s.close()
        return d.startswith(b"HTTP/1.1 101")
    except Exception as e:
        print(f"  {name:46s} -> {type(e).__name__}: {str(e)[:70]}")
        return False


CAPTURED_SID = "29e25600-978d-45f7-b783-9035b58b7168"
hs("session_id= (captured, underscore)", "/", "session_id", CAPTURED_SID)
hs("session_id= (fresh uuid, underscore)", "/", "session_id", str(uuid.uuid4()))
hs("session-id= (captured, hyphen)", "/", "session-id", CAPTURED_SID)
hs("session_id fresh + X-Gen-Trace-Id", "/", "session_id", str(uuid.uuid4()))
