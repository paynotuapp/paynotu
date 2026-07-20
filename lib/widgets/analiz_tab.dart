import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:pay/utils/paynotu_color.dart';
import 'package:pay/widgets/panel_halk.dart';
import 'package:pay/widgets/finansal_panel.dart';
import 'package:pay/widgets/paynotu_panel.dart';

/// Analiz Sekmesi
/// ─────────────
/// Detay sayfasının "Analiz" sekmesinin içeriği. 3 alt sekmeli yapı:
///   • Finansal Analiz  → finansal_panel.dart
///   • PayNotu Analiz  → Anomali skoru, motor bileşen ağırlıkları
///   • Duygusal Analiz  → 5 yıldız dağılımı, yorum istatistikleri
class AnalizTab extends StatefulWidget {
  final Map<String, dynamic> hisseData;
  final String symbol;

  const AnalizTab({
    super.key,
    required this.hisseData,
    required this.symbol,
  });

  @override
  State<AnalizTab> createState() => _AnalizTabState();
}

class _AnalizTabState extends State<AnalizTab>
    with SingleTickerProviderStateMixin {
  late final TabController _tabController;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 3, vsync: this);
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _FiyatBolumu(
          hisseData: widget.hisseData,
          symbol: widget.symbol,
        ),
        Container(
          decoration: BoxDecoration(
            border: Border(
              bottom: BorderSide(
                color: cs.outlineVariant,
                width: 0.8,
              ),
            ),
          ),
          child: TabBar(
            controller: _tabController,
            isScrollable: false,
            labelColor: cs.primary,
            unselectedLabelColor: cs.onSurface,
            indicatorColor: cs.primary,
            indicatorWeight: 4,
            indicatorSize: TabBarIndicatorSize.tab,
            dividerColor: Colors.transparent,
            labelStyle: const TextStyle(
              fontSize: 15,
              fontWeight: FontWeight.w700,
            ),
            unselectedLabelStyle: const TextStyle(
              fontSize: 15,
              fontWeight: FontWeight.w500,
            ),
            tabs: const [
              Tab(
                child: FittedBox(
                  fit: BoxFit.scaleDown,
                  child: Text('Finansal Analiz'),
                ),
              ),
              Tab(
                child: FittedBox(
                  fit: BoxFit.scaleDown,
                  child: Text('PayNotu Analiz'),
                ),
              ),
              Tab(
                child: FittedBox(
                  fit: BoxFit.scaleDown,
                  child: Text('Duygusal Analiz'),
                ),
              ),
            ],
          ),
        ),

        Expanded(
          child: TabBarView(
            controller: _tabController,
            children: [
              FinansalPanel(hisseData: widget.hisseData),
              PayNotuPanel(hisseData: widget.hisseData),
              HalkPanel(symbol: widget.symbol),
            ],
          ),
        ),
      ],
    );
  }
}


// ─────────────────────────────────────────────────────────────────────────────
// FİYAT BÖLÜMÜ
// ─────────────────────────────────────────────────────────────────────────────

class _FiyatBolumu extends StatelessWidget {
  final Map<String, dynamic> hisseData;
  final String symbol;

  const _FiyatBolumu({required this.hisseData, required this.symbol});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final bilgi = _HisseBilgi.fromData(hisseData, symbol);
    final logo   = (hisseData['logo']   as String?) ?? '';
    final name   = (hisseData['name']   as String?) ?? symbol;
    final sector = (hisseData['sector'] as String?) ?? '';

    final renk = sektorRenk(sector);
    final fallback = Container(
      width: 40,
      height: 40,
      decoration: BoxDecoration(
        color: renk.withValues(alpha: 0.15),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Center(
        child: Text(
          symbol.length >= 2 ? symbol.substring(0, 2) : symbol,
          style: TextStyle(
              fontWeight: FontWeight.bold, fontSize: 13, color: renk),
        ),
      ),
    );

    Widget logoW = fallback;
    if (logo.isNotEmpty) {
      logoW = ClipRRect(
        borderRadius: BorderRadius.circular(8),
        child: Image.network(
          logo,
          width: 40,
          height: 40,
          fit: BoxFit.cover,
          errorBuilder: (context, error, stack) => fallback,
        ),
      );
    }

    // İkinci satır: SEMBOL  ₺9,82  -3.0% 7g
    final spans = <InlineSpan>[
      TextSpan(
        text: symbol,
        style: TextStyle(
          fontSize: 13,
          fontWeight: FontWeight.w600,
          color: cs.onSurfaceVariant,
        ),
      ),
      if (bilgi.fiyatMetni != null)
        TextSpan(
          text: '  ${bilgi.fiyatMetni}',
          style: TextStyle(
            fontSize: 13,
            fontWeight: FontWeight.w600,
            color: cs.onSurface,
          ),
        ),
      if (bilgi.degisimMetni != null)
        TextSpan(
          text: '  ${bilgi.degisimMetni}',
          style: TextStyle(
            fontSize: 12,
            fontWeight: FontWeight.w600,
            color: (bilgi.degisimPozitif ?? false)
                ? Colors.green.shade700
                : Colors.red.shade700,
          ),
        ),
    ];

    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          logoW,
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  name,
                  style: const TextStyle(
                      fontSize: 16, fontWeight: FontWeight.bold),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
                const SizedBox(height: 2),
                RichText(
                  text: TextSpan(children: spans),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

@immutable
class _HisseBilgi {
  final String isim;
  final String symbol;
  final String? fiyatMetni;
  final String? hedefMetni;
  final String? degisimMetni;
  final bool? degisimPozitif;

  const _HisseBilgi({
    required this.isim,
    required this.symbol,
    required this.fiyatMetni,
    required this.hedefMetni,
    required this.degisimMetni,
    required this.degisimPozitif,
  });

  bool get fiyatGorunsun =>
      fiyatMetni != null || hedefMetni != null || degisimMetni != null;

  factory _HisseBilgi.fromData(Map<String, dynamic> d, String symbol) {
    final isim = _str(d['name']) ??
        _str(d['short_name']) ??
        _str(d['shortName']) ??
        symbol;

    final fiyat = _num(d['fiyat']) ??
        _num(d['son_fiyat']) ??
        _num(d['last_price']) ??
        _num(d['price']) ??
        _num(d['close']);

    final hedef = _num(d['hedef_fiyat']) ??
        _num(d['target_price']) ??
        _num(d['analyst_target_price']);

    final gunlukDegisim = _num(d['gunluk_degisim_yuzde']);
    final haftalikDegisim = _num(d['haftalik_degisim_yuzde']) ??
        _num(d['degisim_7g_yuzde']) ??
        _num(d['weekly_change_percent']) ??
        _num(d['weekly_change']);
    final degisim = gunlukDegisim ?? haftalikDegisim;
    final degisimDonem = gunlukDegisim != null ? '1g' : '7g';

    final borsa = _str(d['borsa']) ??
        _str(d['exchange']) ??
        _borsaTahminEt(d) ??
        'BIST';

    final paraBirimi = _str(d['para_birimi']) ??
        _str(d['currency']) ??
        (borsa.toUpperCase().contains('BIST') ? 'TRY' : 'USD');

    return _HisseBilgi(
      isim: isim,
      symbol: symbol,
      fiyatMetni: _fiyatFormatla(fiyat, paraBirimi),
      hedefMetni: _fiyatFormatla(hedef, paraBirimi),
      degisimMetni: degisim == null
          ? null
          : '${degisim >= 0 ? '+' : ''}${degisim.toStringAsFixed(1)}% $degisimDonem',
      degisimPozitif: degisim == null ? null : degisim >= 0,
    );
  }

  static String? _str(dynamic v) {
    if (v is String && v.trim().isNotEmpty) return v.trim();
    return null;
  }

  static double? _num(dynamic v) {
    if (v is num) return v.toDouble();
    return null;
  }

  static String? _borsaTahminEt(Map<String, dynamic> d) {
    final endeksler = d['endeksler'];
    if (endeksler is List) {
      final hasBist = endeksler.any(
        (e) => e.toString().toUpperCase().contains('BIST'),
      );
      if (hasBist) return 'BIST';
    }
    return null;
  }

  static String? _fiyatFormatla(double? deger, String paraBirimi) {
    if (deger == null) return null;
    final sembol = switch (paraBirimi.toUpperCase()) {
      'TRY' => '₺',
      'TL' => '₺',
      'USD' => '\$',
      'EUR' => '€',
      _ => '',
    };
    final formatter = NumberFormat('#,##0.00', 'tr_TR');
    return '$sembol${formatter.format(deger)}';
  }
}

