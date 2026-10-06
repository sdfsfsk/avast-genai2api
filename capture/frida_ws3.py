"""Shotgun hook over the libcurl/Avast websocket write region.

Several candidate entry points in AvastUI.exe+0xa68xxx are instrumented at
once; whichever one carries the outgoing JSON payload identifies the real
frame-write function.

Run:  python frida_ws3.py <pid>
"""
import sys
import time

import frida

CANDIDATES = [
    0xA683B0, 0xA68532, 0xA68550, 0xA688A0, 0xA688C0, 0xA68C30,
    0xA68DDA, 0xA68DF0, 0xA687B2, 0xA68120,
]

JS = r"""
var mod = Process.getModuleByName('AvastUI.exe');
var addrs = %s;

function looksLikeJson(p) {
  try {
    var b = new Uint8Array(p.readByteArray(8));
    return b[0] === 0x7b || b[0] === 0x5b;   // '{' or '['
  } catch (e) { return false; }
}

function dump(p, max) {
  try {
    var s = p.readCString(max || 4096);
    return s;
  } catch (e) { return '<err ' + e.message + '>'; }
}

addrs.forEach(function (off) {
  var target = mod.base.add(off);
  try {
    Interceptor.attach(target, {
      onEnter: function (args) {
        var hit = null, where = '';
        for (var i = 0; i < 4; i++) {
          if (looksLikeJson(args[i])) { hit = args[i]; where = 'arg' + i; break; }
        }
        if (hit) {
          send({ off: off, which: where,
                 text: dump(hit, 8000),
                 regs: [args[0].toString(), args[1].toString(), args[2].toString(), args[3].toString()] });
        } else {
          send({ off: off, peek: [args[0].toString(), args[1].toString(), args[2].toString(), args[3].toString()],
                 first: (function(){ try { var b=new Uint8Array(args[1].readByteArray(4)); return b[0]+','+b[1]+','+b[2]+','+b[3]; } catch(e){ return '?'; } })() });
        }
      }
    });
    send({ info: 'attached ' + off.toString(16) });
  } catch (e) {
    send({ info: 'FAILED ' + off.toString(16) + ' ' + e.message });
  }
});
""" % ("[" + ",".join(hex(c) for c in CANDIDATES) + "]")


COUNT = {}


def on_message(msg, data):
    if msg["type"] == "error":
        print("  [frida]", msg.get("description"), flush=True)
        return
    p = msg["payload"]
    line = None
    if "info" in p:
        line = "  " + p["info"]
    elif "text" in p:
        line = f"  *** JSON at +{p['off']:x} via {p['which']}: {p['text'][:1500]!r}"
    with open("ws_shot.log", "a", encoding="utf-8") as fh:
        if line:
            fh.write(line + "\n")
    if line and "peek" not in str(p):
        pass
    if line and ("JSON" in line or "attached" in line or "FAILED" in line):
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
    print("shotgun attached; trigger a chat now", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        session.detach()


if __name__ == "__main__":
    main()
