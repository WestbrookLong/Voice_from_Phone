import 'package:flutter_test/flutter_test.dart';

import 'package:ipad_whiteboard_app/main.dart';

void main() {
  testWidgets('renders the whiteboard toolbar', (tester) async {
    await tester.pumpWidget(const WhiteboardBridgeApp());
    await tester.pump();

    expect(find.text('Pen'), findsOneWidget);
    expect(find.text('Eraser'), findsOneWidget);
    expect(find.text('Clear'), findsOneWidget);
    expect(find.text('Connect'), findsWidgets);
  });
}
