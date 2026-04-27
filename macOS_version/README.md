# 手机实时输入到 macOS 光标

这是独立的 macOS 版本。整个目录可以单独复制到 Mac 上运行，不依赖项目根目录中的 Windows 版本文件。

## 安装

```bash
cd macOS_version
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 本地 HTTPS 证书

手机浏览器只有在 HTTPS 页面里才会允许网页调用麦克风。这个项目不需要买域名、公网服务器或内网穿透；在同一个局域网里使用本地 HTTPS 证书即可。

生成或更新证书：

```bash
python3 scripts/setup_https.py
```

证书会生成到 `certs/` 目录：

```text
certs/local-ca.crt   给手机安装和信任的 CA 证书
certs/server.crt     Mac 本地服务证书
certs/server.key     Mac 本地服务私钥
```

`certs/` 已被 `.gitignore` 忽略，不要提交这些文件。如果 Mac 的局域网 IP 变化，重新运行一次 `python3 scripts/setup_https.py`。

## 命令行运行

HTTP 模式可以继续用于普通文本输入：

```bash
python3 server.py
```

HTTPS 模式用于手机网页录音：

```bash
python3 server.py --https
```

启动后终端会打印类似地址：

```text
https://192.168.1.20:8787/?token=xxxx
```

手机和 Mac 连接同一个局域网，用手机浏览器打开该地址。先把 Mac 光标放到目标输入框，再在手机页面输入或使用手机语音输入法。

### 手机安装证书

服务启动后可以打开：

```text
https://<Mac-IP>:8787/cert/help
```

页面里有“下载 CA 证书”按钮。

iPhone / iPad：

1. 下载证书描述文件。
2. 打开“设置”，进入“已下载描述文件”，安装证书。
3. 打开“设置 -> 通用 -> 关于本机 -> 证书信任设置”。
4. 开启 `Voice from Phone Local CA` 的完全信任。
5. 重新打开 `https://<Mac-IP>:8787/?token=...`。

Android：

1. 下载 CA 证书。
2. 在系统设置中搜索“安装证书”或“CA 证书”。
3. 选择下载的证书并安装。
4. 重新打开 `https://<Mac-IP>:8787/?token=...`。

如果手机在安装证书前不允许打开 HTTPS 页面，可以先用 HTTP 模式打开：

```text
http://<Mac-IP>:8787/cert/help
```

下载并信任证书后，再停止服务并用 `python3 server.py --https` 重启。

## 阿里云百炼 Paraformer 实时语音输入

手机网页里有“开启语音输入”按钮。开启后，手机浏览器会录音并把 16kHz 单声道 PCM 音频发给 Mac，Mac 再代理连接阿里云百炼 Paraformer 实时语音识别，识别结果会直接注入 Mac 当前光标。

API Key 不要写入网页。运行服务前在 Mac 终端设置环境变量：

```bash
export DASHSCOPE_API_KEY="你的阿里云百炼 API Key"
python3 server.py
```

也可以在 `macOS_version/.env` 中保存本机默认 key：

```text
DASHSCOPE_API_KEY="你的阿里云百炼 API Key"
```

`.env` 已被 `.gitignore` 忽略，不会提交到 Git。环境变量优先级高于 `.env`。

如果用桌面客户端：

```bash
export DASHSCOPE_API_KEY="你的阿里云百炼 API Key"
python3 desktop_client.py
```

桌面客户端会优先使用 `certs/server.crt` 和 `certs/server.key`。如果证书存在，显示 HTTPS 地址和二维码；如果证书不存在，会以 HTTP 启动，并提示先生成 HTTPS 证书。

当前使用模型：

```text
paraformer-realtime-v2
```

注意：iPhone Safari/Chrome 对麦克风权限要求安全上下文，局域网 `http://Mac-IP:8787` 可能无法调用麦克风。若按钮提示录音不可用或启动失败，说明需要改成 HTTPS，或改用原生 iOS/Android App。Android 浏览器在部分系统上可能允许局域网 HTTP 录音，但不应依赖这个行为。

## 桌面客户端

```bash
python3 desktop_client.py
```

也可以运行：

```bash
./start_desktop_client.sh
```

桌面客户端会显示手机访问 URL 和二维码，手机 App 可以扫码连接，手机浏览器也可以直接打开该 URL。

桌面客户端里的“生成/更新 HTTPS 证书”按钮会调用 `scripts/setup_https.py`。生成后请重启服务，并让手机安装证书页面里的 CA 证书。

## macOS 权限

macOS 可能会拦截模拟键盘输入。若手机端已连接但 Mac 没有输入文字，请到：

```text
系统设置 -> 隐私与安全性 -> 辅助功能
```

给 Terminal、iTerm、Python 或正在运行脚本的应用开启权限。必要时也在：

```text
系统设置 -> 隐私与安全性 -> 输入监控
```

开启对应权限。修改权限后通常需要重启终端或重新运行 Python。

## 测试输入

```bash
python3 server.py --test-text "你好 macOS"
```

运行后 3 秒内把光标放到任意文本框。如果权限正确，文本框会自动输入测试文字。

## 行为说明

- 手机端无需点击发送，输入框变化会自动同步。
- 手机语音输入法如果修正前文，Mac 端会从差异位置开始删除并重打一段尾部。
- 手机端换行会在 Mac 端执行 Return。
- 删除文字会在 Mac 端发送对应数量的 Delete/Backspace。
- 清空手机输入框只会重置本次会话状态，不会删除 Mac 上已经输入的内容。
- 当前安全边界是局域网 + session token，不要直接暴露到公网。
