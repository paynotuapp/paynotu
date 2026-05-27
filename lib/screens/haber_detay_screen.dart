import 'package:flutter/material.dart';
import 'package:html/parser.dart' as html_parser;
import 'package:http/http.dart' as http;
import 'package:share_plus/share_plus.dart';
import 'package:url_launcher/url_launcher.dart';

class HaberDetayScreen extends StatefulWidget {
  final String url;
  final String baslik;
  final String kaynak;

  const HaberDetayScreen({
    super.key,
    required this.url,
    required this.baslik,
    required this.kaynak,
  });

  @override
  State<HaberDetayScreen> createState() => _HaberDetayScreenState();
}

class _HaberDetayScreenState extends State<HaberDetayScreen> {
  _Makale? _makale;
  bool _yukleniyor = true;
  String? _hata;

  @override
  void initState() {
    super.initState();
    _yukle();
  }

  Future<void> _yukle() async {
    setState(() { _yukleniyor = true; _hata = null; });
    try {
      final makale = await _scrape(widget.url);
      setState(() { _makale = makale; _yukleniyor = false; });
    } catch (e) {
      setState(() { _hata = e.toString(); _yukleniyor = false; });
    }
  }

  Future<_Makale> _scrape(String url) async {
    final res = await http.get(
      Uri.parse(url),
      headers: {
        'User-Agent': 'Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 '
            '(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
        'Accept': 'text/html',
        'Accept-Language': 'tr-TR,tr;q=0.9,en;q=0.8',
      },
    ).timeout(const Duration(seconds: 15));

    if (res.statusCode != 200) {
      throw Exception('Sayfa yüklenemedi (HTTP ${res.statusCode})');
    }

    final finalUrl = res.request?.url.toString() ?? url;
    final doc = html_parser.parse(res.body);

    // Başlık
    final baslik =
        doc.querySelector('h1')?.text.trim() ??
        doc.querySelector('h2')?.text.trim() ??
        widget.baslik;

    // Tarih — Hurriyet: <time> elementi
    final tarih =
        doc.querySelector('time')?.text.trim() ??
        doc.querySelector('[itemprop="datePublished"]')?.attributes['datetime']?.trim() ??
        doc.querySelector('.date, .tarih, .news-date')?.text.trim() ??
        '';

    // İçerik — Hurriyet öncelikli, sonra genel fallback'ler
    final containerSectors = [
      '.article-content',       // Hurriyet
      '[itemprop="articleBody"]',
      '.news-detail-content',
      '.news-content',
      '.entry-content',
      '.post-content',
      '.content-body',
      '.detay-icerik',
      'article',
      'main',
    ];

    List<String> paragraflar = [];
    for (final sel in containerSectors) {
      final container = doc.querySelector(sel);
      if (container != null) {
        paragraflar = container
            .querySelectorAll('p')
            .map((p) => p.text.trim())
            .where((t) => t.length > 20)
            .toList();
        if (paragraflar.isNotEmpty) break;
      }
    }

    // Son çare: tüm uzun p'leri topla
    if (paragraflar.isEmpty) {
      paragraflar = doc
          .querySelectorAll('p')
          .map((p) => p.text.trim())
          .where((t) => t.length > 40)
          .toList();
    }

    if (paragraflar.isEmpty) {
      throw Exception(
          'Bu haber sitesi içeriğini engelledi.\nAşağıdaki butona basarak tarayıcıda aç.');
    }

    return _Makale(
      baslik: baslik,
      tarih: _temizleTarih(tarih),
      paragraflar: paragraflar,
      kaynakUrl: finalUrl,
    );
  }

  String _temizleTarih(String raw) {
    if (raw.isEmpty) return '';
    // ISO 8601 → okunabilir
    try {
      final dt = DateTime.parse(raw).toLocal();
      final ay = [
        '', 'Oca', 'Şub', 'Mar', 'Nis', 'May', 'Haz',
        'Tem', 'Ağu', 'Eyl', 'Eki', 'Kas', 'Ara'
      ];
      return '${dt.day} ${ay[dt.month]} ${dt.year} ${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}';
    } catch (_) {
      return raw;
    }
  }

  Future<void> _tarayicidaAc() async {
    final uri = Uri.parse(widget.url);
    if (await canLaunchUrl(uri)) {
      await launchUrl(uri, mode: LaunchMode.externalApplication);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Theme.of(context).scaffoldBackgroundColor,
      appBar: AppBar(
        backgroundColor: const Color(0xFF1565C0),
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
      body: _buildBody(),
    );
  }

  Widget _buildBody() {
    if (_yukleniyor) {
      return const Center(
          child: CircularProgressIndicator(color: Color(0xFF1565C0)));
    }

    if (_hata != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Icon(Icons.article_outlined, size: 56, color: Theme.of(context).colorScheme.onSurfaceVariant),
            const SizedBox(height: 12),
            Text(_hata!,
                style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant, fontSize: 13),
                textAlign: TextAlign.center),
            const SizedBox(height: 16),
            Row(mainAxisAlignment: MainAxisAlignment.center, children: [
              ElevatedButton.icon(
                onPressed: _yukle,
                icon: const Icon(Icons.refresh, size: 16),
                label: const Text('Tekrar Dene'),
                style: ElevatedButton.styleFrom(
                  backgroundColor: const Color(0xFF1565C0),
                  foregroundColor: Colors.white,
                ),
              ),
              const SizedBox(width: 10),
              OutlinedButton.icon(
                onPressed: _tarayicidaAc,
                icon: const Icon(Icons.open_in_browser, size: 16),
                label: const Text('Tarayıcıda Aç'),
                style: OutlinedButton.styleFrom(
                  foregroundColor: const Color(0xFF1565C0),
                  side: const BorderSide(color: Color(0xFF1565C0)),
                ),
              ),
            ]),
          ]),
        ),
      );
    }

    final m = _makale!;
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 32),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        // Kaynak rozeti
        if (widget.kaynak.isNotEmpty)
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
            decoration: BoxDecoration(
              color: const Color(0xFF1565C0).withValues(alpha: 0.1),
              borderRadius: BorderRadius.circular(6),
            ),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              const Icon(Icons.newspaper, size: 12, color: Color(0xFF1565C0)),
              const SizedBox(width: 4),
              Flexible(
                child: Text(
                  widget.kaynak,
                  style: const TextStyle(
                      fontSize: 11,
                      color: Color(0xFF1565C0),
                      fontWeight: FontWeight.w600),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ]),
          ),

        const SizedBox(height: 10),

        // Başlık
        Text(m.baslik,
            style: const TextStyle(
                fontSize: 18, fontWeight: FontWeight.bold, height: 1.4)),

        // Tarih
        if (m.tarih.isNotEmpty) ...[
          const SizedBox(height: 8),
          Row(children: [
            Icon(Icons.access_time, size: 13, color: Theme.of(context).colorScheme.onSurfaceVariant),
            const SizedBox(width: 4),
            Flexible(
              child: Text(m.tarih,
                  style: TextStyle(fontSize: 12, color: Theme.of(context).colorScheme.onSurfaceVariant),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis),
            ),
          ]),
        ],

        const SizedBox(height: 16),
        const Divider(height: 1),
        const SizedBox(height: 16),

        // İçerik
        ...m.paragraflar.map((p) => Padding(
              padding: const EdgeInsets.only(bottom: 14),
              child: Text(p,
                  style: const TextStyle(fontSize: 15, height: 1.65)),
            )),

        // Tarayıcıda aç
        const SizedBox(height: 8),
        const Divider(height: 1),
        const SizedBox(height: 12),
        OutlinedButton.icon(
          onPressed: _tarayicidaAc,
          icon: const Icon(Icons.open_in_browser, size: 16),
          label: const Text('Kaynakta Oku'),
          style: OutlinedButton.styleFrom(
            foregroundColor: const Color(0xFF1565C0),
            side: const BorderSide(color: Color(0xFF1565C0)),
          ),
        ),
      ]),
    );
  }
}

class _Makale {
  final String baslik;
  final String tarih;
  final List<String> paragraflar;
  final String kaynakUrl;

  const _Makale({
    required this.baslik,
    required this.tarih,
    required this.paragraflar,
    required this.kaynakUrl,
  });
}
