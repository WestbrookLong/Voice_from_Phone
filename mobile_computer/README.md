# Mobile Computer

手机和平板通过局域网浏览器控制 Windows 电脑。

## 启动

```powershell
cd D:\Users\WESTBROOK\Projects\Voice_input\mobile_computer
pip install -r requirements.txt
python desktop_client.py
```

默认端口是 `8788`。启动服务后，桌面窗口会显示两个地址：

- Phone computer control: 手机控制页。
- iPad display remote: 平板显示和触控页，先对齐 FlowBridge 的移动端远程能力。

## 公网连接

桌面客户端提供可选的 `Start public` 按钮，使用 Cloudflare Tunnel 把本机 `127.0.0.1:8788` 暴露为临时公网 HTTPS 地址。

默认会查找：

```text
D:\download_program\cloudflared.exe
```

公网连接成功后，窗口会生成两条公网地址：

- Public phone control
- Public iPad remote

公网地址仍然带 session token。不要把公网 URL 发给不信任的人。

## 手机控制页

- 手机端不显示电脑屏幕，只作为控制器使用。
- 中间摇杆：相对移动电脑鼠标。
- 虚拟按键：`Shift`、`Ctrl`、`Alt`、方向键、`Tab`、`Esc`、`Backspace`、`Space`、左键、右键。
- 右下角键盘键：唤醒手机输入法键盘，没有可见输入框。
- 顶部模式键：
  - `键盘`: 手机英文键盘按键映射为电脑键盘按键。
  - `输入法`: 手机输入法文本按 Unicode 注入电脑当前光标处，行为类似 FlowBridge 文本注入。
- `释放`: 释放所有当前按下的虚拟键和鼠标键。

## 平板显示页

- 平板端继续显示电脑屏幕并支持触控。
- 服务端会在屏幕画面中叠加当前电脑鼠标位置标记，便于平板端定位鼠标。

## 注意

这个项目使用 Windows `SendInput` 注入输入。控制管理员权限窗口时，桌面端也需要用管理员权限运行。
