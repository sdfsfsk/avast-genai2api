"""Dump the plaintext WebSocket payloads the Avast client sends and receives.

Hooking winsock only shows TLS ciphertext, so this hooks libcurl's WebSocket
primitives instead:

    curl_ws_send  ~ AvastUI.exe+0xa68550   (CURL*, const void *buffer, size_t buflen, ...)
    curl_ws_recv  ~ AvastUI.exe+0xa683b0   (CURL*, void *buffer, size_t buflen, size_t *recv, ...)

Run:  python frida_ws2.py <pid>
"""
import sys
import time

import frida

RVA_SEND = 0xA68550
RVA_RECV = 0xA683B0

JS = r"""
var mod = Process.getModuleByName('AvastUI.exe');
var SEND = mod.base.add(%d);
var RECV = mod.base.add(%d);

function emit(kind, ptr, len) {
  if (len <= 0 || len > 200000) return;
  try {
    var bytes = new Uint8Array(ptr.readByteArray(len));
    var arr = [];
    for (var i = 0; i < len; i++) arr.push(bytes[i]);
    send({ kind: kind, bytes: arr });
  } catch (e) { send({ kind: 'err', msg: String(e) }); }
}

Interceptor.attach(SEND, {
  onEnter: function (args) {
    emit('client->server', args[1], args[2].toInt32());
  }
});

Interceptor.attach(RECV, {
  onLeave: function (retval) {
    // args are gone here; use the saved values from onEnter via this.ctx
    if (this.outLen && this.outLen > 0) {
      // buffer already filled by libcurl
      try {
        var bytes = new Uint8Array(this.outBuf.readByteArray(this.outLen));
        var arr = [];
        for (var i = 0; i < this.outLen; i++) arr.push(bytes[i]);
        send({ kind: 'server->client', bytes: arr });
      } catch (e) {}
    }
  },
  onEnter: function (args) {
    this.outBuf = args[1];
    this.outLen = 0;
    this.recvPtr = args[3];
  }
});

// after curl_ws_recv returns, the requested byte count is no longer known,
// so also hook the return of the outer wrapper by reading the meta frame.
send({ info: 'hooked', base: mod.base.toString() });
""" % (RVA_SEND, RVA_RECV)


def on_message(msg, data):
    if msg["type"] == "error":
        print("  [frida error]", msg.get("description"), flush=True)
        return
    p = msg["payload"]
    if "info" in p:
        print("  hooked, base", p["base"], flush=True)
        return
    if p.get("kind") == "err":
        print("  err", p["msg"], flush=True)
        return
    raw = bytes(p["bytes"])
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = "<binary " + raw[:80].hex() + ">"
    line = f"  [{p['kind']}] {text[:2000]}"
    with open("ws_plain.log", "a", encoding="utf-8") as fh:
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
    print("hooked curl_ws_send/recv; trigger a chat now", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        session.detach()


if __name__ == "__main__":
    main()
