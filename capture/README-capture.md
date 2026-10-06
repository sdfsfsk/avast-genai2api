# capture/ — how the protocol was recovered

These are the one-off tools used to reverse the Avast Assistant API on the
author's machine. They are kept because the technique is reusable, not because
you need them to run the gateway.

**None of the artifacts they produce are committed** — `capture.jsonl`, the
Frida dumps and the capture CA all contain live tokens, so `.gitignore` keeps
them out.

## The problem, in short

The assistant UI is a CEF page talking to a native module inside
`AvastUI.exe`. Nothing useful is in the page source, and the traffic is TLS.
Getting at it needed three separate tricks.

### 1. Redirecting the two hostnames

`genai-rest.avast.com` and `genai-ws.avast.com` had to reach a local proxy:

* **hosts entries do not work** — Avast self-defense deletes them within
  seconds.
* `proxy.ini` does not work — self-defense blocks writes to it.
* What did work: an **NRPT rule** (`setup_nrpt.ps1`) pointing the names at a
  local resolver (`dnsd.py`), which answers `127.0.0.1`. Self-defense ignores
  the NRPT store.

`mitm.py` is the proxy: it terminates TLS with `certs/server.crt`, logs every
request, and relays to the real origin over its own TLS connection. It also
answers DoH queries locally, because the WebSocket module resolves through
`dns.google` / `cloudflare-dns.com` rather than the system resolver.

### 2. Trusting the proxy's certificate

`certutil -addstore` installs the capture CA, but self-defense makes it
impossible to *remove* it the normal way — deleting the registry key directly
does work:

```
HKCU\Software\Microsoft\SystemCertificates\Root\Certificates\<thumbprint>
```

`cleanup.ps1` puts the machine back the way it was.

### 3. Driving the UI

AvastUI has no accessibility tree, and synthetic clicks sent with
`mouse_event` are ignored while hover events are not. Posting the messages
straight to the CEF child window works:

```powershell
PostMessage(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, MAKELPARAM(x, y))
PostMessage(hwnd, WM_LBUTTONUP,   0,           MAKELPARAM(x, y))
```

`postmsg.ps1` / `drive.ps1` do that; typing works the same way with `WM_CHAR`.

### 4. When the WebSocket would not go through the proxy

The WebSocket module pins its peer address (`CURLOPT_RESOLVE`), so DNS tricks
never applied to it — that is why the proxy could capture REST but never chat.
Binding the resolved address on the loopback adapter
(`netsh interface ipv4 add address`) steers it, and `mitm.py` can then answer
the upgrade itself and log the frames the client sends.

## Frida notes

Frida only injects while **every** shield is disabled — self-defense alone is
not enough, the behavioural shield also refuses the agent
(`refused to load frida-agent`, or `VirtualAllocEx returned 0x00000005`).
After a hard-killed session the target will not accept a second injection;
restart `AvastUI.exe`. Output must be written to a UTF-8 file: the strings read
out of the target are not GBK-encodable and printing them kills the handler.

Useful addresses inside `AvastUI.exe` (subtract the image base for RVAs):

| symbol | address | how it was found |
|---|---|---|
| `curl_easy_setopt` | `+0xa63050` | the only function called with many distinct `CURLoption` codes |
| `curl_ws_send` | `+0xa69100` | call site `+0xa6592ce` loads `rcx`=CURL*, `rdx`=buffer, `r8`=len, `r9`=&sent, framesize 0, flags 1 |
| `curl_ws_recv` | `+0xa68df0` | called from the receiver at `+0xa659400` |
| `Curl_ws_request` | `+0xa68c30` | builds the `Upgrade: websocket` handshake |
| Avast WS client | `0x140658xxx`–`0x140659xxx` | log strings `Failed to send/receive WebSocket message` |
| NAPI `SendMessage` | `0x14064bxxx` | builds the JSON keys `session_id` / `text` / `intent` |

`frida_ws_send.py` hooks `curl_ws_send` and prints the exact JSON the client
puts on the wire. That was the intended way to learn the message body — it
turned out `sweep_bodies.py` (which just tries many shapes against the live
socket) found it first, and without needing any shield disabled.
