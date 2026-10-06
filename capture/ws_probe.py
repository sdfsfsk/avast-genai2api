import socket, ssl, base64, os, uuid

K = "YOUR_ASSISTANT_KEY"
SID = "c26ab612-0390-4b89-841d-4ddf7384db42"
BASE = {
    "account-id": "YOUR_ACCOUNT_UUID", "app-lang": "zh-cn",
    "authorization-token": K, "enabled-features": "0",
    "guid": "YOUR_ACCOUNT_UUID", "subscription-id": "YOUR_LICENCE_KEY",
    "supported-response-modes": "1", "user-agent": "GES/26.10.11190.3848/Win/10.0/1",
    "X-Gen-Partner-Id": "1062590", "X-Gen-Partner-Unit-Id": "121686",
    "X-Gen-Tenant-Id": "YOUR_TENANT_UUID",
    "X-Gen-User-Agent": "GES/26.10.11190.3848/Win/10.0/1",
}
ctx = ssl.create_default_context()


def hs(name, path, extra=None, drop=()):
    h = dict(BASE)
    h.update(extra or {})
    for d in drop:
        h.pop(d, None)
    h.update({
        "Host": "genai-ws.avast.com", "Upgrade": "websocket", "Connection": "Upgrade",
        "Sec-WebSocket-Version": "13",
        "Sec-WebSocket-Key": base64.b64encode(os.urandom(16)).decode(),
    })
    try:
        s = ctx.wrap_socket(socket.create_connection(("44.211.10.130", 443), timeout=15),
                            server_hostname="genai-ws.avast.com")
        req = "GET " + path + " HTTP/1.1\r\n" + "".join(f"{k}: {v}\r\n" for k, v in h.items()) + "\r\n"
        s.sendall(req.encode())
        s.settimeout(15)
        d = s.recv(2048)
        first = d.split(b"\r\n")[0].decode("latin-1")
        body = d.split(b"\r\n\r\n", 1)[-1][:150].decode("utf-8", "replace").replace("\n", " ")
        print(f"  {name:52s} -> {first}   {body}")
        s.close()
    except Exception as e:
        print(f"  {name:52s} -> {type(e).__name__}: {str(e)[:70]}")


hs("?authorization-token=K (+session-id hdr)", f"/?authorization-token={K}", {"session-id": SID})
hs("?authorization-token=K&session-id=SID", f"/?authorization-token={K}&session-id={SID}")
hs("?authorization-token=K&session_id=SID", f"/?authorization-token={K}&session_id={SID}")
hs("?token=K", f"/?token={K}")
hs("?session-id=SID only", f"/?session-id={SID}")
hs("hdr session-id=SID + trace", "/", {"session-id": SID, "X-Gen-Trace-Id": str(uuid.uuid4())})
hs("hdr session-id + trace + ux-ctx", "/",
   {"session-id": SID, "X-Gen-Trace-Id": str(uuid.uuid4()), "X-Gen-UX-Context": "chat"})
