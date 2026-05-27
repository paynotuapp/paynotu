import 'package:flutter/material.dart';
import 'package:share_plus/share_plus.dart';
import 'package:webview_flutter/webview_flutter.dart';

class KapDetayScreen extends StatefulWidget {
  final String url;
  final String baslik;

  const KapDetayScreen({super.key, required this.url, required this.baslik});

  @override
  State<KapDetayScreen> createState() => _KapDetayScreenState();
}

class _KapDetayScreenState extends State<KapDetayScreen> {
  late final WebViewController _controller;
  bool _yukleniyor = true;

  @override
  void initState() {
    super.initState();
    _controller = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setNavigationDelegate(NavigationDelegate(
        onPageStarted: (_) => setState(() => _yukleniyor = true),
        onPageFinished: (_) => setState(() => _yukleniyor = false),
      ))
      ..loadRequest(Uri.parse(widget.url));
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Theme.of(context).scaffoldBackgroundColor,
      appBar: AppBar(
        backgroundColor: Theme.of(context).colorScheme.primary,
        elevation: 0,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back, color: Colors.white),
          onPressed: () => Navigator.pop(context),
        ),
        title: Text(
          widget.baslik,
          style: const TextStyle(
              color: Colors.white, fontWeight: FontWeight.bold, fontSize: 14),
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.share, color: Colors.white),
            onPressed: () => Share.share(widget.url, subject: widget.baslik),
          ),
        ],
      ),
      body: Stack(
        children: [
          WebViewWidget(controller: _controller),
          if (_yukleniyor)
            Center(
                child: CircularProgressIndicator(color: Theme.of(context).colorScheme.primary)),
        ],
      ),
    );
  }
}
