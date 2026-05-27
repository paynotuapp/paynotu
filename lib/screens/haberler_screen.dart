import 'package:flutter/material.dart';
import 'package:html/parser.dart' as html_parser;
import 'package:http/http.dart' as http;
import 'package:intl/intl.dart';
import 'package:xml/xml.dart';
import 'kap_detay_screen.dart';
import 'webview_screen.dart';


// ─── 15-dk cache ────────────────────────────────────────────────────────────

class _KapCache {
  static List<_KapBildirim>? items;
  static DateTime? fetchedAt;
  static bool get gecerli =>
      items != null &&
      fetchedAt != null &&
      DateTime.now().difference(fetchedAt!) < const Duration(minutes: 15);
  static void kaydet(List<_KapBildirim> data) { items = data; fetchedAt = DateTime.now(); }
  static void temizle() { items = null; fetchedAt = null; }
}

class _HaberCache {
  static List<_HaberItem>? items;
  static DateTime? fetchedAt;

  static bool get gecerli =>
      items != null &&
      fetchedAt != null &&
      DateTime.now().difference(fetchedAt!) < const Duration(minutes: 15);

  static void kaydet(List<_HaberItem> data) {
    items = data;
    fetchedAt = DateTime.now();
  }

  static void temizle() {
    items = null;
    fetchedAt = null;
  }
}

// ─── Modeller ───────────────────────────────────────────────────────────────

class _KapBildirim {
  final String url;
  final String baslik;
  final String sirket;
  final String tip;
  final String tarih;
  const _KapBildirim({
    required this.url,
    required this.baslik,
    required this.sirket,
    required this.tip,
    required this.tarih,
  });
}

class _RssKaynak {
  final String isim;
  final String url;
  final Color renk;
  const _RssKaynak(this.isim, this.url, this.renk);
}

const _rssKaynaklar = [
  _RssKaynak('Investing (Genel)', 'https://tr.investing.com/rss/news.rss',    Color(0xFFE0741B)),
  _RssKaynak('Investing (Borsa)', 'https://tr.investing.com/rss/news_25.rss', Color(0xFFC0560A)),
  _RssKaynak('Dünya Gazetesi',    'https://www.dunya.com/rss',                Color(0xFF1565C0)),
];

class _HaberItem {
  final String baslik;
  final String ozet;
  final String kaynak;
  final Color kaynakRenk;
  final String tarih;
  final String url;
  final DateTime parsedDate;

  const _HaberItem({
    required this.baslik,
    required this.ozet,
    required this.kaynak,
    required this.kaynakRenk,
    required this.tarih,
    required this.url,
    required this.parsedDate,
  });
}

// ─── Ana ekran ───────────────────────────────────────────────────────────────

class HaberlerScreen extends StatefulWidget {
  const HaberlerScreen({super.key});

  @override
  State<HaberlerScreen> createState() => _HaberlerScreenState();
}

class _HaberlerScreenState extends State<HaberlerScreen>
    with SingleTickerProviderStateMixin {
  late final TabController _tabController;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 2, vsync: this);
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFF5F5F5),
      appBar: AppBar(
        backgroundColor: const Color(0xFF00C853),
        elevation: 0,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back, color: Colors.white),
          onPressed: () => Navigator.pop(context),
        ),
        title: const Text(
          'Haberler',
          style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold),
        ),
        bottom: TabBar(
          controller: _tabController,
          indicatorColor: Colors.white,
          indicatorWeight: 3,
          labelColor: Colors.white,
          unselectedLabelColor: Colors.white70,
          labelStyle: const TextStyle(fontWeight: FontWeight.bold, fontSize: 13),
          tabs: const [
            Tab(text: 'KAP Bildirimleri'),
            Tab(text: 'Finans Haberleri'),
          ],
        ),
      ),
      body: TabBarView(
        controller: _tabController,
        children: const [
          _KapTab(),
          _HaberlerTab(),
        ],
      ),
    );
  }
}

// ─── Tab 1: KAP Bildirimleri (Bigpara scraping) ─────────────────────────────

class _KapTab extends StatefulWidget {
  const _KapTab();
  @override
  State<_KapTab> createState() => _KapTabState();
}

class _KapTabState extends State<_KapTab> with AutomaticKeepAliveClientMixin {
  List<_KapBildirim> _bildirimler = [];
  bool _yukleniyor = true;
  String? _hata;

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    _ilkYukle();
  }

  Future<void> _ilkYukle() async {
    if (_KapCache.gecerli) {
      setState(() { _bildirimler = _KapCache.items!; _yukleniyor = false; });
      return;
    }
    await _yukle();
  }

  Future<void> _yenile() async {
    _KapCache.temizle();
    await _yukle();
  }

  Future<void> _yukle() async {
    setState(() { _yukleniyor = true; _hata = null; });
    try {
      final liste = await _scrapeKap();
      _KapCache.kaydet(liste);
      setState(() { _bildirimler = liste; _yukleniyor = false; });
    } catch (e) {
      setState(() { _hata = e.toString(); _yukleniyor = false; });
    }
  }

  Future<List<_KapBildirim>> _scrapeKap() async {
    final res = await http.get(
      Uri.parse('https://bigpara.hurriyet.com.tr/haberler/kap-haberleri/'),
      headers: {
        'User-Agent': 'Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml',
        'Accept-Language': 'tr-TR,tr;q=0.9',
      },
    ).timeout(const Duration(seconds: 15));

    if (res.statusCode != 200) {
      throw Exception('Bigpara yanıt vermedi (HTTP ${res.statusCode})');
    }

    final doc = html_parser.parse(res.body);
    // KAP haber linkleri: href "/haberler/kap-haberleri/..._ID\d+/" formatında
    final linkler = doc.querySelectorAll('a[href*="/kap-haberleri/"]');

    final liste = <_KapBildirim>[];
    for (final a in linkler) {
      final href = a.attributes['href'] ?? '';
      if (!RegExp(r'_ID\d+').hasMatch(href)) continue;

      final tamBaslik = a.text.trim().replaceAll(RegExp(r'\s+'), ' ');
      if (tamBaslik.isEmpty) continue;

      // Başlık formatı: "KAP ***TICKER*** Şirket Adı (Bildirim Tipi)"
      // veya: "KAP TICKER Şirket Adı (Bildirim Tipi)"
      String sirket = '';
      String tip = '';
      String baslik = tamBaslik;

      final tickerMatch = RegExp(r'\*{2,3}([A-Z0-9]+)\*{2,3}').firstMatch(tamBaslik);
      if (tickerMatch != null) {
        sirket = tickerMatch.group(1) ?? '';
        baslik = tamBaslik.replaceAll(tickerMatch.group(0)!, '').trim();
      }

      final tipMatch = RegExp(r'\(([^)]+)\)\s*$').firstMatch(baslik);
      if (tipMatch != null) {
        tip = tipMatch.group(1) ?? '';
        baslik = baslik.substring(0, tipMatch.start).trim();
      }
      // "KAP " önekini kaldır
      baslik = baslik.replaceFirst(RegExp(r'^KAP\s+'), '').trim();

      // Tarih: kardeş veya yakın span/p element
      final parent = a.parent;
      final tarihEl = parent?.querySelector('.date, .tarih, span, time');
      final tarih = tarihEl?.text.trim() ?? '';

      liste.add(_KapBildirim(
        url: href.startsWith('http')
            ? href
            : 'https://bigpara.hurriyet.com.tr$href',
        baslik: baslik.isNotEmpty ? baslik : tamBaslik,
        sirket: sirket,
        tip: tip,
        tarih: tarih,
      ));
    }

    if (liste.isEmpty) throw Exception('Bildirim bulunamadı — sayfa yapısı değişmiş olabilir.');
    return liste;
  }

  void _ac(BuildContext context, _KapBildirim b) {
    Navigator.push(context, MaterialPageRoute(
      builder: (_) => KapDetayScreen(url: b.url, baslik: b.baslik),
    ));
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    if (_yukleniyor) {
      return const Center(child: CircularProgressIndicator(color: Color(0xFF00C853)));
    }
    if (_hata != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            const Icon(Icons.cloud_off, size: 56, color: Colors.grey),
            const SizedBox(height: 12),
            Text(_hata!, style: const TextStyle(color: Colors.grey, fontSize: 13),
                textAlign: TextAlign.center),
            const SizedBox(height: 16),
            ElevatedButton.icon(
              onPressed: _yenile,
              icon: const Icon(Icons.refresh, size: 16),
              label: const Text('Tekrar Dene'),
              style: ElevatedButton.styleFrom(
                backgroundColor: const Color(0xFF00C853),
                foregroundColor: Colors.white,
              ),
            ),
          ]),
        ),
      );
    }
    return RefreshIndicator(
      color: const Color(0xFF00C853),
      onRefresh: _yenile,
      child: ListView.separated(
        padding: const EdgeInsets.fromLTRB(12, 12, 12, 24),
        itemCount: _bildirimler.length,
        separatorBuilder: (context, index) => const SizedBox(height: 8),
        itemBuilder: (ctx, i) => _kart(ctx, _bildirimler[i]),
      ),
    );
  }

  Widget _kart(BuildContext context, _KapBildirim b) {
    return InkWell(
      onTap: () => _ac(context, b),
      borderRadius: BorderRadius.circular(12),
      child: Container(
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(12),
          border: const Border(left: BorderSide(color: Color(0xFF00C853), width: 3)),
          boxShadow: [BoxShadow(
            color: Colors.black.withValues(alpha: 0.05),
            blurRadius: 4, offset: const Offset(0, 2),
          )],
        ),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            if (b.sirket.isNotEmpty || b.tip.isNotEmpty) ...[
              Row(children: [
                if (b.sirket.isNotEmpty) _rozet(b.sirket, const Color(0xFF00C853)),
                if (b.sirket.isNotEmpty && b.tip.isNotEmpty) const SizedBox(width: 6),
                if (b.tip.isNotEmpty)
                  Flexible(child: _rozet(b.tip, Colors.blueGrey)),
              ]),
              const SizedBox(height: 6),
            ],
            Text(b.baslik,
                style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w500),
                maxLines: 2, overflow: TextOverflow.ellipsis),
            if (b.tarih.isNotEmpty) ...[
              const SizedBox(height: 4),
              Text(b.tarih, style: const TextStyle(fontSize: 11, color: Colors.grey)),
            ],
          ])),
          const SizedBox(width: 6),
          const Icon(Icons.open_in_new, size: 14, color: Colors.grey),
        ]),
      ),
    );
  }

  Widget _rozet(String label, Color renk) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
    decoration: BoxDecoration(
      color: renk.withValues(alpha: 0.12),
      borderRadius: BorderRadius.circular(5),
    ),
    child: Text(
      label,
      style: TextStyle(color: renk, fontWeight: FontWeight.bold, fontSize: 11),
      maxLines: 1,
      overflow: TextOverflow.ellipsis,
    ),
  );
}

// ─── Tab 2: Finans Haberleri (çoklu RSS) ────────────────────────────────────

class _HaberlerTab extends StatefulWidget {
  const _HaberlerTab();
  @override
  State<_HaberlerTab> createState() => _HaberlerTabState();
}

class _HaberlerTabState extends State<_HaberlerTab>
    with AutomaticKeepAliveClientMixin {
  List<_HaberItem> _tumHaberler = [];
  bool _yukleniyor = true;
  // null = Tümü, string = kaynak ismi
  String? _seciliKaynak;
  // kaynak bazında hata mesajları
  final Map<String, String> _kaynakHatalari = {};

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    _ilkYukle();
  }

  Future<void> _ilkYukle() async {
    if (_HaberCache.gecerli) {
      setState(() { _tumHaberler = _HaberCache.items!; _yukleniyor = false; });
      return;
    }
    await _yukle();
  }

  Future<void> _yukle() async {
    setState(() { _yukleniyor = true; _kaynakHatalari.clear(); });

    // Her kaynağı paralel çek; hata olsa da diğerleri devam eder
    final sonuclar = await Future.wait(
      _rssKaynaklar.map((k) => _fetchKaynak(k)),
    );

    final birlesik = <_HaberItem>[];
    for (final liste in sonuclar) {
      birlesik.addAll(liste);
    }
    birlesik.sort((a, b) => b.parsedDate.compareTo(a.parsedDate));

    // URL bazlı tekilleştir
    final gorulenUrl = <String>{};
    final tekil = birlesik.where((h) => gorulenUrl.add(h.url)).toList();

    _HaberCache.kaydet(tekil);
    setState(() { _tumHaberler = tekil; _yukleniyor = false; });
  }

  Future<List<_HaberItem>> _fetchKaynak(_RssKaynak kaynak) async {
    try {
      final res = await http.get(
        Uri.parse(kaynak.url),
        headers: {
          'User-Agent': 'Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36',
          'Accept': 'application/rss+xml, application/xml, text/xml',
          'Accept-Language': 'tr-TR,tr;q=0.9',
        },
      ).timeout(const Duration(seconds: 15));

      if (res.statusCode != 200) throw Exception('HTTP ${res.statusCode}');

      final doc = XmlDocument.parse(res.body);
      final items = doc.findAllElements('item');
      final list = <_HaberItem>[];

      for (final item in items) {
        final baslik = _xmlText(item, 'title');
        final link   = _xmlText(item, 'link');
        if (baslik.isEmpty || link.isEmpty) continue;
        final rawDate  = _xmlText(item, 'pubDate');
        final dt       = _parseDate(rawDate);
        final tarih    = _formatDate(dt);
        final ozet     = _stripHtml(_xmlText(item, 'description'));
        list.add(_HaberItem(
          baslik: baslik,
          ozet: ozet,
          kaynak: kaynak.isim,
          kaynakRenk: kaynak.renk,
          tarih: tarih,
          url: link,
          parsedDate: dt,
        ));
      }
      return list;
    } catch (e) {
      _kaynakHatalari[kaynak.isim] = e.toString();
      return [];
    }
  }

  Future<void> _yenile() async {
    _HaberCache.temizle();
    await _yukle();
  }

  // ── Yardımcılar ─────────────────────────────────────────────────────────────

  String _xmlText(XmlElement el, String tag) {
    try { return el.findElements(tag).first.innerText.trim(); }
    catch (_) { return ''; }
  }

  String _stripHtml(String raw) {
    if (raw.isEmpty) return '';
    try { return html_parser.parse(raw).body?.text.trim() ?? raw; }
    catch (_) { return raw.replaceAll(RegExp(r'<[^>]+>'), '').trim(); }
  }

  static const _months = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
    'oca': 1, 'şub': 2, 'mar2': 3, 'nis': 4, 'may2': 5, 'haz': 6,
    'tem': 7, 'ağu': 8, 'eyl': 9, 'eki': 10, 'kas': 11, 'ara': 12,
  };

  DateTime _parseDate(String raw) {
    if (raw.isEmpty) return DateTime(2000);
    // RFC 2822: "Wed, 21 Apr 2026 14:30:00 +0300"
    try {
      final parts = raw.replaceAll(',', '').trim().split(RegExp(r'\s+'));
      final s = parts.length >= 6 ? 1 : 0;
      return DateTime.utc(
        int.parse(parts[s + 2]),
        _months[parts[s + 1].toLowerCase().substring(0, 3)] ?? 1,
        int.parse(parts[s]),
        int.parse(parts[s + 3].split(':')[0]),
        int.parse(parts[s + 3].split(':')[1]),
      );
    } catch (_) {
      try { return DateTime.parse(raw); } catch (_) { return DateTime(2000); }
    }
  }

  String _formatDate(DateTime dt) {
    try {
      return DateFormat('dd.MM.yyyy HH:mm', 'tr').format(dt.toLocal());
    } catch (_) { return ''; }
  }

  // ── Filtre ──────────────────────────────────────────────────────────────────

  List<_HaberItem> get _filtreliHaberler => _seciliKaynak == null
      ? _tumHaberler
      : _tumHaberler.where((h) => h.kaynak == _seciliKaynak).toList();

  // ── Navigasyon ──────────────────────────────────────────────────────────────

  void _ac(BuildContext context, _HaberItem h) {
    if (h.url.isEmpty) return;
    Navigator.push(context, MaterialPageRoute(
      builder: (_) => WebViewScreen(url: h.url, baslik: h.baslik),
    ));
  }

  // ── Build ────────────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    super.build(context);

    if (_yukleniyor) {
      return const Center(child: CircularProgressIndicator(color: Color(0xFF00C853)));
    }

    if (_tumHaberler.isEmpty) {
      return _bosWidget();
    }

    final liste = _filtreliHaberler;

    return RefreshIndicator(
      color: const Color(0xFF00C853),
      onRefresh: _yenile,
      child: CustomScrollView(
        slivers: [
          SliverToBoxAdapter(child: _filtreCipleri()),
          if (_kaynakHatalari.isNotEmpty)
            SliverToBoxAdapter(child: _hataBanner()),
          SliverPadding(
            padding: const EdgeInsets.fromLTRB(12, 0, 12, 24),
            sliver: SliverList(
              delegate: SliverChildBuilderDelegate(
                (ctx, i) {
                  if (i.isOdd) return const SizedBox(height: 8);
                  return _haberKart(ctx, liste[i ~/ 2]);
                },
                childCount: liste.length * 2 - 1,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _filtreCipleri() {
    return SizedBox(
      height: 46,
      child: ListView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.fromLTRB(12, 8, 12, 4),
        children: [
          _chip('Tümü', null, const Color(0xFF00C853)),
          ...(_rssKaynaklar.map((k) => _chip(k.isim, k.isim, k.renk))),
        ],
      ),
    );
  }

  Widget _chip(String label, String? kaynak, Color renk) {
    final secili = _seciliKaynak == kaynak;
    return Padding(
      padding: const EdgeInsets.only(right: 8),
      child: GestureDetector(
        onTap: () => setState(() => _seciliKaynak = kaynak),
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 150),
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 5),
          decoration: BoxDecoration(
            color: secili ? renk : Colors.white,
            borderRadius: BorderRadius.circular(20),
            border: Border.all(color: secili ? renk : Colors.grey.shade300),
          ),
          child: Text(
            label,
            style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w600,
              color: secili ? Colors.white : Colors.grey.shade700,
            ),
          ),
        ),
      ),
    );
  }

  Widget _hataBanner() {
    final mesajlar = _kaynakHatalari.entries
        .map((e) => '${e.key}: ${e.value}')
        .join('\n');
    return Container(
      margin: const EdgeInsets.fromLTRB(12, 4, 12, 4),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: Colors.orange.shade50,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: Colors.orange.shade200),
      ),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Icon(Icons.warning_amber_rounded, size: 16, color: Colors.orange.shade700),
        const SizedBox(width: 8),
        Expanded(
          child: Text(
            'Bazı kaynaklar yüklenemedi:\n$mesajlar',
            style: TextStyle(fontSize: 11, color: Colors.orange.shade900),
          ),
        ),
      ]),
    );
  }

  Widget _bosWidget() {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          const Icon(Icons.cloud_off, size: 56, color: Colors.grey),
          const SizedBox(height: 12),
          const Text('Hiçbir kaynaktan haber yüklenemedi.',
              style: TextStyle(fontWeight: FontWeight.bold, fontSize: 15),
              textAlign: TextAlign.center),
          if (_kaynakHatalari.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text(
              _kaynakHatalari.entries.map((e) => '${e.key}: ${e.value}').join('\n'),
              style: const TextStyle(color: Colors.grey, fontSize: 11),
              textAlign: TextAlign.center,
            ),
          ],
          const SizedBox(height: 16),
          ElevatedButton.icon(
            onPressed: _yenile,
            icon: const Icon(Icons.refresh, size: 16),
            label: const Text('Tekrar Dene'),
            style: ElevatedButton.styleFrom(
              backgroundColor: const Color(0xFF00C853),
              foregroundColor: Colors.white,
            ),
          ),
        ]),
      ),
    );
  }

  Widget _haberKart(BuildContext context, _HaberItem h) {
    final renk = h.kaynakRenk;
    return InkWell(
      onTap: () => _ac(context, h),
      borderRadius: BorderRadius.circular(12),
      child: Container(
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(12),
          border: Border(left: BorderSide(color: renk, width: 3)),
          boxShadow: [BoxShadow(
            color: Colors.black.withValues(alpha: 0.05),
            blurRadius: 4, offset: const Offset(0, 2),
          )],
        ),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(
            h.baslik,
            style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600, height: 1.35),
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
          ),
          if (h.ozet.isNotEmpty) ...[
            const SizedBox(height: 5),
            Text(
              h.ozet,
              style: TextStyle(fontSize: 12, color: Colors.grey.shade700, height: 1.4),
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
            ),
          ],
          const SizedBox(height: 7),
          Row(children: [
            Icon(Icons.newspaper, size: 12, color: renk),
            const SizedBox(width: 4),
            Text(
              h.kaynak,
              style: TextStyle(fontSize: 11, color: renk, fontWeight: FontWeight.w500),
            ),
            const SizedBox(width: 8),
            Text('·', style: TextStyle(fontSize: 11, color: Colors.grey.shade400)),
            const SizedBox(width: 8),
            const Icon(Icons.access_time, size: 11, color: Colors.grey),
            const SizedBox(width: 3),
            Expanded(
              child: Text(
                h.tarih,
                style: const TextStyle(fontSize: 11, color: Colors.grey),
                overflow: TextOverflow.ellipsis,
              ),
            ),
            const Icon(Icons.open_in_new, size: 13, color: Colors.grey),
          ]),
        ]),
      ),
    );
  }
}
