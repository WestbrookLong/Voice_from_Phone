import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:flutter/foundation.dart';
import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  SystemChrome.setEnabledSystemUIMode(SystemUiMode.immersiveSticky);
  SystemChrome.setPreferredOrientations([
    DeviceOrientation.landscapeLeft,
    DeviceOrientation.landscapeRight,
    DeviceOrientation.portraitUp,
    DeviceOrientation.portraitDown,
  ]);
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
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xffff8a00),
          brightness: Brightness.light,
        ),
        useMaterial3: true,
        scaffoldBackgroundColor: Colors.white,
      ),
      home: const WhiteboardPage(),
    );
  }
}

enum ToolMode { pen, line, eraser }

enum FloatingButtonId { pen, line, eraser, undo }

enum BridgeConnectionState { offline, connecting, online, error }

enum AreaHandle { move, n, e, s, w, nw, ne, sw, se }

class MonitorInfo {
  const MonitorInfo({required this.width, required this.height});

  final double width;
  final double height;

  double get aspectRatio =>
      width <= 0 || height <= 0 ? 16 / 10 : width / height;

  factory MonitorInfo.fromJson(Map<String, dynamic> json) {
    return MonitorInfo(
      width: (json['width'] as num?)?.toDouble() ?? 16,
      height: (json['height'] as num?)?.toDouble() ?? 10,
    );
  }
}

class Stroke {
  Stroke({
    required this.tool,
    required this.points,
    required this.color,
    required this.size,
  });

  final ToolMode tool;
  final List<Offset> points;
  final Color color;
  final double size;

  Stroke copyWith({List<Offset>? points}) {
    return Stroke(
      tool: tool,
      points: points ?? this.points,
      color: color,
      size: size,
    );
  }
}

class PointerSample {
  PointerSample({
    required this.action,
    required this.ratio,
    required this.pressure,
    required this.pointerKind,
  });

  final String action;
  final Offset ratio;
  final double pressure;
  final String pointerKind;
}

class ViewportState {
  const ViewportState({this.zoom = 1, this.center = const Offset(0.5, 0.5)});

  final double zoom;
  final Offset center;

  ViewportState copyWith({double? zoom, Offset? center}) {
    return ViewportState(
      zoom: zoom ?? this.zoom,
      center: center ?? this.center,
    );
  }
}

class AreaEditSession {
  AreaEditSession({
    required this.handle,
    required this.startLocal,
    required this.startArea,
  });

  final AreaHandle handle;
  final Offset startLocal;
  final Rect startArea;
}

class BridgeClient {
  WebSocket? _pointerSocket;
  StreamSubscription<dynamic>? _pointerSubscription;
  WebSocket? _screenSocket;
  StreamSubscription<dynamic>? _screenSubscription;
  Uri? _baseUri;
  Uri? _pointerUri;
  Timer? _moveFlushTimer;
  final List<Map<String, dynamic>> _moveQueue = [];
  int _sequence = 0;
  bool _screenWanted = false;

  bool get isPointerOpen => _pointerSocket?.readyState == WebSocket.open;
  Uri? get baseUri => _baseUri;

  Future<void> connect({
    required String value,
    required void Function(MonitorInfo monitor) onMonitor,
    required void Function(BridgeConnectionState state, String label) onState,
  }) async {
    final pointerUri = toPointerUri(value);
    if (pointerUri == null) {
      onState(BridgeConnectionState.error, 'Bad URL');
      return;
    }
    await closePointer();
    _baseUri = pointerUri.replace(
      scheme: pointerUri.scheme == 'wss' ? 'https' : 'http',
      path: '/',
      queryParameters: pointerUri.queryParameters,
    );
    _pointerUri = pointerUri;
    onState(BridgeConnectionState.connecting, 'Connecting');
    try {
      final socket = await WebSocket.connect(pointerUri.toString());
      socket.pingInterval = const Duration(seconds: 15);
      _pointerSocket = socket;
      _pointerSubscription = socket.listen(
        (data) {
          if (data is! String) {
            return;
          }
          final decoded = jsonDecode(data);
          if (decoded is! Map<String, dynamic>) {
            return;
          }
          if (decoded['type'] == 'ready' &&
              decoded['monitor'] is Map<String, dynamic>) {
            onMonitor(
              MonitorInfo.fromJson(decoded['monitor'] as Map<String, dynamic>),
            );
            onState(BridgeConnectionState.online, 'Online');
          } else if (decoded['type'] == 'error') {
            onState(BridgeConnectionState.error, 'PC error');
          }
        },
        onDone: () => onState(BridgeConnectionState.offline, 'Offline'),
        onError: (_) => onState(BridgeConnectionState.error, 'Socket error'),
      );
    } catch (_) {
      onState(BridgeConnectionState.error, 'Connect failed');
    }
  }

  static Uri? toPointerUri(String value) {
    var text = value.trim();
    if (text.isEmpty) {
      return null;
    }
    if (!text.contains('://')) {
      text = 'http://$text';
    }
    final uri = Uri.tryParse(text);
    if (uri == null || uri.host.isEmpty) {
      return null;
    }
    final scheme = switch (uri.scheme) {
      'https' => 'wss',
      'wss' => 'wss',
      _ => 'ws',
    };
    final token = uri.queryParameters['token'];
    final query = token == null || token.isEmpty
        ? uri.queryParameters
        : {'token': token};
    return uri.replace(
      scheme: scheme,
      path: '/pointer',
      queryParameters: query,
      fragment: '',
    );
  }

  Uri? _httpRoute(String path, Map<String, String> extraQuery) {
    final base = _baseUri;
    if (base == null) {
      return null;
    }
    return base.replace(
      path: path,
      queryParameters: {...base.queryParameters, ...extraQuery},
    );
  }

  Uri? _wsRoute(String path, Map<String, String> extraQuery) {
    final pointer = _pointerUri;
    if (pointer == null) {
      return null;
    }
    return pointer.replace(
      path: path,
      queryParameters: {...pointer.queryParameters, ...extraQuery},
    );
  }

  Future<ui.Image?> fetchSnapshot({
    required void Function(MonitorInfo monitor) onMonitor,
  }) async {
    final uri = _httpRoute('/snapshot', {'quality': '72'});
    if (uri == null) {
      return null;
    }
    final client = HttpClient();
    try {
      final request = await client.getUrl(uri);
      final response = await request.close();
      if (response.statusCode != 200) {
        return null;
      }
      final width = double.tryParse(
        response.headers.value('x-monitor-width') ?? '',
      );
      final height = double.tryParse(
        response.headers.value('x-monitor-height') ?? '',
      );
      if (width != null && height != null) {
        onMonitor(MonitorInfo(width: width, height: height));
      }
      final bytes = await consolidateHttpClientResponseBytes(response);
      return decodeUiImage(bytes);
    } finally {
      client.close(force: true);
    }
  }

  Future<void> startScreenStream({
    required void Function(MonitorInfo monitor) onMonitor,
    required void Function(ui.Image frame) onFrame,
    required VoidCallback onClosed,
  }) async {
    final uri = _wsRoute('/screen', {'fps': '12', 'quality': '58'});
    if (uri == null) {
      return;
    }
    await stopScreenStream();
    _screenWanted = true;
    try {
      final socket = await WebSocket.connect(uri.toString());
      _screenSocket = socket;
      _screenSubscription = socket.listen(
        (data) async {
          if (data is String) {
            final decoded = jsonDecode(data);
            if (decoded is Map<String, dynamic> &&
                decoded['type'] == 'screen_meta' &&
                decoded['monitor'] is Map<String, dynamic>) {
              onMonitor(
                MonitorInfo.fromJson(
                  decoded['monitor'] as Map<String, dynamic>,
                ),
              );
            }
            return;
          }
          final bytes = data is Uint8List
              ? data
              : Uint8List.fromList(data as List<int>);
          final frame = await decodeUiImage(bytes);
          onFrame(frame);
        },
        onDone: () {
          if (_screenWanted) {
            onClosed();
          }
        },
        onError: (_) {
          if (_screenWanted) {
            onClosed();
          }
        },
      );
    } catch (_) {
      onClosed();
    }
  }

  Future<void> stopScreenStream() async {
    _screenWanted = false;
    await _screenSubscription?.cancel();
    await _screenSocket?.close();
    _screenSubscription = null;
    _screenSocket = null;
  }

  void sendPointer(PointerSample sample) {
    if (!isPointerOpen) {
      return;
    }
    if (sample.action == 'move') {
      _moveQueue.add(_message(sample));
      if (_moveQueue.length >= 16) {
        flushMoves();
      } else {
        _moveFlushTimer ??= Timer(const Duration(milliseconds: 8), flushMoves);
      }
      return;
    }
    flushMoves();
    _pointerSocket?.add(jsonEncode(_message(sample)));
  }

  void sendClick(Offset ratio, {String pointerKind = 'touch'}) {
    sendPointer(
      PointerSample(
        action: 'down',
        ratio: ratio,
        pressure: 0.5,
        pointerKind: pointerKind,
      ),
    );
    sendPointer(
      PointerSample(
        action: 'up',
        ratio: ratio,
        pressure: 0,
        pointerKind: pointerKind,
      ),
    );
  }

  void flushMoves() {
    _moveFlushTimer?.cancel();
    _moveFlushTimer = null;
    if (_moveQueue.isEmpty || !isPointerOpen) {
      _moveQueue.clear();
      return;
    }
    final events = List<Map<String, dynamic>>.of(_moveQueue);
    _moveQueue.clear();
    _pointerSocket?.add(
      jsonEncode({'type': 'pointer_batch', 'events': events}),
    );
  }

  Map<String, dynamic> _message(PointerSample sample) {
    return {
      'type': 'pointer',
      'action': sample.action,
      'x': sample.ratio.dx.clamp(0.0, 1.0),
      'y': sample.ratio.dy.clamp(0.0, 1.0),
      'pressure': sample.pressure.clamp(0.0, 1.0),
      'pointerType': sample.pointerKind,
      'seq': ++_sequence,
    };
  }

  Future<void> closePointer() async {
    flushMoves();
    await _pointerSubscription?.cancel();
    await _pointerSocket?.close();
    _pointerSubscription = null;
    _pointerSocket = null;
  }

  Future<void> dispose() async {
    await stopScreenStream();
    await closePointer();
  }
}

Future<ui.Image> decodeUiImage(Uint8List bytes) {
  final completer = Completer<ui.Image>();
  ui.decodeImageFromList(bytes, completer.complete);
  return completer.future;
}

class WhiteboardPage extends StatefulWidget {
  const WhiteboardPage({super.key});

  @override
  State<WhiteboardPage> createState() => _WhiteboardPageState();
}

class _WhiteboardPageState extends State<WhiteboardPage>
    with WidgetsBindingObserver {
  final BridgeClient _bridge = BridgeClient();
  final TextEditingController _urlController = TextEditingController();
  final List<Stroke> _strokes = [];
  final Map<int, Offset> _pointers = {};
  final Map<FloatingButtonId, Offset> _buttonPositions = {
    FloatingButtonId.pen: const Offset(24, 88),
    FloatingButtonId.line: const Offset(24, 156),
    FloatingButtonId.eraser: const Offset(24, 224),
    FloatingButtonId.undo: const Offset(24, 292),
  };
  final Map<FloatingButtonId, double> _buttonSizes = {
    FloatingButtonId.pen: 48,
    FloatingButtonId.line: 48,
    FloatingButtonId.eraser: 48,
    FloatingButtonId.undo: 48,
  };
  final Map<FloatingButtonId, double> _buttonOpacities = {
    FloatingButtonId.pen: 0.88,
    FloatingButtonId.line: 0.88,
    FloatingButtonId.eraser: 0.88,
    FloatingButtonId.undo: 0.88,
  };

  MonitorInfo _monitor = const MonitorInfo(width: 16, height: 10);
  BridgeConnectionState _connectionState = BridgeConnectionState.offline;
  String _statusText = 'Offline';
  ToolMode _tool = ToolMode.pen;
  FloatingButtonId _selectedButton = FloatingButtonId.pen;
  Color _penColor = Colors.black;
  double _penSize = 5;
  bool _settingsVisible = false;
  bool _colorPanelVisible = false;
  bool _penSizePanelVisible = false;
  bool _drawAreaEdit = false;
  bool _snapshotVisible = false;
  bool _screenStreamEnabled = false;
  Rect _drawArea = const Rect.fromLTWH(0.05, 0.05, 0.9, 0.9);
  ViewportState _viewport = const ViewportState();
  Rect _viewportRect = Rect.zero;
  Stroke? _activeStroke;
  int? _activePointer;
  Offset? _lastActiveRatio;
  AreaEditSession? _areaEdit;
  double? _pinchStartDistance;
  ViewportState? _pinchStartViewport;
  Offset? _pinchAnchorRatio;
  ui.Image? _pcShot;
  ui.Image? _screenFrame;
  Timer? _screenReconnectTimer;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    WidgetsBinding.instance.addPostFrameCallback(
      (_) => _showConnectionDialog(),
    );
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _screenReconnectTimer?.cancel();
    _forceEndActiveStroke();
    _bridge.dispose();
    _urlController.dispose();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.inactive ||
        state == AppLifecycleState.paused ||
        state == AppLifecycleState.detached) {
      _forceEndActiveStroke();
    }
  }

  Future<void> _showConnectionDialog() async {
    if (!mounted) {
      return;
    }
    await showDialog<void>(
      context: context,
      barrierDismissible: _connectionState == BridgeConnectionState.online,
      builder: (context) {
        return AlertDialog(
          title: const Text('Connect to PC'),
          content: SizedBox(
            width: 520,
            child: TextField(
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
          ),
          actions: [
            TextButton(
              onPressed: () async {
                final data = await Clipboard.getData(Clipboard.kTextPlain);
                if (data?.text != null) {
                  _urlController.text = data!.text!.trim();
                }
              },
              child: const Text('Paste'),
            ),
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
    await _bridge.connect(
      value: _urlController.text,
      onMonitor: (monitor) {
        if (!mounted) {
          return;
        }
        setState(() => _monitor = monitor);
      },
      onState: (state, label) {
        if (!mounted) {
          return;
        }
        setState(() {
          _connectionState = state;
          _statusText = label;
        });
      },
    );
  }

  Future<void> _loadSnapshot() async {
    final image = await _bridge.fetchSnapshot(
      onMonitor: (monitor) {
        if (mounted) {
          setState(() => _monitor = monitor);
        }
      },
    );
    if (!mounted || image == null) {
      return;
    }
    setState(() {
      _pcShot = image;
      _snapshotVisible = true;
    });
  }

  Future<void> _toggleScreenStream() async {
    if (_screenStreamEnabled) {
      _screenReconnectTimer?.cancel();
      await _bridge.stopScreenStream();
      if (!mounted) {
        return;
      }
      setState(() => _screenStreamEnabled = false);
      return;
    }
    setState(() {
      _screenStreamEnabled = true;
      _snapshotVisible = true;
    });
    await _startScreenStream();
  }

  Future<void> _startScreenStream() async {
    await _bridge.startScreenStream(
      onMonitor: (monitor) {
        if (mounted) {
          setState(() => _monitor = monitor);
        }
      },
      onFrame: (frame) {
        if (mounted) {
          setState(() {
            _screenFrame = frame;
            _snapshotVisible = true;
          });
        }
      },
      onClosed: () {
        if (!mounted || !_screenStreamEnabled) {
          return;
        }
        _screenReconnectTimer?.cancel();
        _screenReconnectTimer = Timer(
          const Duration(milliseconds: 800),
          _startScreenStream,
        );
      },
    );
  }

  void _selectTool(ToolMode tool) {
    setState(() {
      _tool = tool;
      _penSizePanelVisible = tool == ToolMode.pen
          ? _penSizePanelVisible
          : false;
      _selectedButton = switch (tool) {
        ToolMode.pen => FloatingButtonId.pen,
        ToolMode.line => FloatingButtonId.line,
        ToolMode.eraser => FloatingButtonId.eraser,
      };
    });
  }

  void _undoLocal() {
    if (_strokes.isEmpty) {
      return;
    }
    setState(() => _strokes.removeLast());
  }

  void _clearLocal() {
    setState(() {
      _strokes.clear();
      _activeStroke = null;
    });
  }

  void _handleToolTap(FloatingButtonId id) {
    switch (id) {
      case FloatingButtonId.pen:
        _selectTool(ToolMode.pen);
      case FloatingButtonId.line:
        _selectTool(ToolMode.line);
      case FloatingButtonId.eraser:
        _selectTool(ToolMode.eraser);
      case FloatingButtonId.undo:
        setState(() => _selectedButton = FloatingButtonId.undo);
        _undoLocal();
    }
    _sendButtonPassThrough(id);
  }

  void _sendButtonPassThrough(FloatingButtonId id) {
    final position = _buttonPositions[id] ?? Offset.zero;
    final size = _buttonSizes[id] ?? 48;
    final center = position + Offset(size / 2, size / 2);
    final ratio = _ratioForLocal(center);
    if (ratio != null) {
      _bridge.sendClick(ratio);
    }
  }

  void _handlePointerDown(PointerDownEvent event) {
    _pointers[event.pointer] = event.localPosition;
    if (_pointers.length >= 2) {
      _forceEndActiveStroke();
      _startOrUpdatePinch();
      return;
    }
    if (_drawAreaEdit) {
      final handle = _hitAreaHandle(event.localPosition);
      if (handle != null) {
        _areaEdit = AreaEditSession(
          handle: handle,
          startLocal: event.localPosition,
          startArea: _drawArea,
        );
        return;
      }
    }
    final ratio = _ratioForLocal(event.localPosition);
    if (ratio == null) {
      return;
    }
    if (_activePointer != null) {
      _forceEndActiveStroke();
    }
    _activePointer = event.pointer;
    _lastActiveRatio = ratio;
    final insideArea = _drawArea.contains(ratio);
    if (insideArea) {
      final stroke = Stroke(
        tool: _tool,
        points: [ratio],
        color: _penColor,
        size: _tool == ToolMode.eraser ? math.max(18, _penSize * 4) : _penSize,
      );
      _activeStroke = stroke;
      _strokes.add(stroke);
      setState(() {});
    }
    _bridge.sendPointer(
      PointerSample(
        action: 'down',
        ratio: ratio,
        pressure: event.pressure,
        pointerKind: _pointerKind(event.kind),
      ),
    );
  }

  void _handlePointerMove(PointerMoveEvent event) {
    _pointers[event.pointer] = event.localPosition;
    if (_pointers.length >= 2) {
      _startOrUpdatePinch();
      return;
    }
    final edit = _areaEdit;
    if (edit != null) {
      _updateAreaEdit(edit, event.localPosition);
      return;
    }
    if (event.pointer != _activePointer) {
      return;
    }
    final ratio = _ratioForLocal(event.localPosition);
    if (ratio == null) {
      return;
    }
    _lastActiveRatio = ratio;
    if (_activeStroke != null) {
      _updateActiveStroke(ratio);
    }
    _bridge.sendPointer(
      PointerSample(
        action: 'move',
        ratio: ratio,
        pressure: event.pressure,
        pointerKind: _pointerKind(event.kind),
      ),
    );
  }

  void _handlePointerEnd(PointerEvent event) {
    _pointers.remove(event.pointer);
    if (_pointers.length < 2) {
      _pinchStartDistance = null;
      _pinchStartViewport = null;
      _pinchAnchorRatio = null;
    }
    if (_areaEdit != null && event.pointer != _activePointer) {
      _areaEdit = null;
      return;
    }
    if (event.pointer != _activePointer) {
      return;
    }
    final ratio = _ratioForLocal(event.localPosition) ?? _lastActiveRatio;
    if (ratio != null) {
      if (_activeStroke != null) {
        _updateActiveStroke(ratio, force: true);
      }
      _bridge.sendPointer(
        PointerSample(
          action: 'up',
          ratio: ratio,
          pressure: event.pressure,
          pointerKind: _pointerKind(event.kind),
        ),
      );
    }
    _activePointer = null;
    _activeStroke = null;
    _lastActiveRatio = null;
  }

  void _forceEndActiveStroke() {
    final ratio = _lastActiveRatio;
    if (_activePointer != null && ratio != null) {
      _bridge.sendPointer(
        PointerSample(
          action: 'up',
          ratio: ratio,
          pressure: 0,
          pointerKind: 'pen',
        ),
      );
    }
    _activePointer = null;
    _activeStroke = null;
    _lastActiveRatio = null;
  }

  void _updateActiveStroke(Offset ratio, {bool force = false}) {
    final stroke = _activeStroke;
    if (stroke == null) {
      return;
    }
    final points = stroke.points;
    if (_tool == ToolMode.line) {
      if (points.length == 1) {
        points.add(ratio);
      } else {
        points[1] = ratio;
      }
      setState(() {});
      return;
    }
    if (force || points.isEmpty || (points.last - ratio).distance > 0.0004) {
      points.add(ratio);
      setState(() {});
    }
  }

  void _startOrUpdatePinch() {
    final values = _pointers.values.take(2).toList();
    if (values.length < 2) {
      return;
    }
    final distance = (values[0] - values[1]).distance;
    if (distance <= 0) {
      return;
    }
    final focal = Offset(
      (values[0].dx + values[1].dx) / 2,
      (values[0].dy + values[1].dy) / 2,
    );
    if (_pinchStartDistance == null) {
      _pinchStartDistance = distance;
      _pinchStartViewport = _viewport;
      _pinchAnchorRatio = _ratioForLocal(focal);
      return;
    }
    final start = _pinchStartViewport!;
    final anchor = _pinchAnchorRatio ?? const Offset(0.5, 0.5);
    final nextZoom = (start.zoom * distance / _pinchStartDistance!)
        .clamp(1.0, 5.0)
        .toDouble();
    setState(() {
      _viewport = start.copyWith(
        zoom: nextZoom,
        center: _clampCenter(anchor, nextZoom),
      );
    });
  }

  Offset _clampCenter(Offset center, double zoom) {
    final halfVisible = 0.5 / zoom;
    return Offset(
      center.dx.clamp(halfVisible, 1 - halfVisible).toDouble(),
      center.dy.clamp(halfVisible, 1 - halfVisible).toDouble(),
    );
  }

  void _updateAreaEdit(AreaEditSession edit, Offset local) {
    final startRatio = _ratioForLocal(edit.startLocal);
    final currentRatio = _ratioForLocal(local);
    if (startRatio == null || currentRatio == null) {
      return;
    }
    final delta = currentRatio - startRatio;
    var left = edit.startArea.left;
    var top = edit.startArea.top;
    var right = edit.startArea.right;
    var bottom = edit.startArea.bottom;
    switch (edit.handle) {
      case AreaHandle.move:
        left += delta.dx;
        right += delta.dx;
        top += delta.dy;
        bottom += delta.dy;
      case AreaHandle.n:
        top += delta.dy;
      case AreaHandle.e:
        right += delta.dx;
      case AreaHandle.s:
        bottom += delta.dy;
      case AreaHandle.w:
        left += delta.dx;
      case AreaHandle.nw:
        left += delta.dx;
        top += delta.dy;
      case AreaHandle.ne:
        right += delta.dx;
        top += delta.dy;
      case AreaHandle.sw:
        left += delta.dx;
        bottom += delta.dy;
      case AreaHandle.se:
        right += delta.dx;
        bottom += delta.dy;
    }
    setState(() {
      _drawArea = _normalizeArea(Rect.fromLTRB(left, top, right, bottom));
    });
  }

  Rect _normalizeArea(Rect area) {
    const minSize = 0.04;
    var left = area.left.clamp(0.0, 1.0).toDouble();
    var top = area.top.clamp(0.0, 1.0).toDouble();
    var right = area.right.clamp(0.0, 1.0).toDouble();
    var bottom = area.bottom.clamp(0.0, 1.0).toDouble();
    if (right - left < minSize) {
      right = (left + minSize).clamp(0.0, 1.0).toDouble();
      left = (right - minSize).clamp(0.0, 1.0).toDouble();
    }
    if (bottom - top < minSize) {
      bottom = (top + minSize).clamp(0.0, 1.0).toDouble();
      top = (bottom - minSize).clamp(0.0, 1.0).toDouble();
    }
    return Rect.fromLTRB(left, top, right, bottom);
  }

  AreaHandle? _hitAreaHandle(Offset local) {
    final rect = _ratioRectToLocal(_drawArea);
    const pad = 24.0;
    final expanded = rect.inflate(pad);
    if (!expanded.contains(local)) {
      return null;
    }
    final nearLeft = (local.dx - rect.left).abs() <= pad;
    final nearRight = (local.dx - rect.right).abs() <= pad;
    final nearTop = (local.dy - rect.top).abs() <= pad;
    final nearBottom = (local.dy - rect.bottom).abs() <= pad;
    if (nearLeft && nearTop) return AreaHandle.nw;
    if (nearRight && nearTop) return AreaHandle.ne;
    if (nearLeft && nearBottom) return AreaHandle.sw;
    if (nearRight && nearBottom) return AreaHandle.se;
    if (nearTop) return AreaHandle.n;
    if (nearRight) return AreaHandle.e;
    if (nearBottom) return AreaHandle.s;
    if (nearLeft) return AreaHandle.w;
    if (rect.contains(local)) return AreaHandle.move;
    return null;
  }

  String _pointerKind(PointerDeviceKind kind) {
    return switch (kind) {
      PointerDeviceKind.stylus || PointerDeviceKind.invertedStylus => 'pen',
      PointerDeviceKind.mouse => 'mouse',
      _ => 'touch',
    };
  }

  Rect _computeViewportRect(Size size) {
    final base = _fitRect(size, _monitor.aspectRatio);
    final width = base.width * _viewport.zoom;
    final height = base.height * _viewport.zoom;
    return Rect.fromLTWH(
      base.center.dx - _viewport.center.dx * width,
      base.center.dy - _viewport.center.dy * height,
      width,
      height,
    );
  }

  Rect _fitRect(Size size, double aspectRatio) {
    var width = size.width;
    var height = width / aspectRatio;
    if (height > size.height) {
      height = size.height;
      width = height * aspectRatio;
    }
    return Rect.fromLTWH(
      (size.width - width) / 2,
      (size.height - height) / 2,
      width,
      height,
    );
  }

  Offset? _ratioForLocal(Offset local) {
    if (_viewportRect.isEmpty) {
      return null;
    }
    final x = (local.dx - _viewportRect.left) / _viewportRect.width;
    final y = (local.dy - _viewportRect.top) / _viewportRect.height;
    if (x < -0.02 || x > 1.02 || y < -0.02 || y > 1.02) {
      return null;
    }
    return Offset(x.clamp(0.0, 1.0).toDouble(), y.clamp(0.0, 1.0).toDouble());
  }

  Offset _ratioToLocal(Offset ratio) {
    return Offset(
      _viewportRect.left + ratio.dx * _viewportRect.width,
      _viewportRect.top + ratio.dy * _viewportRect.height,
    );
  }

  Rect _ratioRectToLocal(Rect ratioRect) {
    final topLeft = _ratioToLocal(ratioRect.topLeft);
    final bottomRight = _ratioToLocal(ratioRect.bottomRight);
    return Rect.fromPoints(topLeft, bottomRight);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: LayoutBuilder(
        builder: (context, constraints) {
          final size = Size(constraints.maxWidth, constraints.maxHeight);
          _viewportRect = _computeViewportRect(size);
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
                      viewportRect: _viewportRect,
                      strokes: _strokes,
                      drawArea: _drawArea,
                      editingDrawArea: _drawAreaEdit,
                      snapshotVisible: _snapshotVisible,
                      background: _screenStreamEnabled && _screenFrame != null
                          ? _screenFrame
                          : _pcShot,
                    ),
                  ),
                ),
              ),
              ...FloatingButtonId.values.map(_buildFloatingTool),
              Positioned(
                top: 14 + MediaQuery.paddingOf(context).top,
                right: 14,
                child: _TopControls(
                  connectionState: _connectionState,
                  statusText: _statusText,
                  screenStreamEnabled: _screenStreamEnabled,
                  snapshotVisible: _snapshotVisible,
                  hasSnapshot: _pcShot != null || _screenFrame != null,
                  drawAreaEdit: _drawAreaEdit,
                  settingsVisible: _settingsVisible,
                  onConnect: _showConnectionDialog,
                  onSnapshot: _loadSnapshot,
                  onStream: _toggleScreenStream,
                  onToggleSnapshot: () =>
                      setState(() => _snapshotVisible = !_snapshotVisible),
                  onArea: () => setState(() => _drawAreaEdit = !_drawAreaEdit),
                  onSettings: () =>
                      setState(() => _settingsVisible = !_settingsVisible),
                  onClear: _clearLocal,
                ),
              ),
              Positioned(
                left: 18,
                bottom: 18 + MediaQuery.paddingOf(context).bottom,
                child: _ColorButton(
                  color: _penColor,
                  expanded: _colorPanelVisible,
                  onToggle: () =>
                      setState(() => _colorPanelVisible = !_colorPanelVisible),
                  onColor: (color) => setState(() {
                    _penColor = color;
                    _colorPanelVisible = false;
                  }),
                ),
              ),
              if (_settingsVisible)
                Positioned(
                  right: 14,
                  top: 86 + MediaQuery.paddingOf(context).top,
                  child: _SettingsPanel(
                    buttonName: _buttonLabel(_selectedButton),
                    size: _buttonSizes[_selectedButton] ?? 48,
                    opacity: _buttonOpacities[_selectedButton] ?? 0.88,
                    onSize: (value) =>
                        setState(() => _buttonSizes[_selectedButton] = value),
                    onOpacity: (value) => setState(
                      () => _buttonOpacities[_selectedButton] = value,
                    ),
                  ),
                ),
              if (_penSizePanelVisible && _tool == ToolMode.pen)
                Positioned(
                  left: (_buttonPositions[FloatingButtonId.pen]?.dx ?? 24) + 58,
                  top: (_buttonPositions[FloatingButtonId.pen]?.dy ?? 88),
                  child: _PenSizePanel(
                    size: _penSize,
                    onChanged: (value) => setState(() => _penSize = value),
                  ),
                ),
            ],
          );
        },
      ),
    );
  }

  Widget _buildFloatingTool(FloatingButtonId id) {
    final pos = _buttonPositions[id] ?? Offset.zero;
    final size = _buttonSizes[id] ?? 48;
    final selected = _selectedButton == id;
    return Positioned(
      left: pos.dx,
      top: pos.dy,
      child: _FloatingToolButton(
        id: id,
        selected: selected,
        size: size,
        opacity: _buttonOpacities[id] ?? 0.88,
        activeTool: _tool,
        onTap: () => _handleToolTap(id),
        onDrag: (delta) {
          setState(() {
            final next = (_buttonPositions[id] ?? Offset.zero) + delta;
            _buttonPositions[id] = Offset(
              next.dx
                  .clamp(
                    0,
                    math.max(0, MediaQuery.sizeOf(context).width - size),
                  )
                  .toDouble(),
              next.dy
                  .clamp(
                    0,
                    math.max(0, MediaQuery.sizeOf(context).height - size),
                  )
                  .toDouble(),
            );
            _selectedButton = id;
          });
        },
        onPenSize: id == FloatingButtonId.pen && _tool == ToolMode.pen
            ? () => setState(() {
                _selectedButton = FloatingButtonId.pen;
                _penSizePanelVisible = !_penSizePanelVisible;
              })
            : null,
      ),
    );
  }

  String _buttonLabel(FloatingButtonId id) {
    return switch (id) {
      FloatingButtonId.pen => 'Pen',
      FloatingButtonId.line => 'Line',
      FloatingButtonId.eraser => 'Eraser',
      FloatingButtonId.undo => 'Undo',
    };
  }
}

class WhiteboardPainter extends CustomPainter {
  WhiteboardPainter({
    required this.viewportRect,
    required this.strokes,
    required this.drawArea,
    required this.editingDrawArea,
    required this.snapshotVisible,
    required this.background,
  });

  final Rect viewportRect;
  final List<Stroke> strokes;
  final Rect drawArea;
  final bool editingDrawArea;
  final bool snapshotVisible;
  final ui.Image? background;

  @override
  void paint(Canvas canvas, Size size) {
    canvas.drawRect(
      Offset.zero & size,
      Paint()..color = const Color(0xfff5f5f5),
    );
    canvas.drawRect(viewportRect, Paint()..color = Colors.white);

    final bg = background;
    if (snapshotVisible && bg != null) {
      canvas.drawImageRect(
        bg,
        Rect.fromLTWH(0, 0, bg.width.toDouble(), bg.height.toDouble()),
        viewportRect,
        Paint()..filterQuality = FilterQuality.low,
      );
    }

    canvas.saveLayer(Offset.zero & size, Paint());
    canvas.clipRect(_drawAreaLocalRect());
    for (final stroke in strokes) {
      _paintStroke(canvas, stroke);
    }
    canvas.restore();

    final border = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1
      ..color = Colors.black.withValues(alpha: 0.12);
    canvas.drawRect(viewportRect, border);

    if (editingDrawArea) {
      _paintDrawArea(canvas);
    }
  }

  void _paintStroke(Canvas canvas, Stroke stroke) {
    if (stroke.points.isEmpty) {
      return;
    }
    final paint = Paint()
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round
      ..style = PaintingStyle.stroke
      ..strokeWidth = stroke.size
      ..color = stroke.color;
    if (stroke.tool == ToolMode.eraser) {
      paint.blendMode = BlendMode.clear;
    }
    final mapped = stroke.points.map(_ratioToLocal).toList();
    if (mapped.length == 1) {
      final pointPaint = Paint()
        ..color = stroke.color
        ..blendMode = stroke.tool == ToolMode.eraser
            ? BlendMode.clear
            : BlendMode.srcOver;
      canvas.drawCircle(mapped.first, stroke.size / 2, pointPaint);
      return;
    }
    if (stroke.tool == ToolMode.line) {
      canvas.drawLine(mapped.first, mapped.last, paint);
      return;
    }
    final path = Path()..moveTo(mapped.first.dx, mapped.first.dy);
    for (var i = 1; i < mapped.length; i += 1) {
      final previous = mapped[i - 1];
      final current = mapped[i];
      final middle = Offset(
        (previous.dx + current.dx) / 2,
        (previous.dy + current.dy) / 2,
      );
      path.quadraticBezierTo(previous.dx, previous.dy, middle.dx, middle.dy);
    }
    path.lineTo(mapped.last.dx, mapped.last.dy);
    canvas.drawPath(path, paint);
  }

  void _paintDrawArea(Canvas canvas) {
    final rect = _drawAreaLocalRect();
    canvas.drawRect(
      rect,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2
        ..color = const Color(0xffff8a00),
    );
    canvas.drawRect(
      rect,
      Paint()
        ..style = PaintingStyle.fill
        ..color = const Color(0xffff8a00).withValues(alpha: 0.06),
    );
    for (final point in [
      rect.topLeft,
      rect.topCenter,
      rect.topRight,
      rect.centerLeft,
      rect.centerRight,
      rect.bottomLeft,
      rect.bottomCenter,
      rect.bottomRight,
    ]) {
      canvas.drawCircle(point, 7, Paint()..color = const Color(0xffff8a00));
      canvas.drawCircle(point, 7, Paint()..style = PaintingStyle.stroke);
    }
  }

  Offset _ratioToLocal(Offset ratio) {
    return Offset(
      viewportRect.left + ratio.dx * viewportRect.width,
      viewportRect.top + ratio.dy * viewportRect.height,
    );
  }

  Rect _drawAreaLocalRect() {
    return Rect.fromLTRB(
      viewportRect.left + drawArea.left * viewportRect.width,
      viewportRect.top + drawArea.top * viewportRect.height,
      viewportRect.left + drawArea.right * viewportRect.width,
      viewportRect.top + drawArea.bottom * viewportRect.height,
    );
  }

  @override
  bool shouldRepaint(covariant WhiteboardPainter oldDelegate) {
    return true;
  }
}

class _FloatingToolButton extends StatelessWidget {
  const _FloatingToolButton({
    required this.id,
    required this.selected,
    required this.size,
    required this.opacity,
    required this.activeTool,
    required this.onTap,
    required this.onDrag,
    required this.onPenSize,
  });

  final FloatingButtonId id;
  final bool selected;
  final double size;
  final double opacity;
  final ToolMode activeTool;
  final VoidCallback onTap;
  final ValueChanged<Offset> onDrag;
  final VoidCallback? onPenSize;

  @override
  Widget build(BuildContext context) {
    final foreground = selected ? Colors.white : Colors.black;
    final background = selected ? Colors.black : Colors.white;
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: onTap,
      onPanUpdate: (details) => onDrag(details.delta),
      child: Opacity(
        opacity: opacity,
        child: Stack(
          clipBehavior: Clip.none,
          children: [
            Container(
              width: size,
              height: size,
              decoration: BoxDecoration(
                color: background,
                borderRadius: BorderRadius.circular(6),
                border: Border.all(
                  color: selected
                      ? const Color(0xffff8a00)
                      : Colors.black.withValues(alpha: 0.2),
                  width: 2,
                ),
                boxShadow: [
                  BoxShadow(
                    color: Colors.black.withValues(alpha: 0.14),
                    blurRadius: 14,
                    offset: const Offset(0, 6),
                  ),
                ],
              ),
              child: Icon(
                _iconFor(id),
                color: foreground,
                size: math.max(18, size * 0.48),
              ),
            ),
            if (id == FloatingButtonId.pen && activeTool == ToolMode.pen)
              Positioned(
                right: -8,
                bottom: -8,
                child: GestureDetector(
                  onTap: onPenSize,
                  child: Container(
                    width: 26,
                    height: 26,
                    decoration: BoxDecoration(
                      color: const Color(0xffff8a00),
                      shape: BoxShape.circle,
                      border: Border.all(color: Colors.white, width: 2),
                    ),
                    child: const Icon(
                      Icons.arrow_drop_down,
                      size: 20,
                      color: Colors.black,
                    ),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }

  IconData _iconFor(FloatingButtonId id) {
    return switch (id) {
      FloatingButtonId.pen => Icons.edit,
      FloatingButtonId.line => Icons.show_chart,
      FloatingButtonId.eraser => Icons.cleaning_services,
      FloatingButtonId.undo => Icons.undo,
    };
  }
}

class _TopControls extends StatelessWidget {
  const _TopControls({
    required this.connectionState,
    required this.statusText,
    required this.screenStreamEnabled,
    required this.snapshotVisible,
    required this.hasSnapshot,
    required this.drawAreaEdit,
    required this.settingsVisible,
    required this.onConnect,
    required this.onSnapshot,
    required this.onStream,
    required this.onToggleSnapshot,
    required this.onArea,
    required this.onSettings,
    required this.onClear,
  });

  final BridgeConnectionState connectionState;
  final String statusText;
  final bool screenStreamEnabled;
  final bool snapshotVisible;
  final bool hasSnapshot;
  final bool drawAreaEdit;
  final bool settingsVisible;
  final VoidCallback onConnect;
  final VoidCallback onSnapshot;
  final VoidCallback onStream;
  final VoidCallback onToggleSnapshot;
  final VoidCallback onArea;
  final VoidCallback onSettings;
  final VoidCallback onClear;

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: BoxDecoration(
        color: Colors.black.withValues(alpha: 0.86),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(
          color: const Color(0xffff8a00).withValues(alpha: 0.5),
        ),
      ),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            _StatusPill(state: connectionState, text: statusText),
            const SizedBox(width: 8),
            _MiniIconButton(
              icon: Icons.link,
              label: 'Connect',
              onPressed: onConnect,
            ),
            _MiniIconButton(
              icon: Icons.photo_camera,
              label: 'PC Shot',
              onPressed: onSnapshot,
            ),
            _MiniIconButton(
              icon: screenStreamEnabled ? Icons.cast_connected : Icons.cast,
              label: screenStreamEnabled ? 'Stream On' : 'Stream Off',
              selected: screenStreamEnabled,
              onPressed: onStream,
            ),
            _MiniIconButton(
              icon: snapshotVisible ? Icons.visibility : Icons.visibility_off,
              label: snapshotVisible ? 'Hide PC' : 'Show PC',
              enabled: hasSnapshot,
              onPressed: onToggleSnapshot,
            ),
            _MiniIconButton(
              icon: Icons.crop_square,
              label: 'Area',
              selected: drawAreaEdit,
              onPressed: onArea,
            ),
            _MiniIconButton(
              icon: Icons.tune,
              label: 'Settings',
              selected: settingsVisible,
              onPressed: onSettings,
            ),
            _MiniIconButton(
              icon: Icons.delete_outline,
              label: 'Clear',
              onPressed: onClear,
            ),
          ],
        ),
      ),
    );
  }
}

class _MiniIconButton extends StatelessWidget {
  const _MiniIconButton({
    required this.icon,
    required this.label,
    required this.onPressed,
    this.selected = false,
    this.enabled = true,
  });

  final IconData icon;
  final String label;
  final VoidCallback onPressed;
  final bool selected;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    return Tooltip(
      message: label,
      child: IconButton(
        visualDensity: VisualDensity.compact,
        color: selected ? const Color(0xffff8a00) : Colors.white,
        disabledColor: Colors.white.withValues(alpha: 0.28),
        onPressed: enabled ? onPressed : null,
        icon: Icon(icon),
      ),
    );
  }
}

class _StatusPill extends StatelessWidget {
  const _StatusPill({required this.state, required this.text});

  final BridgeConnectionState state;
  final String text;

  @override
  Widget build(BuildContext context) {
    final color = switch (state) {
      BridgeConnectionState.online => const Color(0xff34a853),
      BridgeConnectionState.connecting => const Color(0xffffc107),
      BridgeConnectionState.error => const Color(0xffff453a),
      BridgeConnectionState.offline => const Color(0xff9aa0a6),
    };
    return Container(
      height: 30,
      padding: const EdgeInsets.symmetric(horizontal: 10),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Row(
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
            style: const TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w800,
              color: Colors.white,
            ),
          ),
        ],
      ),
    );
  }
}

class _SettingsPanel extends StatelessWidget {
  const _SettingsPanel({
    required this.buttonName,
    required this.size,
    required this.opacity,
    required this.onSize,
    required this.onOpacity,
  });

  final String buttonName;
  final double size;
  final double opacity;
  final ValueChanged<double> onSize;
  final ValueChanged<double> onOpacity;

  @override
  Widget build(BuildContext context) {
    return _PanelShell(
      width: 260,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            '$buttonName Button',
            style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: 12),
          Text('Size ${size.round()}'),
          Slider(min: 24, max: 96, value: size, onChanged: onSize),
          Text('Opacity ${(opacity * 100).round()}%'),
          Slider(min: 0.2, max: 1, value: opacity, onChanged: onOpacity),
        ],
      ),
    );
  }
}

class _PenSizePanel extends StatelessWidget {
  const _PenSizePanel({required this.size, required this.onChanged});

  final double size;
  final ValueChanged<double> onChanged;

  @override
  Widget build(BuildContext context) {
    return _PanelShell(
      width: 240,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          const Text(
            'Pen thickness',
            style: TextStyle(fontSize: 14, fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: 8),
          Text('${size.round()} px'),
          Slider(min: 1, max: 36, value: size, onChanged: onChanged),
        ],
      ),
    );
  }
}

class _ColorButton extends StatelessWidget {
  const _ColorButton({
    required this.color,
    required this.expanded,
    required this.onToggle,
    required this.onColor,
  });

  final Color color;
  final bool expanded;
  final VoidCallback onToggle;
  final ValueChanged<Color> onColor;

  static const colors = [
    Colors.black,
    Color(0xffe53935),
    Color(0xff1e88e5),
    Color(0xff43a047),
    Color(0xffff8a00),
    Color(0xff8e24aa),
  ];

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.end,
      children: [
        GestureDetector(
          onTap: onToggle,
          child: Container(
            width: 48,
            height: 48,
            decoration: BoxDecoration(
              color: Colors.white.withValues(alpha: 0.9),
              borderRadius: BorderRadius.circular(6),
              border: Border.all(color: Colors.black.withValues(alpha: 0.2)),
              boxShadow: [
                BoxShadow(
                  color: Colors.black.withValues(alpha: 0.14),
                  blurRadius: 14,
                  offset: const Offset(0, 6),
                ),
              ],
            ),
            child: Center(
              child: Container(
                width: 26,
                height: 26,
                decoration: BoxDecoration(
                  color: color,
                  shape: BoxShape.circle,
                  border: Border.all(
                    color: Colors.black.withValues(alpha: 0.25),
                  ),
                ),
              ),
            ),
          ),
        ),
        if (expanded) ...[
          const SizedBox(width: 10),
          _PanelShell(
            width: 244,
            child: Wrap(
              spacing: 10,
              runSpacing: 10,
              children: [
                for (final item in colors)
                  GestureDetector(
                    onTap: () => onColor(item),
                    child: Container(
                      width: 32,
                      height: 32,
                      decoration: BoxDecoration(
                        color: item,
                        shape: BoxShape.circle,
                        border: Border.all(
                          color: item == color
                              ? const Color(0xffff8a00)
                              : Colors.black12,
                          width: 3,
                        ),
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ],
      ],
    );
  }
}

class _PanelShell extends StatelessWidget {
  const _PanelShell({required this.width, required this.child});

  final double width;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: width,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.94),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: Colors.black.withValues(alpha: 0.12)),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.14),
            blurRadius: 22,
            offset: const Offset(0, 10),
          ),
        ],
      ),
      child: child,
    );
  }
}
