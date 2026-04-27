import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

void main() {
  runApp(const VoiceInputApp());
}

class VoiceInputApp extends StatelessWidget {
  const VoiceInputApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: '实时输入',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF0F6B5F),
          brightness: Brightness.light,
        ),
        useMaterial3: true,
        fontFamily: 'serif',
      ),
      home: const InputBridgePage(),
    );
  }
}

enum BridgeStatus {
  disconnected,
  connecting,
  connected,
  error,
}

class InputBridgePage extends StatefulWidget {
  const InputBridgePage({super.key});

  @override
  State<InputBridgePage> createState() => _InputBridgePageState();
}

class _InputBridgePageState extends State<InputBridgePage> {
  final TextEditingController _hostController = TextEditingController();
  final TextEditingController _urlController = TextEditingController();
  final TextEditingController _tokenController = TextEditingController();
  final TextEditingController _inputController = TextEditingController();
  final FocusNode _inputFocusNode = FocusNode();

  WebSocket? _socket;
  BridgeStatus _status = BridgeStatus.disconnected;
  String _statusDetail = '未连接';
  String _lastSentText = '';
  int _seq = 0;
  bool _isConnecting = false;
  Timer? _reconnectTimer;
  final List<Map<String, Object?>> _queue = <Map<String, Object?>>[];

  @override
  void initState() {
    super.initState();
    _hostController.text = '192.168.1.100:8787';
    _inputController.addListener(_syncInput);
  }

  @override
  void dispose() {
    _reconnectTimer?.cancel();
    _socket?.close();
    _hostController.dispose();
    _urlController.dispose();
    _tokenController.dispose();
    _inputController.dispose();
    _inputFocusNode.dispose();
    super.dispose();
  }

  void _parseComputerUrl() {
    _parseAndFillComputerUrl(_urlController.text.trim());
  }

  void _parseAndFillComputerUrl(String raw) {
    if (raw.isEmpty) {
      return;
    }

    final uri = Uri.tryParse(raw);
    if (uri == null || uri.host.isEmpty) {
      _setStatus(BridgeStatus.error, '电脑 URL 无法解析');
      return;
    }

    final port = uri.hasPort ? uri.port : 8787;
    _hostController.text = '${uri.host}:$port';
    _tokenController.text = uri.queryParameters['token'] ?? _tokenController.text;
    _setStatus(BridgeStatus.disconnected, '已解析 URL');
  }

  Future<void> _scanQrCode() async {
    final result = await Navigator.of(context).push<String>(
      MaterialPageRoute<String>(
        builder: (_) => const QrScanPage(),
      ),
    );
    if (result == null || result.trim().isEmpty) {
      return;
    }
    _urlController.text = result.trim();
    _parseAndFillComputerUrl(result.trim());
  }

  Uri? get _wsUri {
    final host = _hostController.text.trim();
    final token = _tokenController.text.trim();
    if (host.isEmpty || token.isEmpty) {
      return null;
    }

    final normalizedHost = host
        .replaceFirst(RegExp(r'^https?://'), '')
        .replaceFirst(RegExp(r'^wss?://'), '')
        .split('/')
        .first;
    return Uri(
      scheme: 'ws',
      host: normalizedHost.contains(':')
          ? normalizedHost.split(':').first
          : normalizedHost,
      port: normalizedHost.contains(':')
          ? int.tryParse(normalizedHost.split(':').last)
          : 8787,
      path: '/ws',
      queryParameters: <String, String>{'token': token},
    );
  }

  Future<void> _connect({bool fromRetry = false}) async {
    if (_isConnecting) {
      return;
    }

    final uri = _wsUri;
    if (uri == null) {
      _setStatus(BridgeStatus.error, '请填写电脑地址和 token');
      return;
    }

    _reconnectTimer?.cancel();
    _isConnecting = true;
    _setStatus(BridgeStatus.connecting, '连接中');

    try {
      await _socket?.close();
      final socket = await WebSocket.connect(uri.toString());
      _socket = socket;
      _setStatus(BridgeStatus.connected, '已连接');
      _flushQueue();
      _inputFocusNode.requestFocus();

      socket.listen(
        _handleSocketMessage,
        onDone: () => _handleSocketClosed(retry: true),
        onError: (_) => _handleSocketClosed(retry: true),
        cancelOnError: true,
      );
    } catch (_) {
      _setStatus(BridgeStatus.error, fromRetry ? '重连失败' : '连接失败');
      _scheduleReconnect();
    } finally {
      _isConnecting = false;
    }
  }

  void _handleSocketMessage(dynamic data) {
    if (data is! String) {
      return;
    }
    try {
      final message = jsonDecode(data);
      if (message is Map && message['type'] == 'error') {
        _setStatus(BridgeStatus.error, '电脑端错误');
      }
    } catch (_) {
      // Ignore diagnostics that are not JSON.
    }
  }

  void _handleSocketClosed({required bool retry}) {
    if (!mounted) {
      return;
    }
    _socket = null;
    _setStatus(BridgeStatus.disconnected, '已断开');
    if (retry) {
      _scheduleReconnect();
    }
  }

  void _scheduleReconnect() {
    _reconnectTimer?.cancel();
    _reconnectTimer = Timer(const Duration(seconds: 2), () {
      if (mounted) {
        _connect(fromRetry: true);
      }
    });
  }

  void _setStatus(BridgeStatus status, String detail) {
    if (!mounted) {
      return;
    }
    setState(() {
      _status = status;
      _statusDetail = detail;
    });
  }

  void _syncInput() {
    final text = _inputController.text;
    if (text == _lastSentText) {
      return;
    }
    _lastSentText = text;
    _send(<String, Object?>{
      'type': 'sync_text',
      'token': _tokenController.text.trim(),
      'seq': ++_seq,
      'text': text,
    });
  }

  void _send(Map<String, Object?> message) {
    final socket = _socket;
    if (socket == null || socket.readyState != WebSocket.open) {
      _queue.add(message);
      _setStatus(BridgeStatus.error, '离线缓存 ${_queue.length}');
      return;
    }
    socket.add(jsonEncode(message));
  }

  void _flushQueue() {
    final pending = List<Map<String, Object?>>.from(_queue);
    _queue.clear();
    for (final message in pending) {
      _send(message);
    }
  }

  void _clearLocalInput() {
    _inputController.removeListener(_syncInput);
    _inputController.clear();
    _lastSentText = '';
    _inputController.addListener(_syncInput);
    _send(<String, Object?>{
      'type': 'reset_session',
      'token': _tokenController.text.trim(),
      'seq': ++_seq,
    });
    _inputFocusNode.requestFocus();
  }

  @override
  Widget build(BuildContext context) {
    final statusColor = switch (_status) {
      BridgeStatus.connected => const Color(0xFF0F6B5F),
      BridgeStatus.connecting => const Color(0xFF8B6B20),
      BridgeStatus.disconnected => const Color(0xFF766A5B),
      BridgeStatus.error => const Color(0xFFB6412D),
    };

    return Scaffold(
      backgroundColor: const Color(0xFFF4EFE6),
      body: SafeArea(
        child: Container(
          decoration: const BoxDecoration(
            gradient: LinearGradient(
              begin: Alignment.topLeft,
              end: Alignment.bottomRight,
              colors: <Color>[
                Color(0xFFF8F0DF),
                Color(0xFFF4EFE6),
                Color(0xFFE9DDCA),
              ],
            ),
          ),
          child: ListView(
            padding: const EdgeInsets.all(18),
            children: <Widget>[
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  const Expanded(
                    child: Text(
                      '实时输入',
                      style: TextStyle(
                        fontSize: 42,
                        height: 0.95,
                        fontWeight: FontWeight.w800,
                        letterSpacing: -2,
                      ),
                    ),
                  ),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                    decoration: BoxDecoration(
                      color: const Color(0xFFFFF7E9),
                      borderRadius: BorderRadius.circular(999),
                      border: Border.all(color: const Color(0xFFDCCFBC)),
                    ),
                    child: Text(
                      _statusDetail,
                      style: TextStyle(
                        color: statusColor,
                        fontWeight: FontWeight.w700,
                        fontSize: 13,
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 18),
              TextField(
                controller: _urlController,
                keyboardType: TextInputType.url,
                decoration: const InputDecoration(
                  labelText: '电脑完整 URL（可选）',
                  hintText: '粘贴 python server.py 打印的完整地址',
                  border: OutlineInputBorder(),
                  filled: true,
                  fillColor: Color(0xFFFFFAF1),
                ),
                onSubmitted: (_) => _parseComputerUrl(),
              ),
              const SizedBox(height: 8),
              OutlinedButton(
                onPressed: _parseComputerUrl,
                style: OutlinedButton.styleFrom(
                  minimumSize: const Size.fromHeight(46),
                ),
                child: const Text('从完整 URL 填充地址和 Token'),
              ),
              const SizedBox(height: 8),
              OutlinedButton.icon(
                onPressed: _scanQrCode,
                icon: const Icon(Icons.qr_code_scanner),
                label: const Text('扫码连接'),
                style: OutlinedButton.styleFrom(
                  minimumSize: const Size.fromHeight(46),
                ),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: _hostController,
                keyboardType: TextInputType.url,
                decoration: const InputDecoration(
                  labelText: '电脑地址',
                  hintText: '例如 192.168.1.20:8787',
                  border: OutlineInputBorder(),
                  filled: true,
                  fillColor: Color(0xFFFFFAF1),
                ),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: _tokenController,
                decoration: const InputDecoration(
                  labelText: 'Token',
                  hintText: '复制电脑终端地址里的 token 参数',
                  border: OutlineInputBorder(),
                  filled: true,
                  fillColor: Color(0xFFFFFAF1),
                ),
              ),
              const SizedBox(height: 12),
              FilledButton(
                onPressed: _connect,
                style: FilledButton.styleFrom(
                  minimumSize: const Size.fromHeight(52),
                  backgroundColor: const Color(0xFF0F6B5F),
                ),
                child: const Text('连接电脑'),
              ),
              const SizedBox(height: 18),
              TextField(
                controller: _inputController,
                focusNode: _inputFocusNode,
                minLines: 10,
                maxLines: 16,
                keyboardType: TextInputType.multiline,
                textInputAction: TextInputAction.newline,
                decoration: const InputDecoration(
                  hintText: '在这里输入或使用语音输入法，电脑光标处会实时出现同样的变化。',
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.all(Radius.circular(22)),
                  ),
                  filled: true,
                  fillColor: Color(0xFFFFFAF1),
                ),
                style: const TextStyle(fontSize: 22, height: 1.5),
              ),
              const SizedBox(height: 12),
              OutlinedButton(
                onPressed: _clearLocalInput,
                style: OutlinedButton.styleFrom(
                  minimumSize: const Size.fromHeight(50),
                ),
                child: const Text('清空手机输入框'),
              ),
              const SizedBox(height: 12),
              const Text(
                '使用前先把电脑光标放到目标输入位置。换行会在电脑端执行 Enter；删除会发送 Backspace。',
                style: TextStyle(color: Color(0xFF766A5B), height: 1.4),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class QrScanPage extends StatefulWidget {
  const QrScanPage({super.key});

  @override
  State<QrScanPage> createState() => _QrScanPageState();
}

class _QrScanPageState extends State<QrScanPage> {
  bool _handled = false;

  void _handleDetect(BarcodeCapture capture) {
    if (_handled) {
      return;
    }
    final value = capture.barcodes
        .map((barcode) => barcode.rawValue)
        .whereType<String>()
        .where((value) => value.trim().isNotEmpty)
        .firstOrNull;
    if (value == null) {
      return;
    }

    _handled = true;
    Navigator.of(context).pop(value);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(
        title: const Text('扫码连接'),
        backgroundColor: Colors.black,
        foregroundColor: Colors.white,
      ),
      body: Stack(
        fit: StackFit.expand,
        children: <Widget>[
          MobileScanner(onDetect: _handleDetect),
          Center(
            child: Container(
              width: 240,
              height: 240,
              decoration: BoxDecoration(
                border: Border.all(color: Colors.white, width: 3),
                borderRadius: BorderRadius.circular(20),
              ),
            ),
          ),
          const Positioned(
            left: 24,
            right: 24,
            bottom: 48,
            child: Text(
              '扫描电脑客户端窗口中的二维码',
              textAlign: TextAlign.center,
              style: TextStyle(
                color: Colors.white,
                fontSize: 16,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
