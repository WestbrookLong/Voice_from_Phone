# iPad 白板桥接到 macOS

这是独立的 macOS 白板版本，放在 `macOS_version/macOS_whiteboard/` 下运行，不依赖外层的语音输入服务文件。

它不会把 Mac 屏幕串流到 iPad。iPad 页面本地显示白板笔迹，同时把 Apple Pencil/触控笔迹按比例发送到 Mac；Mac 端把这些笔迹转换成鼠标按下、移动、抬起事件，作用在当前前台的绘图软件或网页画板上。

## 启动

```bash
cd /Users/ayana/Voice_from_Phone/macOS_version/macOS_whiteboard
./start_desktop_client.sh
```

脚本会在本目录内创建 `.venv`，安装 `requirements.txt`，然后打开桌面控制窗口。

在窗口里点击 **Start service**。服务真正启动后才会显示：

- `iPad端白板网址`：给 iPad 打开或扫码使用。
- `Mac端白板网址（仅本机预览/调试）`：只在 Mac 本机打开，用于预览网页白板，不会注入鼠标。

## 使用流程

1. Mac 和 iPad 连到同一个可互通网络，优先用同一个手机热点或家庭 Wi-Fi。
2. 运行 `./start_desktop_client.sh`。
3. 点击 **Start service**。
4. 用 iPad 扫窗口里的二维码，或打开 `iPad端白板网址`。
5. 在 Mac 上打开真正要绘制的目标，例如 Blackboard、PDF 标注、Freeform、网页画板等。
6. 把目标窗口放到前台，手动选好画笔/颜色/橡皮。
7. 在 iPad 白板页书写，Mac 目标窗口会收到对应鼠标拖动。

## 注意

- 不要把 `iPad端白板网址` 当作 Mac 绘图目标打开；它是远程控制端。
- `Mac端白板网址` 自动带 `preview=1`，只做本机预览，不会向服务端发送鼠标事件。
- `Pen` 在 iPad 本地画黑线，`Eraser` 只擦 iPad 本地画布，`Clear` 只清空 iPad 本地画布。
- 工具切换仍然需要在 Mac 的目标绘图软件中手动完成。

## macOS 权限

macOS 会拦截模拟鼠标输入。若 iPad 页面显示在线，但 Mac 目标窗口没有响应，请打开：

```text
系统设置 -> 隐私与安全性 -> 辅助功能
```

给 Terminal、iTerm、Python 或打包后的应用开启权限。修改权限后通常需要重启终端或重新运行脚本。

## 命令行调试

```bash
cd /Users/ayana/Voice_from_Phone/macOS_version/macOS_whiteboard
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python server.py --port 8791 --monitor 1
```

参数：

- `--monitor`：目标显示器编号，默认 `1`。
- `--port`：服务端口，默认 `8791`。
- `--token`：固定 URL token。不传时随机生成。
