# 手机实时输入到 macOS 光标

这是独立的 macOS 版本。整个目录可以单独复制到 Mac 上运行，不依赖项目根目录中的 Windows 版本文件。

## 安装

```bash
cd macOS_version
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 命令行运行

```bash
python3 server.py
```

启动后终端会打印类似地址：

```text
http://192.168.1.20:8787/?token=xxxx
```

手机和 Mac 连接同一个局域网，用手机浏览器打开该地址。先把 Mac 光标放到目标输入框，再在手机页面输入或使用手机语音输入法。

## 桌面客户端

```bash
python3 desktop_client.py
```

也可以运行：

```bash
./start_desktop_client.sh
```

桌面客户端会显示手机访问 URL 和二维码，手机 App 可以扫码连接，手机浏览器也可以直接打开该 URL。

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
