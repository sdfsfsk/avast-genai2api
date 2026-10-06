"""Minimal authoritative DNS server for the capture hostnames.

Answers A = 127.0.0.1 for the GenAI endpoints so the Avast client connects
to the local capture proxy. Used together with an NRPT rule, which does not
touch the hosts file (and therefore is left alone by Avast self-defense).
"""
import socket
import struct
import threading

LISTEN = ("127.0.0.1", 53)
NAMES = {"genai-rest.avast.com", "genai-ws.avast.com"}
ANSWER_IP = socket.inet_aton("127.0.0.1")


def parse_qname(data, off):
    labels = []
    while True:
        ln = data[off]
        off += 1
        if ln == 0:
            break
        labels.append(data[off:off + ln].decode("latin-1"))
        off += ln
    return ".".join(labels), off


def build_response(data):
    if len(data) < 12:
        return None
    qid = data[:2]
    flags = struct.unpack(">H", data[2:4])[0]
    qdcount = struct.unpack(">H", data[4:6])[0]
    if qdcount < 1:
        return None
    name, off = parse_qname(data, 12)
    qtype, qclass = struct.unpack(">HH", data[off:off + 4])
    question = data[12:off + 4]
    lower = name.lower().rstrip(".")

    if lower in NAMES and qtype in (1, 255):
        # answer with A 127.0.0.1
        hdr = qid + struct.pack(">HHHHH", 0x8180, 1, 1, 0, 0)
        ans = b"\xc0\x0c" + struct.pack(">HHIH", 1, 1, 60, 4) + ANSWER_IP
        return hdr + question + ans
    # NXDOMAIN for anything else
    hdr = qid + struct.pack(">HHHHH", 0x8183, 1, 0, 0, 0)
    return hdr + question


def handle_udp(sock):
    while True:
        try:
            data, addr = sock.recvfrom(2048)
        except OSError:
            break
        resp = build_response(data)
        if resp:
            sock.sendto(resp, addr)


def handle_tcp(conn):
    try:
        ln = conn.recv(2)
        if len(ln) < 2:
            return
        size = struct.unpack(">H", ln)[0]
        data = b""
        while len(data) < size:
            chunk = conn.recv(size - len(data))
            if not chunk:
                return
            data += chunk
        resp = build_response(data)
        if resp:
            conn.sendall(struct.pack(">H", len(resp)) + resp)
    except Exception:
        pass
    finally:
        conn.close()


def main():
    u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    u.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    u.bind(LISTEN)
    print(f"[dns] udp listening on {LISTEN[0]}:{LISTEN[1]}", flush=True)
    threading.Thread(target=handle_udp, args=(u,), daemon=True).start()

    t = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    t.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    t.bind(LISTEN)
    t.listen(32)
    print(f"[dns] tcp listening on {LISTEN[0]}:{LISTEN[1]}", flush=True)
    while True:
        conn, _ = t.accept()
        threading.Thread(target=handle_tcp, args=(conn,), daemon=True).start()


if __name__ == "__main__":
    main()
