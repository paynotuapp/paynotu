import 'package:flutter/material.dart';
import 'package:pay/models/motor_v2_models.dart';
import 'package:pay/models/scenario_models.dart';
import 'package:pay/theme/paynotu_colors.dart';

/// PayNotu Analiz Paneli — UI-1 (backend/docs/paynotu_ui1_is_emri.md).
/// ─────────────────────────────────────────────────────────────────────────
/// Analiz sekmesinin "PayNotu Analiz" alt sekmesi.
///
/// Katman B (gerçek veri — bugün mevcut):
///   • Genel Skor (paynotu_skoru = AAS), Veri Güven Skoru, Risk Kategorisi
///   • Segment listesi (`scenarios.segments`) → seçilince SegmentCard detayı
///   NOT: Line chart + flag overlay bu turda kapsam dışı — OHLCV zaman serisi
///   endpoint'i backend'de yok (bkz. backend/docs/legacy_inventory.md §5.15).
///   Segment listesi grafik olmadan chip/liste olarak sunulur; UI kırılmaz.
///
/// Katman A (motor_v2.* — gölge dönem başlamadan her zaman boş):
///   • 5 bileşen kartı + 4 bilgi kartı, veri yokken zarif gri "Yeterli veri
///     yok" durumu (spec §1 ile aynı dil). Gölge yazımı başlayınca (Faz 1)
///     bu ekran kod değişikliği gerekmeden dolar.
///
/// Madde 3: skor→etiket eşlemesi burada YAZILMAZ — motor_v2 bileşen
/// etiketleri backend'in kendi `metrics`/`explanation_tr` alanlarından gelir.
/// Madde 6/renk: yalnız `Theme.of(context).colorScheme`; `PayNotuColors`
/// (mevcut, önceden benimsenmiş) yalnız AAS tabanlı "Genel Skor" için kalır.
/// Madde 12: segment seçimi yalnız hazır veriyi değiştirir, hesap yapmaz.
class PayNotuPanel extends StatefulWidget {
  final Map<String, dynamic> hisseData;

  const PayNotuPanel({super.key, required this.hisseData});

  @override
  State<PayNotuPanel> createState() => _PayNotuPanelState();
}

class _PayNotuPanelState extends State<PayNotuPanel> {
  int? _seciliSegmentIndex;

  @override
  Widget build(BuildContext context) {
    final genel = _GenelDurum.fromFirestore(widget.hisseData);
    final motorV2 = MotorV2Result.fromFirestore(widget.hisseData['motor_v2']);
    final scenarioBundle =
        ScenarioBundle.fromFirestore(widget.hisseData['scenarios']);

    if (genel.veriYok) {
      return _BosDurum(
        mesaj: 'PayNotu analiz verisi henüz yok',
        icon: Icons.insights_outlined,
      );
    }

    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _GenelSkorSatiri(
            paynotuSkoru: genel.paynotuSkoru,
            guvenSkoru: genel.guvenSkoru,
            kategori: genel.kategori,
          ),
          const SizedBox(height: 24),

          _BolumBasligi(
            baslik: 'DAVRANIŞ NOKTALARI',
            altBaslik: scenarioBundle.isEmpty
                ? 'Bu dönemde işaretli segment yok'
                : 'Bir segmente dokunarak detayını görün',
          ),
          const SizedBox(height: 10),
          if (scenarioBundle.isEmpty)
            _BosDurum(
              mesaj: 'Segment verisi yok',
              icon: Icons.timeline_outlined,
              kompakt: true,
            )
          else ...[
            _SegmentSeridi(
              segments: scenarioBundle.segments,
              seciliIndex: _seciliSegmentIndex,
              onSecim: (i) => setState(() {
                _seciliSegmentIndex = _seciliSegmentIndex == i ? null : i;
              }),
            ),
            if (_seciliSegmentIndex != null &&
                _seciliSegmentIndex! < scenarioBundle.segments.length) ...[
              const SizedBox(height: 12),
              _SegmentDetayKarti(
                card: SegmentCard.fromSegment(
                  scenarioBundle.segments[_seciliSegmentIndex!],
                ),
              ),
            ],
          ],

          const SizedBox(height: 28),
          _BolumBasligi(
            baslik: 'DAVRANIŞ BİLEŞENLERİ',
            altBaslik: 'Motor v2 — gölge dönem tamamlanınca dolacak',
          ),
          const SizedBox(height: 10),
          _BesBilesenIzgarasi(motorV2: motorV2),

          const SizedBox(height: 28),
          _BolumBasligi(baslik: 'BİLGİ KARTLARI'),
          const SizedBox(height: 10),
          _BilgiKartiIskeleti(
            baslik: 'Tarihsel Konum',
            icon: Icons.timeline,
            dolu: motorV2 != null && !motorV2.tarihselKonum.isEmpty,
          ),
          const SizedBox(height: 10),
          _BilgiKartiIskeleti(
            baslik: 'Dayanıklılık',
            icon: Icons.shield_outlined,
            dolu: motorV2 != null && !motorV2.dayaniklilik.isEmpty,
          ),
          const SizedBox(height: 10),
          _BilgiKartiIskeleti(
            baslik: 'Davranış Evrimi',
            icon: Icons.show_chart,
            dolu: motorV2 != null && !motorV2.evrim.isEmpty,
          ),
          const SizedBox(height: 10),
          _BilgiKartiIskeleti(
            baslik: 'Hafıza',
            icon: Icons.history,
            dolu: motorV2 != null && !motorV2.hafiza.isEmpty,
          ),
        ],
      ),
    );
  }
}

// ─────────────────────────────────────────────────────────────────────────
// Serialization sınırı — hisseData'dan tek noktada okunur, widget'lara
// yalnız typed alanlar sızar (interface §1: "dynamic map sızmaz").
// ─────────────────────────────────────────────────────────────────────────

class _GenelDurum {
  final double? paynotuSkoru;
  final double? guvenSkoru;
  final String? kategori;
  final bool motorDetayBos;

  const _GenelDurum({
    required this.paynotuSkoru,
    required this.guvenSkoru,
    required this.kategori,
    required this.motorDetayBos,
  });

  bool get veriYok => paynotuSkoru == null && motorDetayBos;

  factory _GenelDurum.fromFirestore(Map<String, dynamic> hisseData) {
    final rawMotorDetay = hisseData['motor_detay'];
    final motorDetay =
        rawMotorDetay is Map<String, dynamic> ? rawMotorDetay : const {};
    final rawPaynotu = hisseData['paynotu_skoru'];
    final rawGuven = motorDetay['guven_skoru'];
    return _GenelDurum(
      paynotuSkoru: rawPaynotu is num ? rawPaynotu.toDouble() : null,
      guvenSkoru: rawGuven is num ? rawGuven.toDouble() : null,
      kategori: motorDetay['kategori'] as String?,
      motorDetayBos: motorDetay.isEmpty,
    );
  }
}

// ─────────────────────────────────────────────────────────────────────────
// Genel skor satırı — bugün mevcut AAS tabanlı veriler
// ─────────────────────────────────────────────────────────────────────────

class _GenelSkorSatiri extends StatelessWidget {
  final double? paynotuSkoru;
  final double? guvenSkoru;
  final String? kategori;

  const _GenelSkorSatiri({
    required this.paynotuSkoru,
    required this.guvenSkoru,
    required this.kategori,
  });

  String _kategoriEtiket(String? k) {
    switch (k) {
      case 'TEMIZ':
        return 'Temiz';
      case 'YENI_PD':
        return 'Yeni Anomali';
      case 'GECMIS_PD':
        return 'Geçmiş Anomali';
      case 'AKTIF_PD':
        return 'Sürekli Anomali';
      default:
        return '—';
    }
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return GridView.count(
      crossAxisCount: 2,
      crossAxisSpacing: 10,
      mainAxisSpacing: 10,
      childAspectRatio: 1.25,
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      children: [
        _StatKarti(
          baslik: 'Genel Skor',
          deger: paynotuSkoru == null ? '—' : paynotuSkoru!.toStringAsFixed(2),
          degerAlt: '/ 10',
          degerRenk: PayNotuColors.forScore(paynotuSkoru),
          altMetin: PayNotuColors.labelFor(paynotuSkoru),
          barOran: paynotuSkoru == null ? null : (paynotuSkoru! / 10.0).clamp(0.0, 1.0),
          barRenk: PayNotuColors.forScore(paynotuSkoru),
        ),
        _StatKarti(
          baslik: 'Veri Güven Skoru',
          deger: guvenSkoru == null ? '—' : '%${(guvenSkoru! * 100).toStringAsFixed(1)}',
          degerRenk: cs.onSurface,
          altMetin: 'Fiyat/hacim veri kalitesi',
          barOran: guvenSkoru,
          barRenk: cs.secondary,
        ),
        _StatKarti(
          baslik: 'Risk Kategorisi',
          deger: _kategoriEtiket(kategori),
          degerRenk: cs.onSurface,
          altMetin: 'Davranışsal anomali sınıfı',
        ),
      ],
    );
  }
}

class _StatKarti extends StatelessWidget {
  final String baslik;
  final String deger;
  final String? degerAlt;
  final Color? degerRenk;
  final String altMetin;
  final double? barOran;
  final Color? barRenk;

  const _StatKarti({
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
        color: cs.surfaceContainerLow,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(
            baslik.toUpperCase(),
            style: TextStyle(fontSize: 10, color: cs.onSurfaceVariant, letterSpacing: 0.4),
          ),
          Row(
            crossAxisAlignment: CrossAxisAlignment.baseline,
            textBaseline: TextBaseline.alphabetic,
            children: [
              Flexible(
                child: Text(
                  deger,
                  style: TextStyle(
                    fontSize: 18,
                    fontWeight: FontWeight.w500,
                    color: degerRenk ?? cs.onSurface,
                  ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              if (degerAlt != null) ...[
                const SizedBox(width: 3),
                Text(degerAlt!, style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant)),
              ],
            ],
          ),
          Text(
            altMetin,
            style: TextStyle(fontSize: 11, color: cs.onSurfaceVariant),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
          ),
          if (barOran != null) ...[
            const SizedBox(height: 2),
            ClipRRect(
              borderRadius: BorderRadius.circular(99),
              child: LinearProgressIndicator(
                value: barOran!.clamp(0.0, 1.0),
                minHeight: 4,
                backgroundColor: cs.surfaceContainerHighest,
                valueColor: AlwaysStoppedAnimation<Color>(barRenk ?? cs.primary),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

// ─────────────────────────────────────────────────────────────────────────
// Bölüm başlığı
// ─────────────────────────────────────────────────────────────────────────

class _BolumBasligi extends StatelessWidget {
  final String baslik;
  final String? altBaslik;

  const _BolumBasligi({required this.baslik, this.altBaslik});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          baslik,
          style: TextStyle(
            fontSize: 11,
            fontWeight: FontWeight.w600,
            letterSpacing: 0.4,
            color: cs.onSurfaceVariant,
          ),
        ),
        if (altBaslik != null) ...[
          const SizedBox(height: 2),
          Text(altBaslik!, style: TextStyle(fontSize: 10, color: cs.onSurfaceVariant)),
        ],
      ],
    );
  }
}

// ─────────────────────────────────────────────────────────────────────────
// Katman B — segment şeridi + detay kartı (chart YOK — bkz. dosya başı notu)
// ─────────────────────────────────────────────────────────────────────────

class _SegmentSeridi extends StatelessWidget {
  final List<ScenarioSegment> segments;
  final int? seciliIndex;
  final ValueChanged<int> onSecim;

  const _SegmentSeridi({
    required this.segments,
    required this.seciliIndex,
    required this.onSecim,
  });

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: [
        for (var i = 0; i < segments.length; i++)
          _SegmentChip(
            segment: segments[i],
            secili: seciliIndex == i,
            onTap: () => onSecim(i),
          ),
      ],
    );
  }
}

class _SegmentChip extends StatelessWidget {
  final ScenarioSegment segment;
  final bool secili;
  final VoidCallback onTap;

  const _SegmentChip({
    required this.segment,
    required this.secili,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(99),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(
          color: secili ? cs.primaryContainer : cs.surfaceContainerLow,
          borderRadius: BorderRadius.circular(99),
          border: Border.all(
            color: secili ? cs.primary : cs.outlineVariant,
            width: secili ? 1.4 : 0.8,
          ),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              Icons.flag_outlined,
              size: 14,
              color: secili ? cs.onPrimaryContainer : cs.onSurfaceVariant,
            ),
            const SizedBox(width: 6),
            Text(
              segment.title,
              style: TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w500,
                color: secili ? cs.onPrimaryContainer : cs.onSurface,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _SegmentDetayKarti extends StatelessWidget {
  final SegmentCard card;

  const _SegmentDetayKarti({required this.card});

  // Madde 3: eşik-bazlı bir güven ETİKETİ icat edilmez — classifier'ın ham
  // confidence değeri yüzde olarak, yorumsuz gösterilir (SPK dil notu, spec §9).
  String _guvenYuzdesi(double c) => 'Güven: %${(c * 100).toStringAsFixed(0)}';

  String _sureMetni() {
    final once = card.baslangicGunOnce;
    final sure = card.sureGun;
    if (once == null || sure == null) return '';
    return '$once gün önce başladı, $sure gün sürdü';
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: cs.surfaceContainerLow,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: cs.outlineVariant, width: 0.8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            card.title,
            style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: cs.onSurface),
          ),
          const SizedBox(height: 4),
          Text(
            [_guvenYuzdesi(card.confidence), _sureMetni()].where((s) => s.isNotEmpty).join(' · '),
            style: TextStyle(fontSize: 11, color: cs.onSurfaceVariant),
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(child: _GrupOlcek(etiket: 'Fiyat', oran: card.fiyatGrubu, renk: cs.secondary)),
              const SizedBox(width: 8),
              Expanded(child: _GrupOlcek(etiket: 'Hacim', oran: card.hacimGrubu, renk: cs.primary)),
            ],
          ),
          const SizedBox(height: 8),
          Row(
            children: [
              Expanded(child: _GrupOlcek(etiket: 'Volatilite', oran: card.volatiliteGrubu, renk: cs.tertiary)),
              const SizedBox(width: 8),
              Expanded(child: _GrupOlcek(etiket: 'Şekil', oran: card.sekilGrubu, renk: cs.error)),
            ],
          ),
          // 11 türetilmiş seg_* satırı — backend henüz üretmiyor (hepsi null),
          // Madde 12 uyumlu: yoksa gösterilmez, UI kırılmaz.
          if (_herhangiSegMetrigiVar()) ...[
            const SizedBox(height: 12),
            Divider(color: cs.outlineVariant, height: 1),
            const SizedBox(height: 8),
            _SegMetrikSatirlari(card: card),
          ],
        ],
      ),
    );
  }

  bool _herhangiSegMetrigiVar() =>
      card.segTotalReturn != null ||
      card.segExcessVsXu100 != null ||
      card.segSharpestDayPercent != null ||
      card.segVolumeMultiple != null ||
      card.segVolumeGini != null ||
      card.segVolVsOwnMedian != null ||
      card.segIntradayRange != null ||
      card.segRsiExtreme != null ||
      card.segUpStreakMax != null ||
      card.segPeakRetrace != null ||
      card.segPostPeakVolume != null;
}

class _GrupOlcek extends StatelessWidget {
  final String etiket;
  final double oran; // 0-1
  final Color renk;

  const _GrupOlcek({required this.etiket, required this.oran, required this.renk});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(etiket, style: TextStyle(fontSize: 10, color: cs.onSurfaceVariant)),
        const SizedBox(height: 3),
        ClipRRect(
          borderRadius: BorderRadius.circular(99),
          child: LinearProgressIndicator(
            value: oran.clamp(0.0, 1.0),
            minHeight: 5,
            backgroundColor: cs.surfaceContainerHighest,
            valueColor: AlwaysStoppedAnimation<Color>(renk),
          ),
        ),
      ],
    );
  }
}

class _SegMetrikSatirlari extends StatelessWidget {
  final SegmentCard card;
  const _SegMetrikSatirlari({required this.card});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    String pct(double? v) => v == null ? '—' : '%${(v * 100).toStringAsFixed(1)}';
    String ratio(double? v) => v == null ? '—' : '×${v.toStringAsFixed(2)}';

    final rows = <(String, String)>[
      ('Segment getirisi', pct(card.segTotalReturn)),
      ('XU100 üzeri getiri', pct(card.segExcessVsXu100)),
      if (card.segSharpestDayPercent != null)
        ('En sert gün', '${pct(card.segSharpestDayPercent)} (${card.segSharpestDayDate ?? "—"})'),
      ('Hacim katı', ratio(card.segVolumeMultiple)),
      ('Hacim Gini', ratio(card.segVolumeGini)),
      ('Kendi medyanına göre volatilite', ratio(card.segVolVsOwnMedian)),
      ('Gün içi aralık', pct(card.segIntradayRange)),
      ('RSI uç değeri', ratio(card.segRsiExtreme)),
      if (card.segUpStreakMax != null) ('En uzun ardışık yükseliş', '${card.segUpStreakMax} gün'),
      ('Zirveden geri çekilme', pct(card.segPeakRetrace)),
      ('Zirve sonrası hacim oranı', ratio(card.segPostPeakVolume)),
    ];

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (final (etiket, deger) in rows)
          if (deger != '—' && deger != '×null')
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text(etiket, style: TextStyle(fontSize: 11, color: cs.onSurfaceVariant)),
                  Text(deger, style: TextStyle(fontSize: 11, fontWeight: FontWeight.w500, color: cs.onSurface)),
                ],
              ),
            ),
      ],
    );
  }
}

// ─────────────────────────────────────────────────────────────────────────
// Katman A — 5 bileşen kartı ızgarası (motor_v2 — bugün her zaman boş)
// ─────────────────────────────────────────────────────────────────────────

class _BesBilesenIzgarasi extends StatelessWidget {
  final MotorV2Result? motorV2;

  const _BesBilesenIzgarasi({required this.motorV2});

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        for (final id in ComponentId.values) ...[
          _BilesenKarti(id: id, score: motorV2?.component(id)),
          if (id != ComponentId.values.last) const SizedBox(height: 8),
        ],
      ],
    );
  }
}

class _BilesenKarti extends StatelessWidget {
  final ComponentId id;
  final ComponentScore? score;

  const _BilesenKarti({required this.id, required this.score});

  String _confidenceEtiket(Confidence c) {
    switch (c) {
      case Confidence.dusuk:
        return 'Düşük güven';
      case Confidence.orta:
        return 'Orta güven';
      case Confidence.yuksek:
        return 'Yüksek güven';
    }
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final dolu = score != null && score!.score != null;

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: cs.surfaceContainerLow,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: cs.outlineVariant, width: 0.8),
      ),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  id.uiAdi,
                  style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: cs.onSurface),
                ),
                const SizedBox(height: 3),
                Text(
                  dolu ? score!.explanationTr : 'Yeterli veri yok',
                  style: TextStyle(fontSize: 11, color: cs.onSurfaceVariant),
                ),
              ],
            ),
          ),
          const SizedBox(width: 8),
          Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Text(
                dolu ? score!.score!.toStringAsFixed(1) : '—',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.w500, color: cs.onSurface),
              ),
              if (dolu)
                Text(
                  _confidenceEtiket(score!.confidence),
                  style: TextStyle(fontSize: 9, color: cs.onSurfaceVariant),
                ),
            ],
          ),
        ],
      ),
    );
  }
}

// ─────────────────────────────────────────────────────────────────────────
// Katman A — bilgi kartı iskeleti (4 kart, spec §8)
// ─────────────────────────────────────────────────────────────────────────

class _BilgiKartiIskeleti extends StatelessWidget {
  final String baslik;
  final IconData icon;
  final bool dolu;

  const _BilgiKartiIskeleti({required this.baslik, required this.icon, required this.dolu});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: cs.surfaceContainerLow,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: cs.outlineVariant, width: 0.8),
      ),
      child: Row(
        children: [
          Icon(icon, size: 18, color: cs.onSurfaceVariant),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              baslik,
              style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: cs.onSurface),
            ),
          ),
          Text(
            dolu ? '' : 'Yeterli veri yok',
            style: TextStyle(fontSize: 11, color: cs.onSurfaceVariant),
          ),
        ],
      ),
    );
  }
}

// ─────────────────────────────────────────────────────────────────────────
// Boş durum
// ─────────────────────────────────────────────────────────────────────────

class _BosDurum extends StatelessWidget {
  final String mesaj;
  final IconData icon;
  final bool kompakt;

  const _BosDurum({required this.mesaj, required this.icon, this.kompakt = false});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    if (kompakt) {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 12),
        child: Row(
          children: [
            Icon(icon, size: 16, color: cs.onSurfaceVariant),
            const SizedBox(width: 8),
            Text(mesaj, style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant)),
          ],
        ),
      );
    }
    return Center(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 40, 16, 24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 48, color: cs.onSurfaceVariant),
            const SizedBox(height: 12),
            Text(mesaj, style: TextStyle(fontSize: 14, color: cs.onSurfaceVariant)),
          ],
        ),
      ),
    );
  }
}
