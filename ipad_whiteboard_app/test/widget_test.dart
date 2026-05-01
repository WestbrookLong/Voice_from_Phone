import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ipad_whiteboard_app/main.dart';

void main() {
  testWidgets('renders the native whiteboard controls', (tester) async {
    await tester.pumpWidget(const WhiteboardBridgeApp());
    await tester.pump();

    expect(find.text('Connect to PC'), findsOneWidget);
    expect(find.byIcon(Icons.edit), findsOneWidget);
    expect(find.byIcon(Icons.show_chart), findsOneWidget);
    expect(find.byIcon(Icons.cleaning_services), findsOneWidget);
    expect(find.byIcon(Icons.undo), findsOneWidget);
    expect(find.byIcon(Icons.unfold_more), findsOneWidget);
  });
}
