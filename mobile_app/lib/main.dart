import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

void main() {
  runApp(const FlowVoiceApp());
}

class FlowVoiceApp extends StatelessWidget {
  const FlowVoiceApp({super.key});

  @override
  Widget build(BuildContext context) {
    const bg = Color(0xFF10140F);
    const ink = Color(0xFF172016);
    const accent = Color(0xFFD9FF70);

    return MaterialApp(
      title: 'Flow Voice',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        brightness: Brightness.light,
        scaffoldBackgroundColor: bg,
        colorScheme: ColorScheme.fromSeed(
          seedColor: accent,
          brightness: Brightness.light,
        ),
        fontFamily: 'sans',
        inputDecorationTheme: InputDecorationTheme(
          filled: true,
          fillColor: const Color(0xFFFFF8E8),
          contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
          border: OutlineInputBorder(
            borderRadius: BorderRadius.circular(18),
            borderSide: const BorderSide(color: Color(0x1F172016)),
          ),
          enabledBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(18),
            borderSide: const BorderSide(color: Color(0x1F172016)),
          ),
          focusedBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(18),
            borderSide: const BorderSide(color: Color(0xFF3D5A21), width: 1.4),
          ),
          labelStyle: const TextStyle(color: Color(0xFF69705D)),
          hintStyle: const TextStyle(color: Color(0x66172016)),
        ),
        filledButtonTheme: FilledButtonThemeData(
          style: FilledButton.styleFrom(
            minimumSize: const Size.fromHeight(52),
            backgroundColor: accent,
            foregroundColor: ink,
            textStyle: const TextStyle(fontWeight: FontWeight.w900, fontSize: 16),
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
          ),
        ),
        outlinedButtonTheme: OutlinedButtonThemeData(
          style: OutlinedButton.styleFrom(
            minimumSize: const Size.fromHeight(48),
            foregroundColor: ink,
            side: const BorderSide(color: Color(0x26172016)),
            textStyle: const TextStyle(fontWeight: FontWeight.w800),
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
          ),
        ),
      ),
      home: const FlowVoicePage(),
    );
  }
}

enum BridgeStatus {
  disconnected,
  connecting,
  connected,
  error,
}

class FlowVoicePage extends StatefulWidget {
  const FlowVoicePage({super.key});

  @override
  State<FlowVoicePage> createState() => _FlowVoicePageState();
}

class _FlowVoicePageState extends State<FlowVoicePage> {
  final TextEditingController _urlController = TextEditingController();
  final TextEditingController _hostController = TextEditingController();
  final TextEditingController _tokenController = TextEditingController();
  final TextEditingController _inputController = TextEditingController();
  final FocusNode _inputFocusNode = FocusNode();

  WebSocket? _socket;
  BridgeStatus _status = BridgeStatus.disconnected;
  String _statusText = '离线';
  String _lastSentText = '';
  int _seq = 0;
  bool _isConnecting = false;
  Timer? _reconnectTimer;
  final List<Map<String, Object?>> _queue = <Map<String, Object?>>[];

  @override
  void initState() {
    super.initState();
    _hostController.text = '192.168.3.8:8787';
    _inputController.addListener(_syncInput);
  }

  @override
  void dispose() {
    _reconnectTimer?.cancel();
    _socket?.close();
    _urlController.dispose();
    _hostController.dispose();
    _tokenController.dispose();
    _inputController.dispose();
    _inputFocusNode.dispose();
    super.dispose();
  }

  Uri? get _wsUri {
    final hostText = _hostController.text.trim();
    final token = _tokenController.text.trim();
    if (hostText.isEmpty || token.isEmpty) {
      return null;
    }

    final normalized = hostText
        .replaceFirst(RegExp(r'^https?://'), '')
        .replaceFirst(RegExp(r'^wss?://'), '')
        .split('/')
        .first;
    final parts = normalized.split(':');
    final host = parts.first;
    final port = parts.length > 1 ? int.tryParse(parts.last) ?? 8787 : 8787;

    return Uri(
      scheme: 'ws',
      host: host,
      port: port,
      path: '/ws',
      queryParameters: <String, String>{'token': token},
    );
  }

  void _parseAndFillUrl(String raw) {
    final value = raw.trim();
    if (value.isEmpty) {
      return;
    }

    final uri = Uri.tryParse(value);
    if (uri == null || uri.host.isEmpty) {
      _setStatus(BridgeStatus.error, 'URL 无效');
      return;
    }

    final port = uri.hasPort ? uri.port : 8787;
    _hostController.text = '${uri.host}:$port';
    final token = uri.queryParameters['token'];
    if (token != null && token.isNotEmpty) {
      _tokenController.text = token;
    }
    _setStatus(BridgeStatus.disconnected, '已读取');
  }

  Future<void> _scanQrCode() async {
    final result = await Navigator.of(context).push<String>(
      MaterialPageRoute<String>(builder: (_) => const QrScanPage()),
    );
    if (result == null || result.trim().isEmpty) {
      return;
    }
    _urlController.text = result.trim();
    _parseAndFillUrl(result);
  }

  Future<void> _connect({bool fromRetry = false}) async {
    if (_isConnecting) {
      return;
    }

    final uri = _wsUri;
    if (uri == null) {
      _setStatus(BridgeStatus.error, '缺少地址');
      return;
    }

    _reconnectTimer?.cancel();
    _isConnecting = true;
    _setStatus(BridgeStatus.connecting, '连接中');

    try {
      await _socket?.close();
      final socket = await WebSocket.connect(uri.toString());
      _socket = socket;
      _setStatus(BridgeStatus.connected, '在线');
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
        _setStatus(BridgeStatus.error, '电脑错误');
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
    _setStatus(BridgeStatus.disconnected, '断开');
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

  void _setStatus(BridgeStatus status, String text) {
    if (!mounted) {
      return;
    }
    setState(() {
      _status = status;
      _statusText = text;
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
      _setStatus(BridgeStatus.error, '离线 ${_queue.length}');
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
      BridgeStatus.connected => const Color(0xFF255B2E),
      BridgeStatus.connecting => const Color(0xFF775F24),
      BridgeStatus.disconnected => const Color(0xFF69705D),
      BridgeStatus.error => const Color(0xFFC4533C),
    };

    return Scaffold(
      body: SafeArea(
        child: Container(
          decoration: const BoxDecoration(
            gradient: LinearGradient(
              begin: Alignment.topLeft,
              end: Alignment.bottomRight,
              colors: <Color>[
                Color(0xFF11180F),
                Color(0xFF1E2819),
                Color(0xFF0C100B),
              ],
            ),
          ),
          child: ListView(
            padding: const EdgeInsets.all(16),
            children: <Widget>[
              _Header(statusText: _statusText, statusColor: statusColor),
              const SizedBox(height: 16),
              _Panel(
                child: Column(
                  children: <Widget>[
                    TextField(
                      controller: _urlController,
                      keyboardType: TextInputType.url,
                      decoration: const InputDecoration(
                        labelText: '电脑二维码 URL',
                        hintText: '扫码会自动填入',
                      ),
                      onSubmitted: _parseAndFillUrl,
                    ),
                    const SizedBox(height: 10),
                    Row(
                      children: <Widget>[
                        Expanded(
                          child: OutlinedButton.icon(
                            onPressed: _scanQrCode,
                            icon: const Icon(Icons.qr_code_scanner),
                            label: const Text('扫码连接'),
                          ),
                        ),
                        const SizedBox(width: 10),
                        Expanded(
                          child: OutlinedButton(
                            onPressed: () => _parseAndFillUrl(_urlController.text),
                            child: const Text('读取 URL'),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 10),
                    TextField(
                      controller: _hostController,
                      keyboardType: TextInputType.url,
                      decoration: const InputDecoration(
                        labelText: '电脑地址',
                        hintText: '192.168.x.x:8787',
                      ),
                    ),
                    const SizedBox(height: 10),
                    TextField(
                      controller: _tokenController,
                      decoration: const InputDecoration(labelText: 'Token'),
                    ),
                    const SizedBox(height: 12),
                    FilledButton(
                      onPressed: _connect,
                      child: const Text('连接电脑'),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 16),
              _Panel(
                child: Column(
                  children: <Widget>[
                    TextField(
                      controller: _inputController,
                      focusNode: _inputFocusNode,
                      minLines: 11,
                      maxLines: 18,
                      keyboardType: TextInputType.multiline,
                      textInputAction: TextInputAction.newline,
                      decoration: const InputDecoration(
                        hintText: '开始输入',
                      ),
                      style: const TextStyle(
                        color: Color(0xFF172016),
                        fontSize: 24,
                        height: 1.42,
                        fontWeight: FontWeight.w500,
                      ),
                    ),
                    const SizedBox(height: 10),
                    OutlinedButton(
                      onPressed: _clearLocalInput,
                      child: const Text('清空'),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _Header extends StatelessWidget {
  const _Header({
    required this.statusText,
    required this.statusColor,
  });

  final String statusText;
  final Color statusColor;

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        const Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Text(
                'LIVE INPUT',
                style: TextStyle(
                  color: Color(0xFFD9FF70),
                  fontSize: 12,
                  fontWeight: FontWeight.w900,
                  letterSpacing: 1.8,
                ),
              ),
              SizedBox(height: 6),
              Text(
                'Flow Voice',
                style: TextStyle(
                  color: Color(0xFFF9F4E5),
                  fontSize: 48,
                  height: 0.9,
                  fontWeight: FontWeight.w900,
                  letterSpacing: -3.5,
                ),
              ),
            ],
          ),
        ),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          decoration: BoxDecoration(
            color: const Color(0xFFFFF8E8),
            borderRadius: BorderRadius.circular(999),
          ),
          child: Text(
            statusText,
            style: TextStyle(
              color: statusColor,
              fontWeight: FontWeight.w900,
              fontSize: 13,
            ),
          ),
        ),
      ],
    );
  }
}

class _Panel extends StatelessWidget {
  const _Panel({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFFF9F4E5).withValues(alpha: 0.94),
        borderRadius: BorderRadius.circular(28),
        border: Border.all(color: const Color(0x33FFFFFF)),
        boxShadow: const <BoxShadow>[
          BoxShadow(
            color: Color(0x3D000000),
            blurRadius: 42,
            offset: Offset(0, 18),
          ),
        ],
      ),
      child: child,
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

    for (final barcode in capture.barcodes) {
      final value = barcode.rawValue;
      if (value == null || value.trim().isEmpty) {
        continue;
      }
      _handled = true;
      Navigator.of(context).pop(value.trim());
      return;
    }
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
              width: 246,
              height: 246,
              decoration: BoxDecoration(
                border: Border.all(color: const Color(0xFFD9FF70), width: 3),
                borderRadius: BorderRadius.circular(24),
              ),
            ),
          ),
          const Positioned(
            left: 24,
            right: 24,
            bottom: 42,
            child: Text(
              '扫描电脑端二维码',
              textAlign: TextAlign.center,
              style: TextStyle(
                color: Colors.white,
                fontSize: 16,
                fontWeight: FontWeight.w800,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
