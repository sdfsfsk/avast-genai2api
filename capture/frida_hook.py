"""Hook curl_easy_setopt inside AvastUI.exe and log every option it sets.

curl_easy_setopt was located statically at RVA 0xa63050 (it is the only
function in the statically linked libcurl region that is called with many
distinct CURLoption codes, including CURLOPT_URL 10002 and CURLOPT_DOH_URL
10279). The call sites with distinct edx values were:

    74, 75, 92, 141, 155, 156, 320, 10002, 10203, 10279

Run:  python frida_hook.py [pid-or-name]
"""
import sys
import time

import frida

RVA_SETOPT = 0xA63050

# CURLOPTTYPE_OBJECTPOINT = 10000, FUNCTIONPOINT = 20000, OFF_T = 30000
OPTNAMES = {
    64: "CURLOPT_SSL_VERIFYPEER",
    74: "CURLOPT_SSL_VERIFYSTATUS/OTHER_74",
    75: "CURLOPT_OPT_75",
    81: "CURLOPT_SSL_VERIFYHOST",
    92: "CURLOPT_OPT_92",
    99: "CURLOPT_NOSIGNAL",
    141: "CURLOPT_CONNECT_ONLY",
    155: "CURLOPT_TIMEOUT_MS",
    156: "CURLOPT_CONNECTTIMEOUT_MS",
    320: "CURLOPT_OPT_320",
    10002: "CURLOPT_URL",
    10004: "CURLOPT_PROXY",
    10018: "CURLOPT_USERAGENT",
    10023: "CURLOPT_HTTPHEADER",
    10025: "CURLOPT_HTTPPOST",
    10029: "CURLOPT_SSLCERT",
    10030: "CURLOPT_SSLCERTTYPE",
    10032: "CURLOPT_SSLKEY",
    10065: "CURLOPT_CAINFO",
    10102: "CURLOPT_SSLENGINE",
    10246: "CURLOPT_PROXY_CAINFO",
    10279: "CURLOPT_DOH_URL",
    20079: "CURLOPT_WRITEFUNCTION",
    20080: "CURLOPT_READFUNCTION",
    20011: "CURLOPT_WRITEFUNCTION",
    40309: "CURLOPT_CAINFO_BLOB",
    10230: "CURLOPT_PINNEDPUBLICKEY",
}

JS = r"""
var mod = Process.getModuleByName('AvastUI.exe');
var SETOPT = mod.base.add(%d);
var LOG = [];
send({kind: 'info', base: mod.base.toString(), setopt: SETOPT.toString()});

Interceptor.attach(SETOPT, {
  onEnter: function (args) {
    var tag = args[1].toInt32();
    var val = args[2];
    var rec = { tag: tag, ptr: val.toString() };
    // string-ish options: read a C string
    if (tag >= 10000 && tag < 20000 || tag >= 40000) {
      try {
        var s = val.readUtf8String(512);
        if (s) { rec.str = s; }
      } catch (e) {}
    } else {
      try { rec.num = val.toInt32(); } catch (e) {}
    }
    try {
      rec.tid = this.threadId;
      rec.caller = this.returnAddress.sub(mod.base).toString();
    } catch (e) {}
    send(rec);
  }
});
""" % RVA_SETOPT


def on_message(msg, data):
    if msg["type"] == "error":
        print("  [frida error]", msg.get("description"))
        return
    p = msg["payload"]
    if p.get("kind") == "info":
        print(f"  base={p['base']}  setopt={p['setopt']}")
        return
    tag = p.get("tag")
    name = OPTNAMES.get(tag, f"OPT_{tag}")
    if "str" in p:
        print(f"  setopt({name} [{tag}]) = {p['str']!r}")
    elif "num" in p:
        print(f"  setopt({name} [{tag}]) = {p['num']}")
    else:
        print(f"  setopt({name} [{tag}]) = {p.get('ptr')}")


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "AvastUI.exe"
    if target.isdigit():
        target = int(target)
    session = frida.attach(target)
    script = session.create_script(JS)
    script.on("message", on_message)
    script.load()
    print(f"hooked curl_easy_setopt in pid {session._impl.pid if hasattr(session,'_impl') else target}")
    print("now trigger a chat in the Avast assistant; Ctrl+C to stop")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        session.detach()


if __name__ == "__main__":
    main()
