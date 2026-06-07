import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:intl/intl.dart';
import 'package:http/http.dart' as http;
import 'dart:convert';
import 'dart:async';
import 'package:url_launcher/url_launcher.dart';
import 'package:pay/screens/soz_hakki_screen.dart';
import 'package:pay/screens/etiket_filtre_screen.dart';
import 'package:pay/screens/sohbet_tab.dart';
import 'package:pay/utils/paynotu_color.dart';
import 'package:pay/theme/paynotu_colors.dart';
import 'package:pay/widgets/analiz_tab.dart';

const Map<String, String> sektorCeviri = {
  'Financial Services':      'Finansal Hizmetler',
  'Industrials':             'Sanayi',
  'Basic Materials':         'Temel Malzemeler',
  'Consumer Cyclical':       'Döngüsel Tüketim',
  'Consumer Defensive':      'Savunmacı Tüketim',
  'Technology':              'Teknoloji',
  'Energy':                  'Enerji',
  'Healthcare':              'Sağlık',
  'Real Estate':             'Gayrimenkul',
  'Communication Services':  'İletişim Hizmetleri',
  'Utilities':               'Kamu Hizmetleri',
  'Unknown':                 'Bilinmiyor',
};

@immutable
class HisseDetayModel {
  final String symbol;
  final String? sozcuYorumu;
  final String? sozcuAdi;
  final DateTime? sozcuTarihi;
  final String? aiAnaliz;
  final DateTime? aiAnalizTarihi;

  const HisseDetayModel({
    required this.symbol,
    this.sozcuYorumu,
    this.sozcuAdi,
    this.sozcuTarihi,
    this.aiAnaliz,
    this.aiAnalizTarihi,
  });

  HisseDetayModel copyWith({
    String? symbol,
    String? sozcuYorumu,
    String? sozcuAdi,
    DateTime? sozcuTarihi,
    String? aiAnaliz,
    DateTime? aiAnalizTarihi,
  }) {
    return HisseDetayModel(
      symbol: symbol ?? this.symbol,
      sozcuYorumu: sozcuYorumu ?? this.sozcuYorumu,
      sozcuAdi: sozcuAdi ?? this.sozcuAdi,
      sozcuTarihi: sozcuTarihi ?? this.sozcuTarihi,
      aiAnaliz: aiAnaliz ?? this.aiAnaliz,
      aiAnalizTarihi: aiAnalizTarihi ?? this.aiAnalizTarihi,
    );
  }

  factory HisseDetayModel.fromFirestore(DocumentSnapshot doc) {
    final data = doc.data() as Map<String, dynamic>? ?? {};
    return HisseDetayModel(
      symbol: doc.id,
      sozcuYorumu: data['sozcü_yorumu'] as String?,
      sozcuAdi: data['sozcü_adi'] as String?,
      sozcuTarihi: (data['sozcü_tarihi'] as Timestamp?)?.toDate(),
      aiAnaliz: data['ai_analiz'] as String?,
      aiAnalizTarihi: (data['ai_analiz_tarihi'] as Timestamp?)?.toDate(),
    );
  }
}

class DetayScreen extends StatefulWidget {
  final Map<String, dynamic> hisseData;
  const DetayScreen({super.key, required this.hisseData});

  @override
  State<DetayScreen> createState() => _DetayScreenState();
}

class _DetayScreenState extends State<DetayScreen>
    with SingleTickerProviderStateMixin {
  Map<String, dynamic>? _yahooData;
  bool _yahooYukleniyor = true;

  Map<String, dynamic>? _quoteData;
  bool _quoteYukleniyor = false;
  Timer? _quoteTimer;

  static String get _apiBaseUrl {
    const envUrl = String.fromEnvironment('PAYNOTU_API_URL', defaultValue: '');
    if (envUrl.isNotEmpty) return envUrl;
    if (!kIsWeb && defaultTargetPlatform == TargetPlatform.android) {
      return 'http://10.0.2.2:8000';
    }
    return 'http://127.0.0.1:8000';
  }

  late final TabController _tabController;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 3, vsync: this);

    _yahooVeriCek();

    _quoteCek();
    _quoteTimer = Timer.periodic(
      const Duration(seconds: 60),
      (_) => _quoteCek(),
    );
  }

  @override
  void dispose() {
    _quoteTimer?.cancel();
    _tabController.dispose();
    super.dispose();
  }

  String get _symbol => widget.hisseData['symbol'] ?? '';
  String get _name => widget.hisseData['name'] ?? '';
  String get _logo => widget.hisseData['logo'] ?? '';
  String get _industry => widget.hisseData['industry'] ?? '';
  String get _sector => widget.hisseData['sector'] ?? '';
  String get _pazar => widget.hisseData['pazar'] ?? '';
  List get _endeksler => widget.hisseData['endeksler'] ?? [];
  String get _summaryTr => widget.hisseData['summary_tr'] ?? '';

  Future<void> _yahooVeriCek() async {
    try {
      final url =
          'https://query1.finance.yahoo.com/v10/finance/quoteSummary/$_symbol.IS?modules=assetProfile';
      final response = await http.get(Uri.parse(url), headers: {
        'User-Agent': 'Mozilla/5.0',
        'Accept': 'application/json',
      }).timeout(const Duration(seconds: 5));

      if (response.statusCode == 200) {
        final json = jsonDecode(response.body);
        final profile = json['quoteSummary']['result']?[0]?['assetProfile'];
        if (profile != null && mounted) {
          setState(() {
            _yahooData = profile;
            _yahooYukleniyor = false;
          });
          return;
        }
      }
    } catch (_) {}

    if (mounted) {
      setState(() {
        _yahooData = {'website': widget.hisseData['website']};
        _yahooYukleniyor = false;
      });
    }
  }

  Future<void> _quoteCek() async {
    if (_symbol.isEmpty || _quoteYukleniyor) return;

    setState(() {
      _quoteYukleniyor = true;
    });

    try {
      final uri = Uri.parse('$_apiBaseUrl/quote/$_symbol');

      final response = await http.get(
        uri,
        headers: const {
          'Accept': 'application/json',
        },
      ).timeout(const Duration(seconds: 8));

      if (response.statusCode == 200) {
        final decoded = jsonDecode(response.body);

        if (decoded is Map<String, dynamic> && mounted) {
          setState(() {
            _quoteData = decoded;
          });
        }
      } else {
        debugPrint(
          '[quote] $_symbol HTTP ${response.statusCode}: ${response.body}',
        );
      }
    } catch (e) {
      debugPrint('[quote] $_symbol fiyat alınamadı: $e');
    } finally {
      if (mounted) {
        setState(() {
          _quoteYukleniyor = false;
        });
      }
    }
  }

  Map<String, dynamic> _hisseDataWithQuote(Map<String, dynamic> base) {
    return {
      ...base,
      if (_quoteData != null) ..._quoteData!,
    };
  }



  Widget _etiketChip(String label, Color color, VoidCallback onTap) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        constraints: const BoxConstraints(maxWidth: 280),
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
        decoration: BoxDecoration(
          color: color.withValues(alpha: 0.1),
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: color.withValues(alpha: 0.3)),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Flexible(
              child: Text(
                label,
                maxLines: 1,
                softWrap: false,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                    fontSize: 12, color: color, fontWeight: FontWeight.w500),
              ),
            ),
            const SizedBox(width: 4),
            Icon(Icons.chevron_right, size: 14, color: color.withValues(alpha: 0.7)),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Theme.of(context).scaffoldBackgroundColor,
      appBar: AppBar(
        backgroundColor: Theme.of(context).colorScheme.primary,
        elevation: 0,
        centerTitle: true,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back, color: Colors.white),
          onPressed: () => Navigator.pop(context),
        ),
        title: const Text(
          'PayNotu',
          style: TextStyle(
            color: Colors.white,
            fontWeight: FontWeight.w800,
            fontSize: 22,
            letterSpacing: -0.2,
          ),
        ),
        bottom: TabBar(
          controller: _tabController,
          indicatorColor: Colors.white,
          indicatorWeight: 3,
          labelColor: Colors.white,
          unselectedLabelColor: Colors.white70,
          labelStyle:
              const TextStyle(fontWeight: FontWeight.bold, fontSize: 13),
          tabs: const [
            Tab(text: 'Genel'),
            Tab(text: 'Analiz'),
            Tab(text: 'Sohbet'),
          ],
        ),
      ),
      body: TabBarView(
        controller: _tabController,
        children: [
          // ── Sekme 0: Genel ──────────────────────────────────────
          StreamBuilder<DocumentSnapshot>(
        stream: FirebaseFirestore.instance
            .collection('hisseler')
            .doc(_symbol)
            .snapshots(),
        builder: (context, hisseSnap) {
          final firestoreData =
              hisseSnap.data?.data() as Map<String, dynamic>? ?? widget.hisseData;
          final hisseData = _hisseDataWithQuote(firestoreData);
          final detay = hisseSnap.hasData && hisseSnap.data!.exists
              ? HisseDetayModel.fromFirestore(hisseSnap.data!)
              : HisseDetayModel(symbol: _symbol);
          final ortalama = (hisseData['ortalamaPuan'] ?? 0.0).toDouble();

          return SingleChildScrollView(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // ── HEADER ──────────────────────────────────────
                Container(
                  color: Theme.of(context).colorScheme.surface,
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          ClipRRect(
                            borderRadius: BorderRadius.circular(12),
                            child: _logo.isNotEmpty
                                ? Image.network(
                                    _logo,
                                    width: 72,
                                    height: 72,
                                    fit: BoxFit.cover,
                                    errorBuilder: (_, _, _) => _logoFallback(),
                                  )
                                : _logoFallback(),
                          ),
                          const SizedBox(width: 14),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(_name,
                                    style: const TextStyle(
                                        fontSize: 16,
                                        fontWeight: FontWeight.bold)),
                                const SizedBox(height: 2),
                                Text(_industry,
                                    style: TextStyle(
                                        fontSize: 12,
                                        color: Theme.of(context).colorScheme.primary)),
                              ],
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 16),
                      IntrinsicHeight(
                        child: Row(
                          mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                          children: [
                            Column(
                              children: [
                                Row(
                                  children: [
                                    Text(
                                      ortalama.toStringAsFixed(1),
                                      style: const TextStyle(
                                          fontSize: 22,
                                          fontWeight: FontWeight.bold),
                                    ),
                                    const Icon(Icons.star,
                                        size: 18, color: Color(0xFFFFC107)),
                                  ],
                                ),
                                Text('Halk Skoru',
                                    style: TextStyle(
                                        fontSize: 11,
                                        color: Theme.of(context).colorScheme.onSurfaceVariant)),
                              ],
                            ),
                            VerticalDivider(
                                thickness: 1,
                                color: Theme.of(context).colorScheme.onSurfaceVariant),
                            Column(
                              mainAxisAlignment: MainAxisAlignment.center,
                              children: [
                                Text(
                                  (hisseData['finansal_skor'] as num?) == null
                                      ? '—'
                                      : (hisseData['finansal_skor'] as num)
                                          .toDouble()
                                          .toStringAsFixed(2),
                                  style: const TextStyle(
                                      fontSize: 22,
                                      fontWeight: FontWeight.bold),
                                ),
                                if ((hisseData['finansal_skor_label'] as String?)
                                        ?.isNotEmpty ==
                                    true)
                                  Text(
                                    hisseData['finansal_skor_label'] as String,
                                    style: TextStyle(
                                        fontSize: 10,
                                        color: Theme.of(context)
                                            .colorScheme
                                            .primary),
                                  ),
                                Text('Finansal Skor',
                                    style: TextStyle(
                                        fontSize: 11,
                                        color: Theme.of(context)
                                            .colorScheme
                                            .onSurfaceVariant)),
                              ],
                            ),
                            VerticalDivider(
                                thickness: 1,
                                color: Theme.of(context).colorScheme.onSurfaceVariant),
                            Column(
                              children: [
                                Builder(builder: (context) {
                                  final rawPn = hisseData['paynotu_skoru'];
                                  final pn = rawPn == null
                                      ? null
                                      : (rawPn as num).toDouble();
                                  return Container(
                                    padding: const EdgeInsets.symmetric(
                                        horizontal: 10, vertical: 4),
                                    decoration: BoxDecoration(
                                      color: PayNotuColors.forScore(pn),
                                      borderRadius: BorderRadius.circular(6),
                                    ),
                                    child: Text(
                                      pn == null ? '—' : pn.toStringAsFixed(2),
                                      style: TextStyle(
                                          color: pn == null
                                              ? Colors.grey.shade500
                                              : Colors.white,
                                          fontWeight: FontWeight.bold,
                                          fontSize: 18),
                                    ),
                                  );
                                }),
                                Text(
                                  hisseData['paynotu_skoru'] == null
                                      ? 'Henüz skorlanmadı'
                                      : 'PayNotu',
                                  style: TextStyle(
                                      fontSize: 11,
                                      color: Theme.of(context).colorScheme.onSurfaceVariant)),
                              ],
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),

                const SizedBox(height: 8),

                // ── SEMBOL ÇUBUĞU ────────────────────────────────
                Container(
                  color: Theme.of(context).colorScheme.surface,
                  padding: const EdgeInsets.symmetric(vertical: 4),
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                    children: [
                      _sembolBtn(context,
                          ikon: Icons.info_outline,
                          etiket: 'Hakkında',
                          onTap: () => _infoPopup(context, 'Bu Hisse Hakkında',
                              _hakkindaIcerik(context))),
                      _sembolBtn(context,
                          ikon: Icons.label_outline,
                          etiket: 'Etiketler',
                          onTap: () => _infoPopup(
                              context, 'Etiketler', _etiketlerIcerik(context))),
                      _sembolBtn(context,
                          ikon: Icons.place,
                          etiket: 'Firma',
                          onTap: () => _infoPopup(context, 'Firma Desteği',
                              _firmaIcerik(context))),
                    ],
                  ),
                ),

                const SizedBox(height: 8),

                // ── EDİTÖR GÖRÜŞÜ ────────────────────────────────
                Container(
                  color: Theme.of(context).colorScheme.surface,
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(children: [
                        Icon(Icons.edit_note_outlined,
                            size: 18,
                            color: Theme.of(context).colorScheme.primary),
                        const SizedBox(width: 8),
                        const Text('Sözcü',
                            style: TextStyle(
                                fontSize: 15, fontWeight: FontWeight.bold)),
                      ]),
                      const SizedBox(height: 8),
                      if (detay.sozcuYorumu != null &&
                          detay.sozcuYorumu!.isNotEmpty) ...[
                        Text(detay.sozcuYorumu!,
                            style: TextStyle(
                                fontSize: 13,
                                color: Theme.of(context).colorScheme.onSurface,
                                height: 1.4)),
                        if (detay.sozcuAdi != null) ...[
                          const SizedBox(height: 6),
                          Text('— ${detay.sozcuAdi}',
                              style: TextStyle(
                                  fontSize: 12,
                                  color:
                                      Theme.of(context).colorScheme.primary,
                                  fontWeight: FontWeight.w500)),
                        ],
                        if (detay.sozcuTarihi != null) ...[
                          const SizedBox(height: 2),
                          Text(
                              'Güncelleme: ${DateFormat('dd.MM.yy').format(detay.sozcuTarihi!)}',
                              style: TextStyle(
                                  fontSize: 11,
                                  color: Theme.of(context)
                                      .colorScheme
                                      .onSurfaceVariant)),
                        ],
                      ] else
                        Text('Henüz sözcü görüşü eklenmedi',
                            style: TextStyle(
                                fontSize: 13,
                                color: Theme.of(context)
                                    .colorScheme
                                    .onSurfaceVariant)),
                    ],
                  ),
                ),

                const SizedBox(height: 8),

                // ── AI ANALİZİ ───────────────────────────────────
                Container(
                  color: Theme.of(context).colorScheme.surface,
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(children: [
                        Icon(Icons.auto_awesome_outlined,
                            size: 18,
                            color: Theme.of(context).colorScheme.primary),
                        const SizedBox(width: 8),
                        const Text('AI Analizi',
                            style: TextStyle(
                                fontSize: 15, fontWeight: FontWeight.bold)),
                      ]),
                      const SizedBox(height: 8),
                      if (detay.aiAnaliz != null &&
                          detay.aiAnaliz!.isNotEmpty) ...[
                        Text(detay.aiAnaliz!,
                            style: TextStyle(
                                fontSize: 13,
                                color: Theme.of(context).colorScheme.onSurface,
                                height: 1.4)),
                        if (detay.aiAnalizTarihi != null) ...[
                          const SizedBox(height: 6),
                          Text(
                              'Güncelleme: ${DateFormat('dd.MM.yy').format(detay.aiAnalizTarihi!)}',
                              style: TextStyle(
                                  fontSize: 11,
                                  color: Theme.of(context)
                                      .colorScheme
                                      .onSurfaceVariant)),
                        ],
                      ] else
                        Text('Henüz AI analizi hazırlanmadı',
                            style: TextStyle(
                                fontSize: 13,
                                color: Theme.of(context)
                                    .colorScheme
                                    .onSurfaceVariant)),
                    ],
                  ),
                ),

                const SizedBox(height: 8),

                // ── PUAN VER ────────────────────────────────────
                Container(
                  color: Theme.of(context).colorScheme.surface,
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text('Bu hisseye puan verin',
                          style: TextStyle(
                              fontSize: 16, fontWeight: FontWeight.bold)),
                      const SizedBox(height: 4),
                      Text(
                          'Düşüncelerinizi diğer ortaklarla paylaşın',
                          style: TextStyle(
                              fontSize: 12,
                              color: Theme.of(context).colorScheme.onSurfaceVariant)),
                      const SizedBox(height: 12),
                      Row(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: List.generate(5, (i) {
                          return Icon(Icons.star_border,
                              size: 36,
                              color: Theme.of(context).colorScheme.onSurfaceVariant);
                        }),
                      ),
                      const SizedBox(height: 12),
                      SizedBox(
                        width: double.infinity,
                        child: OutlinedButton(
                          onPressed: () {
                            Navigator.push(
                              context,
                              MaterialPageRoute(
                                builder: (_) => SozHakkiScreen(
                                  symbol: _symbol,
                                  hisseAdi: _name,
                                ),
                              ),
                            );
                          },
                          style: OutlinedButton.styleFrom(
                            backgroundColor: Colors.black,
                            side: const BorderSide(color: Colors.black),
                            shape: RoundedRectangleBorder(
                                borderRadius: BorderRadius.circular(8)),
                            padding:
                                const EdgeInsets.symmetric(vertical: 12),
                          ),
                          child: const Text('Söz Hakkını Kullan',
                              style: TextStyle(
                                  color: Colors.white,
                                  fontWeight: FontWeight.bold)),
                        ),
                      ),
                    ],
                  ),
                ),

              ],
            ),
          );
        },
      ),

          // ── Sekme 1: Analiz ──────────────────────────────────
          StreamBuilder<DocumentSnapshot>(
            stream: FirebaseFirestore.instance
                .collection('hisseler')
                .doc(_symbol)
                .snapshots(),
            builder: (context, hisseSnap) {
              final firestoreData =
                  hisseSnap.data?.data() as Map<String, dynamic>? ??
                      widget.hisseData;
              final hisseData = _hisseDataWithQuote(firestoreData);

              return _AnalizTab(hisseData: hisseData);
            },
          ),

          // ── Sekme 2: Sohbet ──────────────────────────────────
          SohbetTab(symbol: _symbol, hisseAdi: _name),
        ],
      ),
    );
  }

  void _infoPopup(BuildContext context, String baslik, Widget icerik) {
    showDialog(
      context: context,
      builder: (_) => Dialog(
        elevation: 8,
        shape:
            RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
        child: ConstrainedBox(
          constraints: BoxConstraints(
              maxWidth: MediaQuery.of(context).size.width * 0.85),
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(baslik,
                    style: const TextStyle(
                        fontSize: 16, fontWeight: FontWeight.bold)),
                const SizedBox(height: 12),
                icerik,
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _sembolBtn(BuildContext context,
      {required IconData ikon,
      required String etiket,
      required VoidCallback onTap}) {
    final cs = Theme.of(context).colorScheme;
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(8),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(ikon, color: cs.primary, size: 24),
            const SizedBox(height: 4),
            Text(etiket,
                style: TextStyle(fontSize: 11, color: cs.primary)),
          ],
        ),
      ),
    );
  }

  Widget _hakkindaIcerik(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    if (_summaryTr.isEmpty) {
      return Text('Özet bilgi bulunamadı.',
          style: TextStyle(fontSize: 13, color: cs.onSurfaceVariant));
    }
    return Text(_summaryTr,
        style: TextStyle(fontSize: 13, color: cs.onSurface, height: 1.4));
  }

  Widget _etiketlerIcerik(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    if (_sector.isEmpty &&
        _industry.isEmpty &&
        _pazar.isEmpty &&
        _endeksler.isEmpty) {
      return Text('Etiket bilgisi bulunamadı.',
          style: TextStyle(fontSize: 13, color: cs.onSurfaceVariant));
    }
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (_sector.isNotEmpty) ...[
          Text('Sektör',
              style: TextStyle(
                  fontSize: 12,
                  color: cs.onSurfaceVariant,
                  fontWeight: FontWeight.bold)),
          const SizedBox(height: 4),
          _etiketChip(sektorCeviri[_sector] ?? _sector, cs.primary, () {
            Navigator.pop(context);
            Navigator.push(
                context,
                MaterialPageRoute(
                    builder: (_) => EtiketFiltreScreen(
                        filtreTip: 'sector',
                        filtreValue: _sector,
                        baslik: 'Sektör',
                        renk: cs.primary)));
          }),
          const SizedBox(height: 10),
        ],
        if (_industry.isNotEmpty) ...[
          Text('Sanayi',
              style: TextStyle(
                  fontSize: 12,
                  color: cs.onSurfaceVariant,
                  fontWeight: FontWeight.bold)),
          const SizedBox(height: 4),
          _etiketChip(_industry, Colors.blue, () {
            Navigator.pop(context);
            Navigator.push(
                context,
                MaterialPageRoute(
                    builder: (_) => EtiketFiltreScreen(
                        filtreTip: 'industry',
                        filtreValue: _industry,
                        baslik: 'Sanayi',
                        renk: Colors.blue)));
          }),
          const SizedBox(height: 10),
        ],
        if (_pazar.isNotEmpty) ...[
          Text('Pazar',
              style: TextStyle(
                  fontSize: 12,
                  color: cs.onSurfaceVariant,
                  fontWeight: FontWeight.bold)),
          const SizedBox(height: 4),
          _etiketChip(_pazar, Colors.orange, () {
            Navigator.pop(context);
            Navigator.push(
                context,
                MaterialPageRoute(
                    builder: (_) => EtiketFiltreScreen(
                        filtreTip: 'pazar',
                        filtreValue: _pazar,
                        baslik: 'Pazar',
                        renk: Colors.orange)));
          }),
          const SizedBox(height: 10),
        ],
        if (_endeksler.isNotEmpty) ...[
          Text('Endeksler',
              style: TextStyle(
                  fontSize: 12,
                  color: cs.onSurfaceVariant,
                  fontWeight: FontWeight.bold)),
          const SizedBox(height: 4),
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: _endeksler
                .map((e) => _etiketChip(e.toString(), Colors.purple, () {
                      Navigator.pop(context);
                      Navigator.push(
                          context,
                          MaterialPageRoute(
                              builder: (_) => EtiketFiltreScreen(
                                  filtreTip: 'endeks',
                                  filtreValue: e.toString(),
                                  baslik: 'Endeks',
                                  renk: Colors.purple)));
                    }))
                .toList(),
          ),
        ],
      ],
    );
  }

  Widget _firmaIcerik(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    if (_yahooYukleniyor) {
      return Center(child: CircularProgressIndicator(color: cs.primary));
    }
    if (_yahooData == null) {
      return Text('Firma iletişim bilgisi bulunamadı.',
          style: TextStyle(color: cs.onSurfaceVariant));
    }
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(_name,
            style:
                const TextStyle(fontSize: 15, fontWeight: FontWeight.bold)),
        const SizedBox(height: 8),
        if (_yahooData!['address1'] != null)
          Text(
            [
              _yahooData!['address1'],
              _yahooData!['city'],
              _yahooData!['zip'],
              'Türkiye',
            ].where((e) => e != null).join(', '),
            style: TextStyle(fontSize: 13, color: cs.onSurface),
          ),
        if (_yahooData!['phone'] != null) ...[
          const SizedBox(height: 6),
          Text(_yahooData!['phone'],
              style: TextStyle(fontSize: 13, color: cs.onSurface)),
        ],
        if (_yahooData!['website'] != null) ...[
          const SizedBox(height: 6),
          GestureDetector(
            onTap: () => launchUrl(Uri.parse(_yahooData!['website']),
                mode: LaunchMode.externalApplication),
            child: Text(_yahooData!['website'],
                style: TextStyle(
                    fontSize: 13,
                    color: cs.primary,
                    decoration: TextDecoration.underline)),
          ),
        ],
        if (_yahooData!['fullTimeEmployees'] != null) ...[
          const SizedBox(height: 12),
          Row(children: [
            Text('Tam Zamanlı Çalışanlar: ',
                style: TextStyle(fontSize: 13, color: cs.onSurfaceVariant)),
            Text(
              NumberFormat('#,###').format(_yahooData!['fullTimeEmployees']),
              style:
                  const TextStyle(fontSize: 13, fontWeight: FontWeight.bold),
            ),
          ]),
        ],
      ],
    );
  }

  Widget _logoFallback() {
    final renk = sektorRenk(_sector);
    return Container(
      width: 72,
      height: 72,
      decoration: BoxDecoration(
        color: renk.withValues(alpha: 0.15),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Center(
        child: Text(
          _symbol.length >= 2 ? _symbol.substring(0, 2) : _symbol,
          style: TextStyle(
              fontWeight: FontWeight.bold,
              fontSize: 20,
              color: renk),
        ),
      ),
    );
  }
}

// ── TÜM YORUMLAR SAYFASI ────────────────────────────────────────
class TumYorumlarScreen extends StatelessWidget {
  final String symbol;
  final String hisseAdi;
  const TumYorumlarScreen(
      {super.key, required this.symbol, required this.hisseAdi});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Theme.of(context).scaffoldBackgroundColor,
      appBar: AppBar(
        backgroundColor: Theme.of(context).colorScheme.primary,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back, color: Colors.white),
          onPressed: () => Navigator.pop(context),
        ),
        title: const Text('Söz Hakkı Alanlar',
            style:
                TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
      ),
      body: StreamBuilder<QuerySnapshot>(
        stream: FirebaseFirestore.instance
            .collection('hisseler')
            .doc(symbol)
            .collection('yorumlar')
            .orderBy('tarih', descending: true)
            .snapshots(),
        builder: (context, snap) {
          final yorumlar = snap.data?.docs ?? [];

          if (yorumlar.isEmpty) {
            return Center(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Icon(Icons.chat_bubble_outline,
                      size: 64,
                      color: Theme.of(context).colorScheme.onSurfaceVariant),
                  const SizedBox(height: 12),
                  Text('Henüz yorum yapılmamış.',
                      style: TextStyle(
                          color: Theme.of(context).colorScheme.onSurfaceVariant,
                          fontSize: 15)),
                ],
              ),
            );
          }

          return ListView.builder(
            padding: const EdgeInsets.all(12),
            itemCount: yorumlar.length,
            itemBuilder: (context, index) {
              final doc = yorumlar[index];
              final y = doc.data() as Map<String, dynamic>;
              final puan = (y['puan'] as int?) ?? 0;
              final isim = y['displayName'] ?? 'Anonim';
              final yorum = y['yorum'] ?? '';
              final position = y['position'] as String?;
              final tarih = y['tarih'] != null
                  ? DateFormat('dd.MM.yyyy')
                      .format((y['tarih'] as Timestamp).toDate())
                  : '';
              final faydaliOy = (y['faydali_oy'] ?? 0) as int;
              final faydaliOlmayanOy = (y['faydali_olmayan_oy'] ?? 0) as int;
              final oylayanlar =
                  List<String>.from(y['oylayan_kullanicilar'] ?? []);
              final mevcutUid =
                  FirebaseAuth.instance.currentUser?.uid ?? '';
              final zatenOyVerdi = oylayanlar.contains(mevcutUid);
              final maviTik = y['yazarin_mavi_tik'] == true;

              return Container(
                margin: const EdgeInsets.only(bottom: 8),
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: Theme.of(context).colorScheme.surface,
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        CircleAvatar(
                          radius: 18,
                          backgroundColor:
                              Theme.of(context).colorScheme.primary,
                          child: Text(
                            isim.isNotEmpty ? isim[0].toUpperCase() : 'A',
                            style: const TextStyle(
                                color: Colors.white,
                                fontWeight: FontWeight.bold),
                          ),
                        ),
                        const SizedBox(width: 10),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Row(
                                children: [
                                  Text(isim,
                                      style: const TextStyle(
                                          fontWeight: FontWeight.bold,
                                          fontSize: 13)),
                                  if (maviTik) ...[
                                    const SizedBox(width: 4),
                                    const Icon(Icons.verified,
                                        size: 14, color: Colors.blue),
                                  ],
                                  if (position != null) ...[
                                    const SizedBox(width: 6),
                                    Container(
                                      padding: const EdgeInsets.symmetric(
                                          horizontal: 6, vertical: 2),
                                      decoration: BoxDecoration(
                                        color: position == 'portfoy'
                                            ? Theme.of(context)
                                                .colorScheme
                                                .primary
                                                .withValues(alpha: 0.1)
                                            : position == 'cikti'
                                                ? Colors.red
                                                    .withValues(alpha: 0.1)
                                                : Colors.blue
                                                    .withValues(alpha: 0.1),
                                        borderRadius:
                                            BorderRadius.circular(4),
                                      ),
                                      child: Text(
                                        position == 'portfoy'
                                            ? 'Portföyde'
                                            : position == 'cikti'
                                                ? 'Çıktı'
                                                : 'Takipte',
                                        style: TextStyle(
                                          fontSize: 10,
                                          color: position == 'portfoy'
                                              ? Theme.of(context)
                                                  .colorScheme
                                                  .primary
                                              : position == 'cikti'
                                                  ? Colors.red
                                                  : Colors.blue,
                                          fontWeight: FontWeight.bold,
                                        ),
                                      ),
                                    ),
                                  ],
                                ],
                              ),
                              Row(
                                children: [
                                  ...List.generate(
                                      5,
                                      (i) => Icon(
                                            i < puan
                                                ? Icons.star
                                                : Icons.star_border,
                                            size: 13,
                                            color: const Color(0xFFFFC107),
                                          )),
                                  const SizedBox(width: 6),
                                  Text(tarih,
                                      style: TextStyle(
                                          fontSize: 11,
                                          color: Theme.of(context).colorScheme.onSurfaceVariant)),
                                ],
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                    if (yorum.isNotEmpty) ...[
                      const SizedBox(height: 8),
                      Text(yorum,
                          style: TextStyle(
                              fontSize: 13,
                              color: Theme.of(context).colorScheme.onSurface)),
                    ],
                    const SizedBox(height: 8),
                    Row(
                      children: [
                        Text('Faydalı oldu mu?',
                            style: TextStyle(
                                fontSize: 12,
                                color: Theme.of(context).colorScheme.onSurfaceVariant)),
                        const Spacer(),
                        OutlinedButton.icon(
                          onPressed: zatenOyVerdi
                              ? null
                              : () async {
                                  if (mevcutUid.isEmpty) return;
                                  await FirebaseFirestore.instance
                                      .collection('hisseler')
                                      .doc(symbol)
                                      .collection('yorumlar')
                                      .doc(doc.id)
                                      .update({
                                    'faydali_oy': FieldValue.increment(1),
                                    'oylayan_kullanicilar':
                                        FieldValue.arrayUnion([mevcutUid]),
                                  });
                                },
                          icon: Icon(
                              zatenOyVerdi
                                  ? Icons.thumb_up
                                  : Icons.thumb_up_outlined,
                              size: 14),
                          label: Text('$faydaliOy',
                              style: const TextStyle(fontSize: 12)),
                          style: OutlinedButton.styleFrom(
                            padding: const EdgeInsets.symmetric(
                                horizontal: 10, vertical: 4),
                            minimumSize: Size.zero,
                            tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                          ),
                        ),
                        const SizedBox(width: 8),
                        OutlinedButton.icon(
                          onPressed: zatenOyVerdi
                              ? null
                              : () async {
                                  if (mevcutUid.isEmpty) return;
                                  await FirebaseFirestore.instance
                                      .collection('hisseler')
                                      .doc(symbol)
                                      .collection('yorumlar')
                                      .doc(doc.id)
                                      .update({
                                    'faydali_olmayan_oy':
                                        FieldValue.increment(1),
                                    'oylayan_kullanicilar':
                                        FieldValue.arrayUnion([mevcutUid]),
                                  });
                                },
                          icon: Icon(
                              zatenOyVerdi
                                  ? Icons.thumb_down
                                  : Icons.thumb_down_outlined,
                              size: 14),
                          label: Text('$faydaliOlmayanOy',
                              style: const TextStyle(fontSize: 12)),
                          style: OutlinedButton.styleFrom(
                            padding: const EdgeInsets.symmetric(
                                horizontal: 10, vertical: 4),
                            minimumSize: Size.zero,
                            tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              );
            },
          );
        },
      ),
    );
  }
}

// ── ANALİZ SEKMESİ (iç sekmeler) ────────────────────────────────
class _AnalizTab extends StatelessWidget {
  final Map<String, dynamic> hisseData;
  const _AnalizTab({required this.hisseData});

  @override
  Widget build(BuildContext context) {
    return AnalizTab(
      hisseData: hisseData,
      symbol: (hisseData['symbol'] as String?) ?? '',
    );
  }
}

class _SikayetSheet extends StatefulWidget {
  const _SikayetSheet({
    required this.yorumcuUid,
    required this.sikayetEdenUid,
    required this.hisseSymbol,
    required this.onBasari,
  });

  final String yorumcuUid;
  final String sikayetEdenUid;
  final String hisseSymbol;
  final VoidCallback onBasari;

  @override
  State<_SikayetSheet> createState() => _SikayetSheetState();
}

class _SikayetSheetState extends State<_SikayetSheet> {
  static const _sebepler = <String, String>{
    '🚫 Küfür / Hakaret': 'Küfür / Hakaret',
    '⚠️ Yanıltıcı Bilgi': 'Yanıltıcı Bilgi',
    '🔁 Spam': 'Spam',
    '📝 Diğer': 'Diğer',
  };

  String? _secilen;
  final _aciklamaCtrl = TextEditingController();
  bool _gonderiliyor = false;

  @override
  void dispose() {
    _aciklamaCtrl.dispose();
    super.dispose();
  }

  Future<void> _gonder() async {
    if (_secilen == null) return;
    setState(() => _gonderiliyor = true);
    try {
      await FirebaseFirestore.instance.collection('raporlar').add({
        'yorumcu_uid': widget.yorumcuUid,
        'sikayet_eden_uid': widget.sikayetEdenUid,
        'hisse_symbol': widget.hisseSymbol,
        'sebep': _sebepler[_secilen]!,
        'aciklama':
            _secilen == '📝 Diğer' ? _aciklamaCtrl.text.trim() : '',
        'tarih': FieldValue.serverTimestamp(),
        'durum': 'beklemede',
        'incelendi': false,
      });
      if (mounted) Navigator.pop(context);
      widget.onBasari();
    } catch (_) {
      if (mounted) setState(() => _gonderiliyor = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.only(
        bottom: MediaQuery.of(context).viewInsets.bottom + 16,
        left: 16,
        right: 16,
        top: 20,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('Şikayet Sebebi',
              style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
          const SizedBox(height: 8),
          ..._sebepler.keys.map((label) => RadioListTile<String>(
                value: label,
                // ignore: deprecated_member_use
                groupValue: _secilen,
                dense: true,
                contentPadding: EdgeInsets.zero,
                title: Text(label, style: const TextStyle(fontSize: 14)),
                // ignore: deprecated_member_use
                onChanged: (v) => setState(() => _secilen = v),
              )),
          if (_secilen == '📝 Diğer') ...[
            const SizedBox(height: 8),
            TextField(
              controller: _aciklamaCtrl,
              maxLines: 3,
              decoration: const InputDecoration(
                hintText: 'Açıklamanızı yazın...',
                border: OutlineInputBorder(),
                contentPadding:
                    EdgeInsets.symmetric(horizontal: 12, vertical: 10),
              ),
            ),
          ],
          const SizedBox(height: 16),
          SizedBox(
            width: double.infinity,
            child: ElevatedButton(
              onPressed: _secilen == null || _gonderiliyor ? null : _gonder,
              style: ElevatedButton.styleFrom(
                backgroundColor: Theme.of(context).colorScheme.primary,
                foregroundColor: Colors.white,
              ),
              child: _gonderiliyor
                  ? const SizedBox(
                      height: 18,
                      width: 18,
                      child: CircularProgressIndicator(
                          strokeWidth: 2, color: Colors.white),
                    )
                  : const Text('Gönder'),
            ),
          ),
        ],
      ),
    );
  }
}
