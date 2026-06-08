import 'package:flutter/material.dart';
import 'package:pay/utils/paynotu_color.dart';
import 'package:pay/widgets/panel_halk.dart';
import 'package:pay/widgets/finansal_panel.dart';

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
        _HisseBasligi(
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
              const _PayNotuPanel(),
              HalkPanel(symbol: widget.symbol),
            ],
          ),
        ),
      ],
    );
  }
}


// ─────────────────────────────────────────────────────────────────────────────
// HİSSE BAŞLIĞI — detay_screen.dart header ile birebir
// ─────────────────────────────────────────────────────────────────────────────

class _HisseBasligi extends StatelessWidget {
  final Map<String, dynamic> hisseData;
  final String symbol;

  const _HisseBasligi({required this.hisseData, required this.symbol});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final logo = (hisseData['logo'] ?? '') as String;
    final name = (hisseData['name'] ?? '') as String;
    final industry = (hisseData['industry'] ?? '') as String;
    final sector = (hisseData['sector'] ?? '') as String;

    Widget logoWidget() {
      final renk = sektorRenk(sector);
      final fallback = Container(
        width: 72,
        height: 72,
        decoration: BoxDecoration(
          color: renk.withValues(alpha: 0.15),
          borderRadius: BorderRadius.circular(12),
        ),
        child: Center(
          child: Text(
            symbol.length >= 2 ? symbol.substring(0, 2) : symbol,
            style: TextStyle(
                fontWeight: FontWeight.bold, fontSize: 20, color: renk),
          ),
        ),
      );
      if (logo.isEmpty) return fallback;
      return ClipRRect(
        borderRadius: BorderRadius.circular(12),
        child: Image.network(
          logo,
          width: 72,
          height: 72,
          fit: BoxFit.cover,
          errorBuilder: (_, _, _) => fallback,
        ),
      );
    }

    return Container(
      color: cs.surface,
      padding: const EdgeInsets.all(16),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          logoWidget(),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(name,
                    style: const TextStyle(
                        fontSize: 16, fontWeight: FontWeight.bold)),
                const SizedBox(height: 2),
                Text(symbol,
                    style: TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w600,
                        color: cs.onSurfaceVariant)),
                const SizedBox(height: 2),
                Text(industry,
                    style: TextStyle(
                        fontSize: 12, color: cs.primary)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

// ═════════════════════════════════════════════════════════════════════════════
// PANEL 2: PAYNOTU ANALİZİ
// ═════════════════════════════════════════════════════════════════════════════

class _PayNotuPanel extends StatelessWidget {
  const _PayNotuPanel();

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;

    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          GridView.count(
            crossAxisCount: 2,
            crossAxisSpacing: 10,
            mainAxisSpacing: 10,
            childAspectRatio: 1.25,
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            children: [
              _PnKart(
                baslik: 'Genel Skor',
                deger: '72',
                degerAlt: '/ 100',
                altMetin: 'İyi seviye',
                barOran: 0.72,
                barRenk: cs.primary,
              ),
              _PnKart(
                baslik: 'Momentum',
                deger: 'Güçlü',
                degerRenk: cs.primary,
                altMetin: 'Son 90 günde +12.4%',
              ),
              _PnKart(
                baslik: 'Likidite Skoru',
                deger: '4.2',
                degerAlt: '/ 5',
                altMetin: 'Yüksek işlem hacmi',
                barOran: 0.84,
                barRenk: cs.secondary,
              ),
              _PnKart(
                baslik: 'Risk Seviyesi',
                deger: 'Orta',
                degerRenk: cs.tertiary,
                altMetin: 'Beta: 1.24',
              ),
            ],
          ),

          const SizedBox(height: 20),

          Text(
            'MOTOR BİLEŞEN AĞIRLIKLARI',
            style: TextStyle(
              fontSize: 11,
              fontWeight: FontWeight.w500,
              letterSpacing: 0.4,
              color: cs.onSurfaceVariant,
            ),
          ),

          const SizedBox(height: 10),

          _MotorSatir(
            etiket: 'Değerleme Skoru',
            oran: 0.33,
            yuzde: '33%',
            renk: cs.secondary,
          ),
          _MotorSatir(
            etiket: 'Büyüme Faktörü',
            oran: 0.28,
            yuzde: '28%',
            renk: cs.primary,
          ),
          _MotorSatir(
            etiket: 'Finansal Sağlık',
            oran: 0.22,
            yuzde: '22%',
            renk: cs.primary,
          ),
          _MotorSatir(
            etiket: 'Momentum',
            oran: 0.10,
            yuzde: '10%',
            renk: cs.tertiary,
          ),
          _MotorSatir(
            etiket: 'Temettü Kalitesi',
            oran: 0.07,
            yuzde: '7%',
            renk: cs.error,
          ),
        ],
      ),
    );
  }
}

class _PnKart extends StatelessWidget {
  final String baslik;
  final String deger;
  final String? degerAlt;
  final Color? degerRenk;
  final String altMetin;
  final double? barOran;
  final Color? barRenk;

  const _PnKart({
    required this.baslik,
    required this.deger,
    required this.altMetin,
    this.degerAlt,
    this.degerRenk,
    this.barOran,
    this.barRenk,
  });

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: cs.surface,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(
            baslik.toUpperCase(),
            style: TextStyle(
              fontSize: 10,
              color: cs.onSurfaceVariant,
              letterSpacing: 0.4,
            ),
          ),
          Row(
            crossAxisAlignment: CrossAxisAlignment.baseline,
            textBaseline: TextBaseline.alphabetic,
            children: [
              Text(
                deger,
                style: TextStyle(
                  fontSize: 18,
                  fontWeight: FontWeight.w500,
                  color: degerRenk ?? cs.onSurface,
                ),
              ),
              if (degerAlt != null) ...[
                const SizedBox(width: 3),
                Text(
                  degerAlt!,
                  style: TextStyle(
                    fontSize: 12,
                    color: cs.onSurfaceVariant,
                  ),
                ),
              ],
            ],
          ),
          Text(
            altMetin,
            style: TextStyle(
              fontSize: 11,
              color: cs.onSurfaceVariant,
            ),
          ),
          if (barOran != null) ...[
            const SizedBox(height: 2),
            ClipRRect(
              borderRadius: BorderRadius.circular(99),
              child: LinearProgressIndicator(
                value: barOran!,
                minHeight: 4,
                backgroundColor: cs.surfaceContainerHighest,
                valueColor: AlwaysStoppedAnimation<Color>(
                  barRenk ?? cs.primary,
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _MotorSatir extends StatelessWidget {
  final String etiket;
  final double oran;
  final String yuzde;
  final Color renk;

  const _MotorSatir({
    required this.etiket,
    required this.oran,
    required this.yuzde,
    required this.renk,
  });

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;

    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Row(
        children: [
          SizedBox(
            width: 120,
            child: Text(
              etiket,
              style: TextStyle(
                fontSize: 12,
                color: cs.onSurfaceVariant,
              ),
            ),
          ),
          Expanded(
            child: ClipRRect(
              borderRadius: BorderRadius.circular(99),
              child: LinearProgressIndicator(
                value: oran,
                minHeight: 6,
                backgroundColor: cs.surface,
                valueColor: AlwaysStoppedAnimation<Color>(renk),
              ),
            ),
          ),
          const SizedBox(width: 8),
          SizedBox(
            width: 32,
            child: Text(
              yuzde,
              style: TextStyle(
                fontSize: 11,
                fontWeight: FontWeight.w500,
                color: cs.onSurface,
              ),
              textAlign: TextAlign.right,
            ),
          ),
        ],
      ),
    );
  }
}