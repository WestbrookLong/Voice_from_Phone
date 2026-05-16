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
    return MaterialApp(
      title: 'Flow Voice',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        brightness: Brightness.dark,
        scaffoldBackgroundColor: const Color(0xFF050807),
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF28F58D),
          brightness: Brightness.dark,
        ),
        fontFamily: 'sans',
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
  String _lastSnapshotKey = '';
  int _seq = 0;
  int _connectionGeneration = 0;
  bool _isConnecting = false;
  bool _filterPunctuation = false;
  bool _convertSpokenPunctuation = false;
  bool _enableVoiceCommands = false;
  Timer? _reconnectTimer;
  final List<Map<String, Object?>> _queue = <Map<String, Object?>>[];

  @override
  void initState() {
    super.initState();
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

  Future<void> _scanQrCode() async {
    final result = await Navigator.of(context).push<String>(
      MaterialPageRoute<String>(builder: (_) => const QrScanPage()),
    );
    if (result == null || result.trim().isEmpty) {
      return;
    }
    _urlController.text = result.trim();
    _parseAndFillUrl(result);
    await _connect();
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

  Future<void> _connect({bool fromRetry = false}) async {
    if (_isConnecting) {
      return;
    }
    final uri = _wsUri;
    if (uri == null) {
      _setStatus(BridgeStatus.error, '请扫码');
      return;
    }

    _reconnectTimer?.cancel();
    _isConnecting = true;
    _setStatus(BridgeStatus.connecting, '连接中');

    try {
      final generation = ++_connectionGeneration;
      final oldSocket = _socket;
      _socket = null;
      await oldSocket?.close();
      final socket = await WebSocket.connect(uri.toString());
      if (generation != _connectionGeneration) {
        await socket.close();
        return;
      }
      _socket = socket;
      _setStatus(BridgeStatus.connected, '在线');
      _flushQueue();
      _syncInput(force: true);
      _inputFocusNode.requestFocus();

      socket.listen(
        _handleSocketMessage,
        onDone: () => _handleSocketClosed(socket, retry: true),
        onError: (_) => _handleSocketClosed(socket, retry: true),
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

  void _handleSocketClosed(WebSocket socket, {required bool retry}) {
    if (!mounted) {
      return;
    }
    if (!identical(socket, _socket)) {
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

  Map<String, Object?> _settingsPayload() {
    return <String, Object?>{
      'filterPunctuation': _filterPunctuation,
      'convertSpokenPunctuation': _convertSpokenPunctuation,
      'enableVoiceCommands': _enableVoiceCommands,
    };
  }

  void _syncInput({bool force = false}) {
    final message = <String, Object?>{
      'type': 'sync_state',
      'token': _tokenController.text.trim(),
      'seq': ++_seq,
      'text': _inputController.text,
      'settings': _settingsPayload(),
    };
    final snapshotKey = jsonEncode(<String, Object?>{
      'text': message['text'],
      'settings': message['settings'],
    });
    if (!force && snapshotKey == _lastSnapshotKey) {
      return;
    }
    _lastSnapshotKey = snapshotKey;
    _send(message);
  }

  void _sendResetSession() {
    _lastSnapshotKey = '';
    _send(<String, Object?>{
      'type': 'reset_session',
      'token': _tokenController.text.trim(),
      'seq': ++_seq,
    });
  }

  void _send(Map<String, Object?> message) {
    final socket = _socket;
    if (socket == null || socket.readyState != WebSocket.open) {
      _queue.add(message);
      if (_status != BridgeStatus.connected &&
          _status != BridgeStatus.connecting) {
        _setStatus(BridgeStatus.error, '离线 ${_queue.length}');
      }
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
    _inputController.addListener(_syncInput);
    _sendResetSession();
    _inputFocusNode.requestFocus();
  }

  void _openSettings() {
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      showDragHandle: false,
      backgroundColor: Colors.transparent,
      builder: (context) {
        return StatefulBuilder(
          builder: (context, setSheetState) {
            void update(VoidCallback fn) {
              setState(fn);
              setSheetState(() {});
              _syncInput(force: true);
            }

            return SafeArea(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: _SettingsSheet(
                  filterPunctuation: _filterPunctuation,
                  convertSpokenPunctuation: _convertSpokenPunctuation,
                  enableVoiceCommands: _enableVoiceCommands,
                  onFilterChanged: (value) => update(() {
                    _filterPunctuation = value;
                    if (!value) {
                      _convertSpokenPunctuation = false;
                    }
                  }),
                  onConvertChanged: _filterPunctuation
                      ? (value) =>
                          update(() => _convertSpokenPunctuation = value)
                      : null,
                  onCommandChanged: (value) =>
                      update(() => _enableVoiceCommands = value),
                  onClose: () => Navigator.of(context).pop(),
                ),
              ),
            );
          },
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: _VoiceBackground(
          child: Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(16),
              child: _VoiceShell(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: <Widget>[
                    _Header(
                      status: _status,
                      statusText: _statusText,
                      settingsActive: _filterPunctuation ||
                          _convertSpokenPunctuation ||
                          _enableVoiceCommands,
                      onSettings: _openSettings,
                      onScan: _scanQrCode,
                    ),
                    const SizedBox(height: 16),
                    _VoiceInput(
                      controller: _inputController,
                      focusNode: _inputFocusNode,
                    ),
                    const SizedBox(height: 10),
                    Row(
                      children: <Widget>[
                        Expanded(
                          child: _VoiceButton(
                            label: '清空',
                            onPressed: _clearLocalInput,
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _VoiceBackground extends StatelessWidget {
  const _VoiceBackground({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: const BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: <Color>[
            Color(0xFF050807),
            Color(0xFF0B1D14),
            Color(0xFF06100B),
          ],
        ),
      ),
      child: Stack(
        fit: StackFit.expand,
        children: <Widget>[
          const Positioned(
            left: -110,
            top: -120,
            child: _GlowBlob(
              size: 330,
              color: Color(0x3328F58D),
            ),
          ),
          const Positioned(
            right: -120,
            top: 30,
            child: _GlowBlob(
              size: 300,
              color: Color(0x261FA463),
            ),
          ),
          child,
        ],
      ),
    );
  }
}

class _GlowBlob extends StatelessWidget {
  const _GlowBlob({
    required this.size,
    required this.color,
  });

  final double size;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        gradient: RadialGradient(
          colors: <Color>[color, Colors.transparent],
        ),
      ),
    );
  }
}

class _VoiceShell extends StatelessWidget {
  const _VoiceShell({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    return ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 760),
      child: Container(
        padding: const EdgeInsets.all(18),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(34),
          border: Border.all(color: const Color(0x3828F58D)),
          gradient: const LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: <Color>[
              Color(0xF508100D),
              Color(0xE00B1D14),
            ],
          ),
          boxShadow: const <BoxShadow>[
            BoxShadow(
              color: Color(0x80000000),
              blurRadius: 90,
              offset: Offset(0, 30),
            ),
          ],
        ),
        child: child,
      ),
    );
  }
}

class _Header extends StatelessWidget {
  const _Header({
    required this.status,
    required this.statusText,
    required this.settingsActive,
    required this.onSettings,
    required this.onScan,
  });

  final BridgeStatus status;
  final String statusText;
  final bool settingsActive;
  final VoidCallback onSettings;
  final VoidCallback onScan;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final compact = constraints.maxWidth < 340;
        final ultraCompact = constraints.maxWidth < 300;
        return Row(
          children: <Widget>[
            Expanded(
              child: Row(
                children: <Widget>[
                  if (!ultraCompact) const Flexible(child: _Eyebrow()),
                  if (!compact) ...const <Widget>[
                    SizedBox(width: 10),
                    Flexible(
                      child: Text(
                        'Flow Voice',
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(
                          color: Color(0xFFF0FFF5),
                          fontSize: 18,
                          fontWeight: FontWeight.w600,
                          letterSpacing: -0.36,
                        ),
                      ),
                    ),
                  ],
                ],
              ),
            ),
            _StatusPill(
              status: status,
              text: compact ? '' : statusText,
            ),
            const SizedBox(width: 8),
            _RoundIconButton(
              icon: Icons.settings,
              active: settingsActive,
              onPressed: onSettings,
            ),
            const SizedBox(width: 8),
            _RoundIconButton(
              icon: Icons.qr_code_scanner,
              active: false,
              onPressed: onScan,
            ),
          ],
        );
      },
    );
  }
}

class _Eyebrow extends StatelessWidget {
  const _Eyebrow();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: const Color(0x1F28F58D),
        border: Border.all(color: const Color(0x3D28F58D)),
        borderRadius: BorderRadius.circular(999),
      ),
      child: const Text(
        'LIVE INPUT',
        maxLines: 1,
        overflow: TextOverflow.fade,
        softWrap: false,
        style: TextStyle(
          color: Color(0xFF7BFFB5),
          fontSize: 11,
          fontWeight: FontWeight.w900,
          height: 1,
          letterSpacing: 0.9,
        ),
      ),
    );
  }
}

class _StatusPill extends StatelessWidget {
  const _StatusPill({
    required this.status,
    required this.text,
  });

  final BridgeStatus status;
  final String text;

  @override
  Widget build(BuildContext context) {
    final isConnected = status == BridgeStatus.connected;
    final isError =
        status == BridgeStatus.error || status == BridgeStatus.disconnected;
    final color = isConnected
        ? const Color(0xFF9CFCC4)
        : isError
            ? const Color(0xFFC4533C)
            : const Color(0xFF5B7062);
    final dot = isConnected
        ? const Color(0xFF28F58D)
        : isError
            ? const Color(0xFFC4533C)
            : const Color(0xFF5B7062);
    return Container(
      constraints: const BoxConstraints(minWidth: 42, minHeight: 42),
      padding: EdgeInsets.symmetric(
        horizontal: text.isEmpty ? 0 : 12,
        vertical: 9,
      ),
      decoration: BoxDecoration(
        color: isConnected ? const Color(0x2628F58D) : const Color(0xC708100D),
        border: Border.all(color: const Color(0x1F28F58D)),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.center,
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          Container(
            width: 8,
            height: 8,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: dot,
              boxShadow: <BoxShadow>[
                BoxShadow(
                  color: dot.withValues(alpha: 0.6),
                  blurRadius: 10,
                ),
              ],
            ),
          ),
          if (text.isNotEmpty) ...<Widget>[
            const SizedBox(width: 6),
            Text(
              text,
              maxLines: 1,
              overflow: TextOverflow.fade,
              softWrap: false,
              style: TextStyle(
                color: color,
                fontSize: 12,
                fontWeight: FontWeight.w800,
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _RoundIconButton extends StatelessWidget {
  const _RoundIconButton({
    required this.icon,
    required this.active,
    required this.onPressed,
  });

  final IconData icon;
  final bool active;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: active ? const Color(0xFF28F58D) : const Color(0xC208100D),
      shape: const CircleBorder(
        side: BorderSide(color: Color(0x3328F58D)),
      ),
      child: InkWell(
        customBorder: const CircleBorder(),
        onTap: onPressed,
        child: SizedBox(
          width: 42,
          height: 42,
          child: Icon(
            icon,
            size: 21,
            color: active ? const Color(0xFF041008) : const Color(0xFFDDE7DF),
          ),
        ),
      ),
    );
  }
}

class _VoiceInput extends StatelessWidget {
  const _VoiceInput({
    required this.controller,
    required this.focusNode,
  });

  final TextEditingController controller;
  final FocusNode focusNode;

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 122,
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(30),
        border: Border.all(color: const Color(0x2428F58D)),
        gradient: const LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: <Color>[
            Color(0xDB08100D),
            Color(0xDE0B1D14),
          ],
        ),
        boxShadow: const <BoxShadow>[
          BoxShadow(
            color: Color(0x66000000),
            blurRadius: 48,
            offset: Offset(0, 18),
          ),
        ],
      ),
      child: TextField(
        controller: controller,
        focusNode: focusNode,
        minLines: 3,
        maxLines: 3,
        keyboardType: TextInputType.multiline,
        textInputAction: TextInputAction.newline,
        autocorrect: true,
        enableSuggestions: true,
        style: const TextStyle(
          color: Color(0xFFDDE7DF),
          fontSize: 22,
          height: 1.36,
          fontWeight: FontWeight.w500,
        ),
        decoration: const InputDecoration(
          hintText: '开始输入',
          hintStyle: TextStyle(color: Color(0x57DDE7DF)),
          border: InputBorder.none,
          contentPadding: EdgeInsets.symmetric(horizontal: 18, vertical: 14),
        ),
      ),
    );
  }
}

class _VoiceButton extends StatelessWidget {
  const _VoiceButton({
    required this.label,
    required this.onPressed,
  });

  final String label;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 54,
      child: OutlinedButton(
        onPressed: onPressed,
        style: OutlinedButton.styleFrom(
          foregroundColor: const Color(0xFFDDE7DF),
          side: const BorderSide(color: Color(0x1F28F58D)),
          backgroundColor: const Color(0xC208100D),
          textStyle: const TextStyle(
            fontSize: 16,
            fontWeight: FontWeight.w900,
          ),
          shape:
              RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
        ),
        child: Text(label),
      ),
    );
  }
}

class _SettingsSheet extends StatelessWidget {
  const _SettingsSheet({
    required this.filterPunctuation,
    required this.convertSpokenPunctuation,
    required this.enableVoiceCommands,
    required this.onFilterChanged,
    required this.onConvertChanged,
    required this.onCommandChanged,
    required this.onClose,
  });

  final bool filterPunctuation;
  final bool convertSpokenPunctuation;
  final bool enableVoiceCommands;
  final ValueChanged<bool> onFilterChanged;
  final ValueChanged<bool>? onConvertChanged;
  final ValueChanged<bool> onCommandChanged;
  final VoidCallback onClose;

  @override
  Widget build(BuildContext context) {
    return ConstrainedBox(
      constraints: BoxConstraints(
        maxHeight: MediaQuery.sizeOf(context).height * 0.82,
      ),
      child: Container(
        padding: const EdgeInsets.all(18),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(26),
          border: Border.all(color: const Color(0x3828F58D)),
          gradient: const LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: <Color>[
              Color(0xFF08100D),
              Color(0xFF0B1D14),
            ],
          ),
          boxShadow: const <BoxShadow>[
            BoxShadow(
              color: Color(0x8C000000),
              blurRadius: 90,
              offset: Offset(0, 30),
            ),
          ],
        ),
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: <Widget>[
              const Text(
                '设置',
                style: TextStyle(
                  color: Color(0xFFF0FFF5),
                  fontSize: 22,
                  fontWeight: FontWeight.w800,
                ),
              ),
              const SizedBox(height: 12),
              _SettingSwitch(
                title: '标点过滤',
                description: '开启后，电脑端只接收过滤真实标点后的文本；手机输入框内容保持原样。',
                value: filterPunctuation,
                onChanged: onFilterChanged,
              ),
              const SizedBox(height: 12),
              Padding(
                padding: const EdgeInsets.only(left: 12),
                child: _SettingSwitch(
                  title: '口述标点转换',
                  description: '把“逗号、句号、问号”等文字命令转换为真实标点，并按上下文选择样式。',
                  value: convertSpokenPunctuation,
                  onChanged: onConvertChanged,
                ),
              ),
              const SizedBox(height: 12),
              _SettingSwitch(
                title: '英文语音命令',
                description:
                    '支持 enter、back、backspace / back space、delete all。命令大小写不敏感。',
                value: enableVoiceCommands,
                onChanged: onCommandChanged,
              ),
              const SizedBox(height: 12),
              _VoiceButton(label: '完成', onPressed: onClose),
            ],
          ),
        ),
      ),
    );
  }
}

class _SettingSwitch extends StatelessWidget {
  const _SettingSwitch({
    required this.title,
    required this.description,
    required this.value,
    required this.onChanged,
  });

  final String title;
  final String description;
  final bool value;
  final ValueChanged<bool>? onChanged;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xC706100B),
        border: Border.all(color: const Color(0x1F28F58D)),
        borderRadius: BorderRadius.circular(20),
      ),
      child: Row(
        children: <Widget>[
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Text(
                  title,
                  style: TextStyle(
                    color: onChanged == null
                        ? const Color(0x805B7062)
                        : const Color(0xFFDDE7DF),
                    fontSize: 16,
                    fontWeight: FontWeight.w800,
                  ),
                ),
                const SizedBox(height: 6),
                Text(
                  description,
                  style: TextStyle(
                    color: onChanged == null
                        ? const Color(0x705B7062)
                        : const Color(0xFF5B7062),
                    fontSize: 12,
                    height: 1.45,
                    fontWeight: FontWeight.w500,
                  ),
                ),
              ],
            ),
          ),
          Switch(
            value: value,
            onChanged: onChanged,
            activeThumbColor: const Color(0xFF28F58D),
            inactiveThumbColor: const Color(0xFF8EA99A),
            inactiveTrackColor: const Color(0x385B7062),
          ),
        ],
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
                border: Border.all(color: const Color(0xFF28F58D), width: 3),
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
