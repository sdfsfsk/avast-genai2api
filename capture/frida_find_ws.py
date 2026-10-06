"""Find the WebSocket write path by watching Avast's internal logger.

`AvastUI.exe+0xa7d5d0` is the infof()-style logger (it is called as
`log(data, fmt, a, b)` right before the WS frame write with the format string
"ws_cw_write(len=%zu, type=%d)"). Hooking it reveals both the caller address
(the real frame-write function) and the write size, which is how the frame
writer gets located.

Run:  python frida_find_ws.py <pid>
"""
import sys
import time

import frida

RVA_LOGGER = 0xA7D5D0

JS = r"""
var mod = Process.getModuleByName('AvastUI.exe');
var LOGGER = mod.base.add(%d);

function cstr(p) {
  try { return p.readCString(512); } catch (e) { return null; }
}

var seen = {};

Interceptor.attach(LOGGER, {
  onEnter: function (args) {
    var fmt = cstr(args[1]);
    if (!fmt) return;
    if (fmt.indexOf('ws') < 0 && fmt.indexOf('WS') < 0 &&
        fmt.indexOf('socket') < 0 && fmt.indexOf('frame') < 0) return;
    var caller = this.returnAddress.sub(mod.base).toString();
    var key = caller + '|' + fmt;
    var n = (seen[key] = (seen[key] || 0) + 1);
    if (n > 3) return;
    send({
      fmt: fmt,
      caller: caller,
      a2: args[2].toString(),
      a3: args[3].toString(),
      a2i: (function(){ try { return args[2].toInt32(); } catch(e){ return null; } })(),
      a3i: (function(){ try { return args[3].toInt32(); } catch(e){ return null; } })()
    });
  }
});

send({ info: 'logger hooked', base: mod.base.toString() });
""" % RVA_LOGGER


def on_message(msg, data):
    if msg["type"] == "error":
        print("  [frida]", msg.get("description"), flush=True)
        return
    p = msg["payload"]
    if "info" in p:
        print("  " + p["info"], p["base"], flush=True)
        return
    line = (f"  caller=+{p['caller']} fmt={p['fmt']!r} "
            f"a2={p['a2']}({p['a2i']}) a3={p['a3']}({p['a3i']})")
    with open("ws_find.log", "a", encoding="utf-8") as fh:
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
    print("logger hooked; trigger a chat now", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        session.detach()


if __name__ == "__main__":
    main()
