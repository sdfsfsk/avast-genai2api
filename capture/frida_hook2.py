"""Hook curl_easy_setopt in AvastUI.exe and decode string / curl_slist options.

curl_easy_setopt lives at AvastUI.exe+0xa63050. The WebSocket setup sequence is
recognisable by CURLOPT_TIMEOUT_MS=3600000 plus CURLOPT_SSL_VERIFYPEER=1 and
CURLOPT_RESOLVE - meaning the client verifies the peer against the default CA
store and pins the peer address itself.

Run:  python frida_hook2.py <pid>
"""
import json
import sys
import time

import frida

RVA_SETOPT = 0xA63050
RAWLOG = "setopt_raw.jsonl"

JS = r"""
var mod = Process.getModuleByName('AvastUI.exe');
var SETOPT = mod.base.add(%d);

function cstr(p) {
  try {
    if (p.isNull()) return '<null ptr>';
    return p.readCString(4096);
  } catch (e) {
    try { return p.readUtf8String(256); }
    catch (e2) { return '<ERR ' + e2.message + ' @' + p.toString() + '>'; }
  }
}

// struct curl_slist { char *data; struct curl_slist *next; };
function slist(p, max) {
  var out = [];
  var node = p;
  for (var i = 0; i < (max || 40) && !node.isNull(); i++) {
    try {
      var d = node.readPointer();
      out.push(cstr(d));
      node = node.add(Process.pointerSize).readPointer();
    } catch (e) { out.push('<read error>'); break; }
  }
  return out;
}

var LAST = {};

Interceptor.attach(SETOPT, {
  onEnter: function (args) {
    var tag = args[1].toInt32();
    var val = args[2];
    var rec = { tag: tag };
    try {
      if (tag === 10002 || tag === 10004 || tag === 10018 || tag === 10029 ||
          tag === 10102 || tag === 10065 || tag === 10230 || tag === 10246 ||
          tag === 10279 || tag === 10005 || tag === 10006 || tag === 10030 ||
          tag === 10032) {
        rec.str = cstr(val);
      } else if (tag === 10023 || tag === 10203) {
        rec.list = slist(val);
      } else if (tag === 40309) {
        rec.blob = 'len=' + val.toString();
      } else if (tag >= 0 && tag < 10000) {
        rec.num = val.toInt32();
      } else {
        rec.ptr = val.toString();
      }
    } catch (e) { rec.err = String(e); }
    rec.ret = this.returnAddress.sub(mod.base).toString();
    send(rec);
  }
});

send({info: 'hooked', base: mod.base.toString(), setopt: SETOPT.toString()});
""" % RVA_SETOPT

SLIST_TAGS = {10023: "CURLOPT_HTTPHEADER", 10203: "CURLOPT_RESOLVE"}
STR_TAGS = {
    10002: "URL", 10004: "PROXY", 10018: "USERAGENT", 10029: "SSLCERT",
    10102: "SSLENGINE", 10065: "CAINFO", 10230: "PINNEDPUBLICKEY",
    10246: "PROXY_CAINFO", 10279: "DOH_URL", 10005: "WRITEDATA",
    10006: "READDATA", 10030: "SSLCERTTYPE", 10032: "SSLKEY",
}
NUM_TAGS = {
    64: "SSL_VERIFYPEER", 81: "SSL_VERIFYHOST", 216: "SSL_OPTIONS",
    141: "CONNECT_ONLY", 99: "NOSIGNAL", 84: "HTTP_VERSION",
    155: "TIMEOUT_MS", 156: "CONNECTTIMEOUT_MS", 107: "HTTPAUTH",
    181: "PROXYTYPE?", 265: "SSLCERT_BLOB?", 59: "POST", 52: "FOLLOWLOCATION",
    68: "MAXREDIRS", 69: "UNRESTRICTED_AUTH", 20: "LOW_SPEED_TIME?",
    19: "LOW_SPEED_LIMIT?", 45: "POSTFIELDS?", 46: "POSTFIELDSIZE?",
    47: "POSTFIELDSIZE_LARGE?", 111: "NETRC?", 113: "PUT?",
}


def fmt(rec):
    tag = rec.get("tag")
    name = STR_TAGS.get(tag) or SLIST_TAGS.get(tag) or NUM_TAGS.get(tag) or f"OPT_{tag}"
    if "str" in rec:
        return f"  {name} [{tag}] = {rec['str']!r}"
    if "list" in rec:
        return f"  {name} [{tag}] = {rec['list']}"
    if "num" in rec:
        return f"  {name} [{tag}] = {rec['num']}"
    if "blob" in rec:
        return f"  {name} [{tag}] = {rec['blob']}"
    return f"  {name} [{tag}] = {rec.get('ptr')}"


def safe_print(text):
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        print(text.encode("utf-8", "replace").decode("ascii", "replace"), flush=True)


def on_message(msg, data):
    if msg["type"] == "error":
        print("  [frida error]", msg.get("description"), flush=True)
        return
    p = msg["payload"]
    with open(RAWLOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(p, ensure_ascii=False) + "\n")
    if "info" in p:
        print(f"  {p['info']} base={p['base']} setopt={p['setopt']}", flush=True)
        return
    line = fmt(p)
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        print(line.encode("ascii", "backslashreplace").decode("ascii"), flush=True)


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "AvastUI.exe"
    if target.isdigit():
        target = int(target)
    session = frida.attach(target)
    script = session.create_script(JS)
    script.on("message", on_message)
    script.load()
    print("hooked; trigger a chat now", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        session.detach()


if __name__ == "__main__":
    main()
