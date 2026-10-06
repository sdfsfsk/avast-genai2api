"""Capture proxy for Avast GenAI traffic.

Listens on 127.0.0.1:443 (reached via an NRPT rule + local DNS override),
terminates TLS with the local capture certificate, logs every request and
response, and relays to the real origin. WebSocket upgrades are tunnelled
and their frames are logged.
"""
import json
import os
import socket
import ssl
import struct
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CERT = os.path.join(HERE, "certs", "server.crt")
KEY = os.path.join(HERE, "certs", "server.key")
LOG = os.path.join(HERE, "capture.jsonl")

LISTEN_PORT = 443
TIMEOUT = 600

HOSTS = ("genai-rest.avast.com", "genai-ws.avast.com")
FALLBACK_IPS = {
    "genai-rest.avast.com": ["13.249.74.57", "13.249.74.122", "13.249.74.92", "13.249.74.49"],
    "genai-ws.avast.com": ["44.211.10.130", "18.210.164.172", "54.172.13.143"],
}

# The WebSocket module resolves through DNS-over-HTTPS, bypassing the hosts
# file and the NRPT rule. These endpoints are answered locally instead.
DOH_HOSTS = {"dns.google", "cloudflare-dns.com", "dns.google.com"}
DOH_NAMES = {"genai-rest.avast.com", "genai-ws.avast.com"}

_loglock = threading.Lock()


def _qname(data, off):
    labels = []
    while True:
        ln = data[off]
        off += 1
        if ln == 0:
            break
        labels.append(data[off:off + ln].decode("latin-1"))
        off += ln
    return ".".join(labels), off


def dns_wire_response(query):
    """Answer a DNS wire-format query: A 127.0.0.1 for our names, NXDOMAIN otherwise."""
    if len(query) < 12:
        return None
    qid = query[:2]
    qdcount = struct.unpack(">H", query[4:6])[0]
    if qdcount < 1:
        return None
    name, off = _qname(query, 12)
    qtype, _qclass = struct.unpack(">HH", query[off:off + 4])
    question = query[12:off + 4]
    lower = name.lower().rstrip(".")
    if lower in DOH_NAMES and qtype in (1, 255):
        hdr = qid + struct.pack(">HHHHH", 0x8180, 1, 1, 0, 0)
        ans = b"\xc0\x0c" + struct.pack(">HHIH", 1, 1, 60, 4) + socket.inet_aton("127.0.0.1")
        return hdr + question + ans
    return qid + struct.pack(">HHHHH", 0x8183, 1, 0, 0, 0) + question


def log(rec):
    rec["ts"] = time.strftime("%Y-%m-%d %H:%M:%S")
    with _loglock:
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    tag = rec.get("method") or rec.get("dir") or rec.get("raw", "")[:40]
    print(f"[{rec['ts']}] {rec.get('kind'):18s} {rec.get('host','')}{rec.get('path','')}  {tag}", flush=True)


_origin_cache = {}


def resolve_origin(host):
    if host in _origin_cache and _origin_cache[host][1] > time.time():
        return _origin_cache[host][0]
    ips = []
    try:
        url = f"https://dns.google/resolve?name={host}&type=A"
        with urllib.request.urlopen(url, timeout=8) as r:
            data = json.load(r)
        ips = [a["data"] for a in data.get("Answer", []) if a.get("type") == 1]
    except Exception as exc:
        print(f"  DoH failed for {host}: {exc}", flush=True)
    if not ips:
        ips = list(FALLBACK_IPS.get(host, []))
    ips = [ip for ip in ips if not ip.startswith("127.")]
    if not ips:
        ips = [ip for ip in FALLBACK_IPS.get(host, []) if not ip.startswith("127.")]
    _origin_cache[host] = (ips, time.time() + 300)
    return ips


def dial_origin(host):
    ctx = ssl.create_default_context()
    last = None
    for ip in resolve_origin(host):
        try:
            raw = socket.create_connection((ip, 443), timeout=20)
            return ctx.wrap_socket(raw, server_hostname=host)
        except Exception as exc:
            last = exc
    raise last or RuntimeError(f"no origin for {host}")


def recv_head(sock, limit=1 << 20):
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(8192)
        if not chunk:
            return buf
        buf += chunk
        if len(buf) > limit:
            break
    return buf


def split_head(raw):
    head, _, rest = raw.partition(b"\r\n\r\n")
    lines = head.split(b"\r\n")
    start = lines[0].decode("latin-1")
    headers = []
    for ln in lines[1:]:
        if b":" in ln:
            k, _, v = ln.decode("latin-1").partition(":")
            headers.append((k.strip(), v.strip()))
    return start, headers, rest


def _sock_recv_exact(sock, n, buf):
    while len(buf) < n:
        chunk = sock.recv(min(65536, n - len(buf)))
        if not chunk:
            break
        buf += chunk
    return buf


def read_message_body(sock, headers, buf):
    """Read a body according to Content-Length / chunked. Returns (body, leftover)."""
    hl = {k.lower(): v for k, v in headers}
    if hl.get("transfer-encoding", "").lower() == "chunked":
        while True:
            while b"\r\n" not in buf:
                chunk = sock.recv(65536)
                if not chunk:
                    return buf, b""
                buf += chunk
            line, _, rest = buf.partition(b"\r\n")
            try:
                size = int(line.split(b";")[0], 16)
            except ValueError:
                return buf, b""
            need = size + 2 + len(line) + 2
            if size == 0:
                while len(buf) < need:
                    chunk = sock.recv(65536)
                    if not chunk:
                        return buf, b""
                    buf += chunk
                return buf[:need], buf[need:]
            while len(buf) < need:
                chunk = sock.recv(65536)
                if not chunk:
                    return buf, b""
                buf += chunk
            buf = buf[need:]
            if size == 0:
                return b"", buf
        return b"", buf
    if "content-length" in hl:
        try:
            need = int(hl["content-length"])
        except ValueError:
            return buf, b""
        buf = _sock_recv_exact(sock, need, buf)
        return buf[:need], buf[need:]
    return b"", buf


def ws_frames(buf):
    out = []
    i = 0
    while i + 2 <= len(buf):
        b0, b1 = buf[i], buf[i + 1]
        opcode = b0 & 0x0F
        masked = b1 & 0x80
        length = b1 & 0x7F
        off = i + 2
        if length == 126:
            if off + 2 > len(buf):
                break
            length = struct.unpack(">H", buf[off:off + 2])[0]
            off += 2
        elif length == 127:
            if off + 8 > len(buf):
                break
            length = struct.unpack(">Q", buf[off:off + 8])[0]
            off += 8
        mask = b""
        if masked:
            if off + 4 > len(buf):
                break
            mask = buf[off:off + 4]
            off += 4
        if off + length > len(buf):
            break
        payload = bytearray(buf[off:off + length])
        if masked:
            for j in range(len(payload)):
                payload[j] ^= mask[j % 4]
        i = off + length
        if opcode in (1, 2):
            try:
                out.append(payload.decode("utf-8"))
            except Exception:
                out.append("<binary " + payload.hex()[:400] + ">")
        elif opcode == 9:
            out.append("<ping>")
        elif opcode == 10:
            out.append("<pong>")
        elif opcode == 8:
            out.append("<close>")
    return out, i


def tunnel(client, upstream, host, path):
    def pump(src, dst, tag):
        carry = b""
        try:
            while True:
                data = src.recv(65536)
                if not data:
                    break
                if tag == "c2s":
                    carry += data
                    frames, consumed = ws_frames(carry)
                    carry = carry[consumed:]
                    for p in frames:
                        log({"kind": "ws_c2s", "host": host, "path": path, "dir": "C->S", "payload": p})
                else:
                    carry += data
                    frames, consumed = ws_frames(carry)
                    carry = carry[consumed:]
                    for p in frames:
                        log({"kind": "ws_s2c", "host": host, "path": path, "dir": "S->C", "payload": p})
                dst.sendall(data)
        except Exception:
            pass
        finally:
            for s in (src, dst):
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
    t1 = threading.Thread(target=pump, args=(client, upstream, "c2s"), daemon=True)
    t2 = threading.Thread(target=pump, args=(upstream, client, "s2c"), daemon=True)
    t1.start()
    t2.start()
    t1.join()
    t2.join()


def handle_doh(method, path, body, headers):
    """Answer RFC 8484 DoH queries (and Google's JSON API) from the local table."""
    import base64
    import urllib.parse

    query = None
    if method == "POST" and body:
        query = body
    else:
        qs = urllib.parse.urlparse(path).query
        params = urllib.parse.parse_qs(qs)
        if "dns" in params:
            raw = params["dns"][0]
            pad = "=" * (-len(raw) % 4)
            try:
                query = base64.urlsafe_b64decode(raw + pad)
            except Exception:
                query = None

    if query:
        resp = dns_wire_response(query)
        if resp is None:
            return None
        log({"kind": "doh", "path": path, "qname": _qname(query, 12)[0]})
        return (b"HTTP/1.1 200 OK\r\nContent-Type: application/dns-message\r\n"
                b"Content-Length: " + str(len(resp)).encode() + b"\r\n\r\n" + resp)

    # Google JSON API fallback: /resolve?name=...&type=A
    qs = urllib.parse.urlparse(path).query
    params = urllib.parse.parse_qs(qs)
    name = (params.get("name") or [""])[0].lower().rstrip(".")
    log({"kind": "doh_json", "path": path, "qname": name})
    if name in DOH_NAMES:
        payload = json.dumps({"Status": 0, "Answer": [
            {"name": name, "type": 1, "TTL": 60, "data": "127.0.0.1"}]}).encode()
    else:
        payload = json.dumps({"Status": 3, "Answer": []}).encode()
    return (b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
            b"Content-Length: " + str(len(payload)).encode() + b"\r\n\r\n" + payload)


def fake_ws_server(tls, host, path, headers):
    """Answer the WebSocket upgrade locally and log every frame the client sends.

    The GenAI client pins its peer address (CURLOPT_RESOLVE), so it can be
    steered here by binding the resolved address on the loopback adapter. Once
    the client sees 101 it sends its real payload in the clear, which is what
    this recovery step is after.
    """
    import base64
    import hashlib

    hl = {k.lower(): v for k, v in headers}
    key = hl.get("sec-websocket-key", "")
    accept = base64.b64encode(hashlib.sha1(
        (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
    resp = ("HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n\r\n")
    tls.sendall(resp.encode())
    log({"kind": "ws_fake_upgrade", "host": host, "path": path})

    buf = b""
    tls.settimeout(180)
    while True:
        try:
            chunk = tls.recv(65536)
        except Exception:
            break
        if not chunk:
            break
        buf += chunk
        frames, consumed = ws_frames(buf)
        buf = buf[consumed:]
        for f in frames:
            log({"kind": "ws_c2s", "host": host, "path": path,
                 "dir": "C->S", "payload": f})


def serve_http(tls, host, peer):
    buf = b""
    while True:
        raw = recv_head(tls) if not buf else buf + tls.recv(0)
        if not raw or b"\r\n\r\n" not in raw:
            return
        start, headers, rest = split_head(raw)
        buf = b""
        parts = start.split()
        if len(parts) < 3:
            return
        method, path, version = parts[0], parts[1], parts[2]
        hl = {k.lower(): v for k, v in headers}
        if hl.get("host"):
            host = hl["host"].split(":")[0]

        body, leftover = read_message_body(tls, headers, rest)
        log({"kind": "request", "host": host, "method": method, "path": path,
             "headers": headers, "body": body.decode("utf-8", "replace")})

        if host in DOH_HOSTS:
            answer = handle_doh(method, path, body, headers)
            if answer is not None:
                tls.sendall(answer)
                continue
            return

        if host == "genai-ws.avast.com" and hl.get("upgrade", "").lower() == "websocket":
            fake_ws_server(tls, host, path, headers)
            return

        upstream = dial_origin(host)
        req = f"{method} {path} {version}".encode() + b"\r\n" + b"\r\n".join(
            f"{k}: {v}".encode() for k, v in headers) + b"\r\n\r\n" + body
        upstream.sendall(req)

        if hl.get("upgrade", "").lower() == "websocket":
            resp_raw = recv_head(upstream)
            log({"kind": "ws_handshake", "host": host, "path": path,
                 "raw": resp_raw.decode("latin-1", "replace")})
            tls.sendall(resp_raw)
            if leftover:
                upstream.sendall(leftover)
            tunnel(tls, upstream, host, path)
            return

        up_buf = recv_head(upstream)
        if not up_buf:
            return
        rstart, rheaders, rrest = split_head(up_buf)
        rbody, _ = read_message_body(upstream, rheaders, rrest)
        chunk = up_buf.split(b"\r\n\r\n")[0] + b"\r\n\r\n" + rbody
        tls.sendall(chunk)
        log({"kind": "response", "host": host, "path": path,
             "status": rstart, "headers": rheaders,
             "body": rbody.decode("utf-8", "replace")[:40000]})

        rhl = {k.lower(): v for k, v in rheaders}
        if rhl.get("connection", "").lower() == "close":
            return
        try:
            upstream.close()
        except Exception:
            pass
        buf = b""


def read_client_hello_sni(sock, peek_timeout=10.0):
    """Peek at the TLS ClientHello and pull out the SNI without consuming it."""
    old = sock.gettimeout()
    sock.settimeout(peek_timeout)
    try:
        data = sock.recv(5, socket.MSG_PEEK)
        if len(data) < 5:
            return None
        length = struct.unpack(">H", data[3:5])[0]
        buf = b""
        while len(buf) < 5 + length:
            chunk = sock.recv(5 + length, socket.MSG_PEEK)
            if len(chunk) == len(buf):
                break
            buf = chunk
        data = sock.recv(5 + length, socket.MSG_PEEK)
        if len(data) < 5 + length:
            return None
        body = data[5:]
        # handshake header
        if body[0] != 0x01:
            return None
        p = 4 + 2 + 32           # handshake hdr + version + random
        sid_len = body[p]
        p += 1 + sid_len
        cs_len = struct.unpack(">H", body[p:p + 2])[0]
        p += 2 + cs_len
        comp_len = body[p]
        p += 1 + comp_len
        if p + 2 > len(body):
            return None
        ext_total = struct.unpack(">H", body[p:p + 2])[0]
        p += 2
        end = min(len(body), p + ext_total)
        while p + 4 <= end:
            etype, elen = struct.unpack(">HH", body[p:p + 4])
            p += 4
            if etype == 0x00:  # server_name
                off = p + 2 + 1
                nlen = struct.unpack(">H", body[p + 3:p + 5])[0]
                return body[p + 5:p + 5 + nlen].decode("latin-1")
            p += elen
        return None
    except Exception:
        return None
    finally:
        sock.settimeout(old)


def handle(conn, peer):
    try:
        sni = read_client_hello_sni(conn)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(CERT, KEY)
        ctx.set_alpn_protocols(["http/1.1"])
        tls = ctx.wrap_socket(conn, server_side=True)
        host = sni or tls.server_hostname or "genai-rest.avast.com"
        log({"kind": "tls", "host": host, "peer": str(peer), "sni": sni})
        serve_http(tls, host, peer)
    except Exception as exc:
        log({"kind": "error", "peer": str(peer), "error": f"{type(exc).__name__}: {exc}"})
    finally:
        try:
            conn.close()
        except Exception:
            pass


def main():
    print(f"capture log -> {LOG}", flush=True)
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", LISTEN_PORT))
    srv.listen(128)
    print(f"[capture] listening on 0.0.0.0:{LISTEN_PORT}", flush=True)
    while True:
        conn, peer = srv.accept()
        conn.settimeout(TIMEOUT)
        threading.Thread(target=handle, args=(conn, peer), daemon=True).start()


if __name__ == "__main__":
    main()
