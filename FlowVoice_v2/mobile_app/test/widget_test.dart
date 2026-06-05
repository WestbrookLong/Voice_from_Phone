import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:voice_input_mobile/main.dart';

void main() {
  testWidgets('shows flow voice screen', (WidgetTester tester) async {
    await tester.pumpWidget(const FlowVoiceApp());

    expect(find.text('Flow Voice'), findsOneWidget);
    expect(find.byIcon(Icons.settings), findsOneWidget);
    expect(find.byIcon(Icons.qr_code_scanner), findsOneWidget);
  });
}
