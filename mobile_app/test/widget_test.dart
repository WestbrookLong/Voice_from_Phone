import 'package:flutter_test/flutter_test.dart';

import 'package:voice_input_mobile/main.dart';

void main() {
  testWidgets('shows input bridge screen', (WidgetTester tester) async {
    await tester.pumpWidget(const VoiceInputApp());

    expect(find.text('实时输入'), findsOneWidget);
    expect(find.text('连接电脑'), findsOneWidget);
  });
}
