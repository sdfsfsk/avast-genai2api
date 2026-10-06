# capture/ —— 协议是怎么还原出来的

这里是当年在作者机器上逆向 Avast 助手 API 用的一次性工具。留下来是因为手法可以
复用，而不是因为跑网关需要它们。

**它们产生的产物一个都没提交** —— `capture.jsonl`、Frida 的各种 dump、抓包 CA
里都含有效 token，`.gitignore` 把它们挡在外面。

> **English**: [README-capture.en.md](README-capture.en.md)

## 一句话概括问题

助手界面是一个 CEF 页面，和 `AvastUI.exe` 里的原生模块通信。页面源码里没有任何
有用的东西，流量又是 TLS 加密的。要拿到它得用三个各自独立的技巧。

### 一、把两个域名拐到本地

`genai-rest.avast.com` 和 `genai-ws.avast.com` 必须走到本地代理上：

* **改 hosts 没用** —— Avast 自我保护几秒内就会把条目删掉。
* 改 `proxy.ini` 也没用 —— 自我保护阻止写入。
* **能用的是 NRPT 规则**（`setup_nrpt.ps1`）：把域名指到本地解析器
  （`dnsd.py`），它回答 `127.0.0.1`。自我保护不监控 NRPT 存储。

`mitm.py` 就是那个代理：用 `certs/server.crt` 终结 TLS、记录每个请求，再用自己的
TLS 连接转发到真实源站。它还会在本地应答 DoH 查询，因为 WebSocket 模块是通过
`dns.google` / `cloudflare-dns.com` 解析的，不走系统解析器。

### 二、让客户端信任代理的证书

用 `certutil -addstore` 把抓包 CA 装进证书库没问题，但自我保护让**正常方式删不掉**
它 —— 直接删注册表项才行：

```
HKCU\Software\Microsoft\SystemCertificates\Root\Certificates\<thumbprint>
```

`cleanup.ps1` 会把机器恢复原状。

### 三、驱动界面

AvastUI 没有无障碍树，而且用 `mouse_event` 发的合成点击会被忽略（鼠标移动事件却
不会被忽略）。**把消息直接投递给 CEF 子窗口**才行：

```powershell
PostMessage(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, MAKELPARAM(x, y))
PostMessage(hwnd, WM_LBUTTONUP,   0,           MAKELPARAM(x, y))
```

`postmsg.ps1` / `drive.ps1` 就是干这个的；打字同理，用 `WM_CHAR`。

### 四、WebSocket 死活不走代理怎么办

WebSocket 模块会**把对端地址写死**（`CURLOPT_RESOLVE`），所以 DNS 那套技巧对它
一律无效 —— 这就是代理能抓到 REST 却永远抓不到聊天的原因。把解析出来的地址绑到
回环网卡上（`netsh interface ipv4 add address`）就能把它引过来，这时 `mitm.py`
甚至可以自己应答 upgrade，直接记录客户端发出去的帧。

## Frida 笔记

Frida 只有在**所有**防护都关闭时才能注入 —— 只关自我保护不够，行为防护也会拒绝
agent（`refused to load frida-agent`，或 `VirtualAllocEx returned 0x00000005`）。
被硬杀的会话之后，同一目标进程无法二次注入；重启 `AvastUI.exe` 换新的。输出必须
写到 UTF-8 文件：从目标读出来的字符串不是 GBK 能编码的，直接 print 会让处理函数崩掉。

`AvastUI.exe` 里几个有用的地址（减去映像基址就是 RVA）：

| 符号 | 地址 | 怎么找到的 |
|---|---|---|
| `curl_easy_setopt` | `+0xa63050` | 唯一一个被大量不同 `CURLoption` 值调用的函数 |
| `curl_ws_send` | `+0xa69100` | 调用点 `+0xa6592ce` 载入 `rcx`=CURL*、`rdx`=buffer、`r8`=len、`r9`=&sent，framesize 0、flags 1 |
| `curl_ws_recv` | `+0xa68df0` | 被 `+0xa659400` 的接收函数调用 |
| `Curl_ws_request` | `+0xa68c30` | 构造 `Upgrade: websocket` 握手 |
| Avast WS 客户端 | `0x140658xxx`–`0x140659xxx` | 日志字符串 `Failed to send/receive WebSocket message` |
| NAPI `SendMessage` | `0x14064bxxx` | 构造 JSON 键 `session_id` / `text` / `intent` |

`frida_ws_send.py` 挂 `curl_ws_send`，打印客户端放到网线上的原始 JSON。这本来是
用来搞清楚消息体的正路 —— 结果 `sweep_bodies.py`（拿各种结构去怼真实 socket）
先找到了，而且完全不需要关闭任何防护。
