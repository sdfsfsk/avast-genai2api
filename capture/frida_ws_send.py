"""Dump the exact JSON the Avast client writes to the GenAI WebSocket.

curl_ws_send was located at AvastUI.exe+0xa69100 by following the send path in
Avast's own client: the call site at 0xa6592ce loads rcx = CURL*, rdx = buffer,
r8 = length, r9 = &sent, framesize = 0 on the stack and flags = 1
(CURLWS_TEXT) - i.e. curl_ws_send(CURL*, const void*, size_t, size_t*,
curl_off_t, unsigned).

Run:  python frida_ws_send.py <pid>
"""
import sys
import time

import frida

RVA_WS_SEND = 0xA69100

JS = r"""
var mod = Process.getModuleByName('AvastUI.exe');
var SEND = mod.base.add(%d);

Interceptor.attach(SEND, {
  onEnter: function (args) {
    try {
      var n = args[2].toInt32();
      if (n <= 0 || n > 100000) return;
      var bytes = new Uint8Array(args[1].readByteArray(n));
      var arr = [];
      for (var i = 0; i < n; i++) arr.push(bytes[i]);
      send({ len: n, bytes: arr });
    } catch (e) {
      send({ err: String(e) });
    }
  }
});

send({ info: 'curl_ws_send hooked', base: mod.base.toString(), at: SEND.toString() });
""" % RVA_WS_SEND


def on_message(msg, data):
    if msg["type"] == "error":
        print("  [frida]", msg.get("description"), flush=True)
        return
    p = msg["payload"]
    if "info" in p:
        print(f"  {p['info']} base={p['base']} at={p['at']}", flush=True)
        return
    if "err" in p:
        print("  err", p["err"], flush=True)
        return
    raw = bytes(p["bytes"])
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = "<binary " + raw[:120].hex() + ">"
    line = f"  *** curl_ws_send len={p['len']}: {text}"
    with open("ws_send.log", "a", encoding="utf-8") as fh:
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
    print("hooked curl_ws_send; trigger a chat now", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        session.detach()


if __name__ == "__main__":
    main()
