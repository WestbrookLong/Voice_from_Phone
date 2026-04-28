import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  SystemChrome.setEnabledSystemUIMode(SystemUiMode.immersiveSticky);
  runApp(const WhiteboardBridgeApp());
}

class WhiteboardBridgeApp extends StatelessWidget {
  const WhiteboardBridgeApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'Whiteboard Bridge',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.black),
        useMaterial3: true,
        scaffoldBackgroundColor: Colors.white,
      ),
      home: const WhiteboardPage(),
    );
  }
}

enum ToolMode { pen, eraser }

enum ConnectionStateLabel { offline, connecting, online, error }

class Stroke {
  Stroke({required this.tool, required this.points});

  final ToolMode tool;
  final List<Offset> points;
}

class MonitorInfo {
  const MonitorInfo({required this.width, required this.height});

  final double width;
  final double height;

  double get aspectRatio => width <= 0 || height <= 0 ? 16 / 10 : width / height;

  factory MonitorInfo.fromJson(Map<String, dynamic> json) {
    return MonitorInfo(
      width: (json['width'] as num?)?.toDouble() ?? 16,
      height: (json['height'] as num?)?.toDouble() ?? 10,
    );
  }
}

class WhiteboardPage extends StatefulWidget {
  const WhiteboardPage({super.key});

  @override
  State<WhiteboardPage> createState() => _WhiteboardPageState();
}

class _WhiteboardPageState extends State<WhiteboardPage> with WidgetsBindingObserver {
  final List<Stroke> _strokes = [];
  final TextEditingController _urlController = TextEditingController();

  WebSocket? _socket;
  StreamSubscription<dynamic>? _socketSubscription;
  Timer? _moveFlushTimer;
  final List<Map<String, dynamic>> _moveQueue = [];
  MonitorInfo _monitor = const MonitorInfo(width: 16, height: 10);
  ToolMode _tool = ToolMode.pen;
  ConnectionStateLabel _connectionState = ConnectionStateLabel.offline;
  String _statusText = 'Offline';
  int? _activePointer;
  Rect _boardRect = Rect.zero;
  Stroke? _activeStroke;
  Offset? _activeRatio;
  int _sequence = 0;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    WidgetsBinding.instance.addPostFrameCallback((_) => _showConnectionDialog());
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _forceEndActiveStroke();
    _moveFlushTimer?.cancel();
    _socketSubscription?.cancel();
    _socket?.close();
    _urlController.dispose();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.inactive || state == AppLifecycleState.paused || state == AppLifecycleState.detached) {
      _forceEndActiveStroke();
    }
  }

  Future<void> _showConnectionDialog() async {
    if (!mounted) {
      return;
    }
    await showDialog<void>(
      context: context,
      barrierDismissible: _connectionState == ConnectionStateLabel.online,
      builder: (context) {
        return AlertDialog(
          title: const Text('Connect to PC'),
          content: TextField(
            controller: _urlController,
            autofocus: true,
            keyboardType: TextInputType.url,
            autocorrect: false,
            textInputAction: TextInputAction.done,
            decoration: const InputDecoration(
              labelText: 'Whiteboard URL',
              hintText: 'http://PC-IP:8791/?token=...',
            ),
            onSubmitted: (_) {
              Navigator.of(context).pop();
              _connect();
            },
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(context).pop(),
              child: const Text('Close'),
            ),
            FilledButton(
              onPressed: () {
                Navigator.of(context).pop();
                _connect();
              },
              child: const Text('Connect'),
            ),
          ],
        );
      },
    );
  }

  Future<void> _connect() async {
    final wsUri = _toWebSocketUri(_urlController.text.trim());
    if (wsUri == null) {
      setState(() {
        _connectionState = ConnectionStateLabel.error;
        _statusText = 'Bad URL';
      });
      return;
    }

    await _socketSubscription?.cancel();
    await _socket?.close();

    setState(() {
      _connectionState = ConnectionStateLabel.connecting;
      _statusText = 'Connecting';
    });

    try {
      final socket = await WebSocket.connect(wsUri.toString());
      socket.pingInterval = const Duration(seconds: 15);
      _socket = socket;
      _socketSubscription = socket.listen(
        _handleSocketMessage,
        onDone: () {
          if (!mounted) {
            return;
          }
          setState(() {
            _connectionState = ConnectionStateLabel.offline;
            _statusText = 'Offline';
          });
        },
        onError: (_) {
          if (!mounted) {
            return;
          }
          setState(() {
            _connectionState = ConnectionStateLabel.error;
            _statusText = 'Socket error';
          });
        },
      );
      if (!mounted) {
        return;
      }
      setState(() {
        _connectionState = ConnectionStateLabel.online;
        _statusText = 'Online';
      });
    } catch (error) {
      if (!mounted) {
        return;
      }
      setState(() {
        _connectionState = ConnectionStateLabel.error;
        _statusText = 'Connect failed';
      });
    }
  }

  Uri? _toWebSocketUri(String value) {
    if (value.isEmpty) {
      return null;
    }
    Uri? uri = Uri.tryParse(value);
    if (uri == null || !uri.hasScheme || uri.host.isEmpty) {
      uri = Uri.tryParse('http://$value');
    }
    if (uri == null || uri.host.isEmpty) {
      return null;
    }

    final scheme = switch (uri.scheme) {
      'https' => 'wss',
      'wss' => 'wss',
      _ => 'ws',
    };
    final token = uri.queryParameters['token'];
    final query = token == null || token.isEmpty ? uri.queryParameters : {'token': token};
    return uri.replace(scheme: scheme, path: '/pointer', queryParameters: query, fragment: '');
  }

  void _handleSocketMessage(dynamic data) {
    if (data is! String) {
      return;
    }
    final message = jsonDecode(data);
    if (message is! Map<String, dynamic>) {
      return;
    }
    if (message['type'] == 'ready' && message['monitor'] is Map<String, dynamic>) {
      setState(() {
        _monitor = MonitorInfo.fromJson(message['monitor'] as Map<String, dynamic>);
      });
    } else if (message['type'] == 'error') {
      setState(() {
        _connectionState = ConnectionStateLabel.error;
        _statusText = 'PC error';
      });
    }
  }

  void _sendRaw(Map<String, dynamic> message) {
    final socket = _socket;
    if (socket == null || socket.readyState != WebSocket.open || _boardRect.isEmpty) {
      return;
    }
    socket.add(jsonEncode(message));
  }

  Map<String, dynamic> _pointerMessage(String action, Offset ratio, {double pressure = 0}) {
    return {
      'type': 'pointer',
      'action': action,
      'x': ratio.dx,
      'y': ratio.dy,
      'pressure': pressure,
      'pointerType': 'pen',
      'seq': ++_sequence,
    };
  }

  void _sendPointer(String action, Offset localPosition, {double pressure = 0}) {
    final ratio = _ratioForLocalPosition(localPosition);
    _activeRatio = ratio;
    _sendRaw(_pointerMessage(action, ratio, pressure: pressure));
  }

  Offset _ratioForLocalPosition(Offset localPosition) {
    final x = ((localPosition.dx - _boardRect.left) / math.max(1, _boardRect.width)).clamp(0.0, 1.0).toDouble();
    final y = ((localPosition.dy - _boardRect.top) / math.max(1, _boardRect.height)).clamp(0.0, 1.0).toDouble();
    return Offset(x, y);
  }

  Offset _canvasPoint(Offset localPosition) {
    return Offset(
      localPosition.dx.clamp(_boardRect.left, _boardRect.right).toDouble(),
      localPosition.dy.clamp(_boardRect.top, _boardRect.bottom).toDouble(),
    );
  }

  void _flushMove() {
    _moveFlushTimer?.cancel();
    _moveFlushTimer = null;
    if (_moveQueue.isEmpty) {
      return;
    }
    final events = List<Map<String, dynamic>>.of(_moveQueue);
    _moveQueue.clear();
    _sendRaw({'type': 'pointer_batch', 'events': events});
  }

  void _queueMove(PointerMoveEvent event) {
    final socket = _socket;
    if (socket == null || socket.readyState != WebSocket.open) {
      return;
    }
    final ratio = _ratioForLocalPosition(event.localPosition);
    _activeRatio = ratio;
    _moveQueue.add(_pointerMessage('move', ratio, pressure: event.pressure));
    if (_moveQueue.length >= 16) {
      _flushMove();
      return;
    }
    _moveFlushTimer ??= Timer(const Duration(milliseconds: 8), _flushMove);
  }

  void _handlePointerDown(PointerDownEvent event) {
    if (!_boardRect.contains(event.localPosition)) {
      return;
    }
    if (_activePointer != null) {
      _forceEndActiveStroke();
    }
    _activePointer = event.pointer;
    _activeStroke = Stroke(tool: _tool, points: [_canvasPoint(event.localPosition)]);
    _strokes.add(_activeStroke!);
    _flushMove();
    _sendPointer('down', event.localPosition, pressure: event.pressure);
    setState(() {});
  }

  void _handlePointerMove(PointerMoveEvent event) {
    if (event.pointer != _activePointer || _activeStroke == null) {
      return;
    }
    final point = _canvasPoint(event.localPosition);
    final points = _activeStroke!.points;
    if (points.isEmpty || (points.last - point).distance > 0.25) {
      points.add(point);
      setState(() {});
    }
    _queueMove(event);
  }

  void _handlePointerEnd(PointerEvent event) {
    if (event.pointer != _activePointer) {
      return;
    }
    _flushMove();
    _sendPointer('up', event.localPosition, pressure: event.pressure);
    _activePointer = null;
    _activeStroke = null;
    _activeRatio = null;
  }

  void _forceEndActiveStroke() {
    if (_activePointer == null) {
      return;
    }
    _flushMove();
    final ratio = _activeRatio;
    if (ratio != null) {
      _sendRaw(_pointerMessage('up', ratio));
    }
    _activePointer = null;
    _activeStroke = null;
    _activeRatio = null;
  }

  void _clear() {
    setState(() {
      _strokes.clear();
      _activeStroke = null;
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        top: false,
        bottom: false,
        child: LayoutBuilder(
          builder: (context, constraints) {
            final size = Size(constraints.maxWidth, constraints.maxHeight);
            _boardRect = _fitRect(size, _monitor.aspectRatio);
            return Stack(
              children: [
                Positioned.fill(
                  child: Listener(
                    behavior: HitTestBehavior.opaque,
                    onPointerDown: _handlePointerDown,
                    onPointerMove: _handlePointerMove,
                    onPointerUp: _handlePointerEnd,
                    onPointerCancel: _handlePointerEnd,
                    child: CustomPaint(
                      painter: WhiteboardPainter(
                        boardRect: _boardRect,
                        strokes: _strokes,
                      ),
                    ),
                  ),
                ),
                Positioned(
                  left: 14,
                  top: 14 + MediaQuery.paddingOf(context).top,
                  child: _Toolbar(
                    tool: _tool,
                    state: _connectionState,
                    statusText: _statusText,
                    onToolChanged: (tool) => setState(() => _tool = tool),
                    onClear: _clear,
                    onConnect: _showConnectionDialog,
                  ),
                ),
              ],
            );
          },
        ),
      ),
    );
  }

  Rect _fitRect(Size size, double aspectRatio) {
    var width = size.width;
    var height = width / aspectRatio;
    if (height > size.height) {
      height = size.height;
      width = height * aspectRatio;
    }
    return Rect.fromLTWH((size.width - width) / 2, (size.height - height) / 2, width, height);
  }
}

class _Toolbar extends StatelessWidget {
  const _Toolbar({
    required this.tool,
    required this.state,
    required this.statusText,
    required this.onToolChanged,
    required this.onClear,
    required this.onConnect,
  });

  final ToolMode tool;
  final ConnectionStateLabel state;
  final String statusText;
  final ValueChanged<ToolMode> onToolChanged;
  final VoidCallback onClear;
  final VoidCallback onConnect;

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.94),
        border: Border.all(color: Colors.black.withValues(alpha: 0.12)),
        borderRadius: BorderRadius.circular(8),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.08),
            blurRadius: 20,
            offset: const Offset(0, 8),
          ),
        ],
      ),
      child: Padding(
        padding: const EdgeInsets.all(6),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            _ToolButton(
              label: 'Pen',
              selected: tool == ToolMode.pen,
              onPressed: () => onToolChanged(ToolMode.pen),
            ),
            const SizedBox(width: 8),
            _ToolButton(
              label: 'Eraser',
              selected: tool == ToolMode.eraser,
              onPressed: () => onToolChanged(ToolMode.eraser),
            ),
            const SizedBox(width: 8),
            TextButton(
              onPressed: onClear,
              child: const Text('Clear'),
            ),
            const SizedBox(width: 6),
            TextButton(
              onPressed: onConnect,
              child: const Text('Connect'),
            ),
            const SizedBox(width: 8),
            _StatusPill(state: state, text: statusText),
          ],
        ),
      ),
    );
  }
}

class _ToolButton extends StatelessWidget {
  const _ToolButton({required this.label, required this.selected, required this.onPressed});

  final String label;
  final bool selected;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 42,
      child: selected
          ? FilledButton(onPressed: onPressed, child: Text(label))
          : OutlinedButton(onPressed: onPressed, child: Text(label)),
    );
  }
}

class _StatusPill extends StatelessWidget {
  const _StatusPill({required this.state, required this.text});

  final ConnectionStateLabel state;
  final String text;

  @override
  Widget build(BuildContext context) {
    final color = switch (state) {
      ConnectionStateLabel.online => const Color(0xff188038),
      ConnectionStateLabel.connecting => const Color(0xffb7791f),
      ConnectionStateLabel.error => const Color(0xffc5221f),
      ConnectionStateLabel.offline => const Color(0xff777777),
    };
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 8,
          height: 8,
          decoration: BoxDecoration(color: color, shape: BoxShape.circle),
        ),
        const SizedBox(width: 7),
        Text(
          text,
          style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: Color(0xff555555)),
        ),
      ],
    );
  }
}

class WhiteboardPainter extends CustomPainter {
  WhiteboardPainter({required this.boardRect, required this.strokes});

  final Rect boardRect;
  final List<Stroke> strokes;

  @override
  void paint(Canvas canvas, Size size) {
    final outsidePaint = Paint()..color = const Color(0xfff5f5f5);
    canvas.drawRect(Offset.zero & size, outsidePaint);

    final boardPaint = Paint()..color = Colors.white;
    canvas.drawRect(boardRect, boardPaint);

    canvas.save();
    canvas.clipRect(boardRect);
    for (final stroke in strokes) {
      _paintStroke(canvas, stroke);
    }
    canvas.restore();

    final borderPaint = Paint()
      ..color = Colors.black.withValues(alpha: 0.08)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1;
    canvas.drawRect(boardRect, borderPaint);
  }

  void _paintStroke(Canvas canvas, Stroke stroke) {
    if (stroke.points.isEmpty) {
      return;
    }
    final paint = Paint()
      ..color = stroke.tool == ToolMode.eraser ? Colors.white : Colors.black
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round
      ..style = PaintingStyle.stroke
      ..strokeWidth = stroke.tool == ToolMode.eraser ? 24 : 5;

    if (stroke.points.length == 1) {
      canvas.drawCircle(stroke.points.first, paint.strokeWidth / 2, Paint()..color = paint.color);
      return;
    }

    final path = Path()..moveTo(stroke.points.first.dx, stroke.points.first.dy);
    for (var i = 1; i < stroke.points.length; i += 1) {
      path.lineTo(stroke.points[i].dx, stroke.points[i].dy);
    }
    canvas.drawPath(path, paint);
  }

  @override
  bool shouldRepaint(covariant WhiteboardPainter oldDelegate) {
    return true;
  }
}
