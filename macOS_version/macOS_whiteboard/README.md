# iPad 白板桥接到 macOS

这是独立的 macOS 白板版本，放在 `macOS_version/macOS_whiteboard/` 下运行，不依赖外层的语音输入服务文件。

它统一提供两种控制入口：

- 网页白板：直接在 iPad Safari 或其他浏览器里打开 URL。
- 原生 iPad App：使用 `../ipad_whiteboard_app`，在 App 的 Connect 弹窗里粘贴同一台 Mac 显示出来的连接地址。

两种方式都把笔迹按比例发送到 Mac；Mac 端再把这些笔迹转换成鼠标按下、移动、抬起事件，作用在当前前台的绘图软件或网页画板上。

## 启动

```bash
cd /Users/ayana/Voice_from_Phone/macOS_version/macOS_whiteboard
./start_desktop_client.sh
```

脚本会在本目录内创建 `.venv`，安装 `requirements.txt`，然后打开桌面控制窗口。

在窗口里点击 **Start service**。服务真正启动后会同时显示：

- `方式 A: 网页白板`：给 iPad 浏览器打开，二维码也对应这个入口。
- `方式 B: iPad 原生 App`：给 `ipad_whiteboard_app` 粘贴使用。

## 使用流程

1. Mac 和 iPad 连到同一个可互通网络，优先用同一个手机热点或家庭 Wi-Fi。
2. 运行 `./start_desktop_client.sh`。
3. 点击 **Start service**。
4. 二选一：
   - 网页方式：用 iPad 扫窗口里的二维码，或直接打开 `方式 A: 网页白板`。
   - App 方式：打开 `../ipad_whiteboard_app`，把 `方式 B: iPad 原生 App` 粘贴到 Connect 弹窗。
5. 在 Mac 上打开真正要绘制的目标，例如 Blackboard、PDF 标注、Freeform、网页画板等。
6. 把目标窗口放到前台，手动选好画笔/颜色/橡皮。
7. 在 iPad 网页或 App 里书写，Mac 目标窗口会收到对应鼠标拖动。

## 注意

- 网页方式和 App 方式可以共用同一个服务，但一般只保留一个主要控制端更稳。
- 网页白板里的 `Pen` 在 iPad 本地画黑线，`Eraser` 只擦 iPad 本地画布，`Clear` 只清空 iPad 本地画布。
- 原生 App 额外支持 `PC Shot` 和 `Stream`，因为 Mac 端现在已经提供了 `/snapshot` 和 `/screen`。
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
