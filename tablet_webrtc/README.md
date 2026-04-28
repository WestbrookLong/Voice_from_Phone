# WebRTC 低延迟移动端远程实验版

这个目录是独立于现有 `server.py` / `static/tablet.html` 的重构实现，目标是降低移动端远程模式的屏幕回传延迟。

旧版移动端远程路径是：

```text
mss 截屏 -> Pillow JPEG 编码 -> WebSocket binary frame -> 浏览器解码 JPEG -> canvas 绘制
```

新版改成：

```text
mss 截屏 -> aiortc VideoStreamTrack -> WebRTC 视频轨 -> 移动端 video 元素
移动端 Pointer Events -> 本地 stroke buffer -> WebRTC DataChannel -> 服务端 stroke 回放 -> Win32 SendInput
```

## 为什么会更低延迟

- WebRTC 视频轨会走浏览器原生实时媒体管线，而不是每帧创建 JPEG blob 再手动绘制 canvas。
- 指针输入以完整 stroke 为单位缓存，本地蒙版先画，服务端按 stroke 队列顺序回放，快速连续两笔不会互相覆盖状态。
- 服务端复用单线程屏幕捕获 executor，避免每帧创建捕获器。
- 默认会把捕获画面缩到 `max_width=1600` 再编码，减少编码和网络负担。

## 安装

建议用独立虚拟环境，避免影响原工程：

```powershell
cd D:\Users\WESTBROOK\Projects\Voice_input\tablet_webrtc
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## 启动

```powershell
python server.py
```

或双击：

```text
start_webrtc_tablet.bat
```

启动后终端会打印：

```text
Open on mobile device: http://<电脑局域网 IP>:8790/?token=<token>
```

在手机或平板浏览器中打开这个地址即可。

## 参数

```powershell
python server.py --port 8790 --monitor 1 --fps 45 --max-width 1600
```

- `--monitor`：捕获的显示器编号，默认 `1`。
- `--fps`：目标帧率，默认 `45`，最高限制到 `60`。
- `--max-width`：编码前最大宽度，默认 `1600`。想更清晰可调到 `1920`，想更低延迟可调到 `1280`。
- `--token`：固定 token。不传则每次随机生成。

浏览器 URL 也可以覆盖部分参数：

```text
http://电脑IP:8790/?token=xxx&fps=60&maxWidth=1280&monitor=1
```

## 当前功能

- WebRTC 屏幕视频流。
- WebRTC DataChannel 指针输入。
- Apple Pencil / 单指按下、移动、抬起映射到 Windows 鼠标。
- 双指上下滑动映射到鼠标滚轮。
- 可切换单指滚轮模式。
- 本地笔迹蒙版回显。
- 简单缩放控制。

## 当前限制

- 仍然是鼠标事件注入，不是 Windows Ink/HID 笔设备，因此没有真实压感。
- 当前只做 LAN 内 WebRTC 信令，没有 STUN/TURN 配置；跨公网连接要再加信令和 TURN。
- aiortc 的编码路径通常是软件编码，最终延迟取决于 CPU、分辨率和浏览器协商到的 codec。若要进一步降低延迟，下一步应迁移到 Windows.Graphics.Capture / DXGI + 硬件 H.264 编码。
- 当前版本专注移动端远程，不包含手机语音输入功能。
