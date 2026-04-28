# Mobile FPS Controller

手机浏览器通过局域网 WebSocket 控制电脑输入，目标是把手机触摸屏当作 FPS 游戏控制器。

## 启动

双击 `start_fps_controller.bat`，点击 `Start service`，然后用手机扫描二维码或打开窗口里的 URL。

默认端口是 `8792`，避免和 `tablet_whiteboard` 的 `8791` 冲突。

## 控制映射

- 顶部灵敏度滑条：`1x` 到 `30x`。
- 右侧空白区域滑动：相对鼠标移动，用于拉视角。
- 左下虚拟摇杆：`W/A/S/D`，支持八方向组合。
- `FIRE`：鼠标左键。
- `ADS`：鼠标右键。
- `JUMP`：`Space`。
- `CTRL`：左 `Ctrl`。
- `RUN`：左 `Shift`。
- `R`：换弹。
- `E` / `F`：交互键。
- `TAB` / `ESC`：菜单键。
- `SAFE`：释放所有当前按下的键和鼠标按钮。
- `EDIT`：进入布局编辑模式，拖动摇杆和按钮，选中控件后用 `SIZE` 调整大小，点 `SAVE` 保存到手机本地。
- `RESET`：在布局编辑模式下恢复默认按钮位置。

## 注意

这个版本使用 Windows `SendInput` 注入输入。它适合普通桌面程序、无反作弊限制的游戏或测试场景；带强反作弊或独占 Raw Input 的在线 FPS 可能无法响应，或者不适合使用这种方式。

如果手机和电脑不在同一个局域网，手机将无法打开 URL。Windows 防火墙首次提示时需要允许 Python 在专用网络通信。
