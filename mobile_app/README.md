# Flutter 手机端 App

这个目录是手机端 Flutter/Dart 客户端源码，复用电脑端 `server.py` 的 WebSocket 协议。

## 准备

本机需要安装 Flutter SDK。当前机器没有检测到 `flutter` / `dart` 命令，所以这里没有实际编译 APK。

安装 Flutter 后，在本目录生成平台工程：

```powershell
cd D:\Users\WESTBROOK\Projects\Voice_input\mobile_app
flutter create --project-name voice_input_mobile .
flutter pub get
flutter run
```

如果 `flutter create` 询问是否覆盖 `lib/main.dart`，选择不覆盖，保留当前实现。

## 使用

1. 电脑端运行：

```powershell
cd D:\Users\WESTBROOK\Projects\Voice_input
python server.py
```

2. 电脑终端会打印：

```text
http://192.168.x.x:8787/?token=xxxx
```

3. App 中填写：

- 推荐方式：点击“扫码连接”，扫描电脑桌面客户端窗口中的二维码
- 电脑完整 URL：可以直接粘贴 `python server.py` 打印的完整地址，然后点击“从完整 URL 填充地址和 Token”
- 电脑地址：`192.168.x.x:8787`
- Token：上面 URL 的 `token` 参数

4. 点击“连接电脑”，然后把电脑光标放到目标输入框。手机 App 中输入、语音输入、换行、删除都会同步到电脑。

语音输入法在句子结束后如果回头修正前文，App 会发送当前完整文本，电脑端会从差异位置开始退格并重打一段尾部；普通追加仍是即时流式输入。

## Android 权限

生成 Android 工程后，确认 `android/app/src/main/AndroidManifest.xml` 有网络权限：

```xml
<uses-permission android:name="android.permission.INTERNET" />
```

局域网明文 `ws://` 在较新 Android 上通常可用；如果被系统拦截，需要在 Android 网络安全配置中允许 cleartext traffic。
