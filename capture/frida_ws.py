"""Dump WebSocket frames the Avast client sends, by hooking winsock send.

The client negotiates permessage-deflate on the GenAI socket, so text frames
show up either as plain JSON (0x81) or as DEFLATE-compressed payloads (RSV1 set,
first byte 0xC1). Both shapes are reported; compressed ones are inflated with
zlib.

Run:  python frida_ws.py <pid>
"""
import json
import sys
import time

import frida

JS = r"""
var ws2 = Process.getModuleByName('ws2_32.dll');
var sendPtr = ws2.getExportByName('send');
var wsaSend = null;
try { wsaSend = ws2.getExportByName('WSASend'); } catch (e) {}

function report(buf, len, via) {
  if (len < 2) return;
  var b0 = buf[0];
  var opcode = b0 & 0x0f;
  if (opcode !== 1 && opcode !== 2) return;   // only text/binary frames
  var masked = (buf[1] & 0x80) !== 0;
  var plen = buf[1] & 0x7f;
  var off = 2;
  if (plen === 126) { plen = (buf[2] << 8) | buf[3]; off = 4; }
  else if (plen === 127) { off = 10; plen = len - 10; }
  var mask = null;
  if (masked) { mask = [buf[off], buf[off+1], buf[off+2], buf[off+3]]; off += 4; }
  if (off + plen > len) plen = len - off;
  var out = [];
  for (var i = 0; i < plen; i++) {
    var v = buf[off + i];
    if (mask) v ^= mask[i % 4];
    out.push(v);
  }
  // only care about JSON payloads; the same hook sees DNS packets too
  if (out.length < 2) return;
  var rsv1 = (b0 & 0x40) !== 0;
  if (!rsv1 && out[0] !== 0x7b && out[0] !== 0x5b) return;
  send({ via: via, rsv1: rsv1, opcode: opcode, bytes: out });
}

Interceptor.attach(sendPtr, {
  onEnter: function (args) {
    try {
      var len = args[2].toInt32();
      if (len > 1 && len < 200000) {
        var buf = new Uint8Array(args[1].readByteArray(len));
        report(buf, len, 'send');
      }
    } catch (e) {}
  }
});

if (wsaSend) {
  Interceptor.attach(wsaSend, {
    onEnter: function (args) {
      try {
        var n = args[2].toInt32();
        var arr = args[1];
        for (var i = 0; i < n; i++) {
          var wsabuf = arr.add(i * 16);
          var len = wsabuf.readU32();
          var p = wsabuf.add(8).readPointer();
          if (len > 1 && len < 200000) {
            var buf = new Uint8Array(p.readByteArray(len));
            report(buf, len, 'WSASend');
          }
        }
      } catch (e) {}
    }
  });
}

send({ info: 'hooked send', ws2: ws2.base.toString() });
"""


def on_message(msg, data):
    if msg["type"] == "error":
        print("  [frida error]", msg.get("description"), flush=True)
        return
    p = msg["payload"]
    if "info" in p:
        print(" ", p["info"], p["ws2"], flush=True)
        return
    raw = bytes(p["bytes"])
    if p.get("rsv1"):
        try:
            import zlib
            raw = zlib.decompressobj(-zlib.MAX_WBITS).decompress(raw)
            tag = "inflated"
        except Exception as exc:
            tag = f"deflate-fail({exc})"
    else:
        tag = "plain"
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw[:200].hex()
    line = f"  [{p['via']}/{tag}] {text[:1500]}"
    with open("ws_frames.log", "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        print(line.encode("ascii", "backslashreplace").decode(), flush=True)


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "AvastUI.exe"
    if target.isdigit():
        target = int(target)
    session = frida.attach(target)
    script = session.create_script(JS)
    script.on("message", on_message)
    script.load()
    print("hooked ws2_32.send; trigger a chat now", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        session.detach()


if __name__ == "__main__":
    main()
