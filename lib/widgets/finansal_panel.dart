import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:flutter/material.dart';

class FinansalPanel extends StatelessWidget {
  final Map<String, dynamic> hisseData;

  const FinansalPanel({
    super.key,
    required this.hisseData,
  });

  Map<String, dynamic> get _motorDetay {
    final v = hisseData['motor_detay'];
    if (v is Map<String, dynamic>) return v;
    return {};
  }

  Map<String, dynamic> get _rootTemel {
    final v = hisseData['temel'];
    if (v is Map<String, dynamic>) return v;
    return {};
  }

  Map<String, dynamic> get _motorTemel {
    final v = _motorDetay['temel'];
    if (v is Map<String, dynamic>) return v;
    return {};
  }

  double? _num(dynamic v) => v is num ? v.toDouble() : null;

  double? get _roe =>
      _num(_rootTemel['roe']) ??
      _num(_motorTemel['roe']) ??
      _num(hisseData['temel_roe']) ??
      _num(_motorDetay['temel_roe']);

  double? get _pdDd =>
      _num(_rootTemel['pd_dd']) ??
      _num(_motorTemel['pd_dd']) ??
      _num(hisseData['temel_pd_dd']) ??
      _num(_motorDetay['temel_pd_dd']);

  double? get _fk =>
      _num(_rootTemel['fk']) ??
      _num(_motorTemel['fk']) ??
      _num(_rootTemel['f_k']) ??
      _num(_motorTemel['f_k']) ??
      _num(hisseData['temel_fk']) ??
      _num(_motorDetay['temel_fk']);

  double? get _netKarMarji =>
      _num(_rootTemel['net_kar_marji']) ??
      _num(_motorTemel['net_kar_marji']) ??
      _num(_rootTemel['kar_marji']) ??
      _num(_motorTemel['kar_marji']) ??
      _num(hisseData['temel_kar_marji']) ??
      _num(_motorDetay['temel_net_kar_marji']) ??
      _num(_motorDetay['temel_kar_marji']);

  double? get _okBuyume =>
      _num(_rootTemel['ok_buyume']) ??
      _num(_motorTemel['ok_buyume']) ??
      _num(hisseData['temel_ok_buyume']) ??
      _num(_motorDetay['temel_ok_buyume']);

  double? get _borcFavok =>
      _num(_rootTemel['borc_favok']) ??
      _num(_motorTemel['borc_favok']) ??
      _num(_rootTemel['net_borc_favok']) ??
      _num(_motorTemel['net_borc_favok']) ??
      _num(hisseData['temel_borc_favok']) ??
      _num(hisseData['borc_favok']) ??
      _num(_motorDetay['temel_borc_favok']) ??
      _num(_motorDetay['borc_favok']) ??
      _num(_motorDetay['net_borc_favok']);

  double? get _beta =>
      _num(hisseData['beta']) ??
      _num(hisseData['beta_5y']) ??
      _num(_motorDetay['beta']) ??
      _num(_motorDetay['beta_5y']);

  double? get _rsi14 =>
      _num(hisseData['rsi_14']) ??
      _num(hisseData['rsi14']) ??
      _num(_motorDetay['rsi_14']);

  double _normRoe(double? v) {
    if (v == null) return 0.5;
    return v.clamp(0.0, 0.30).toDouble() / 0.30;
  }

  double _normPdDd(double? v) {
    if (v == null) return 0.5;
    return 1.0 - ((v - 0.5) / 3.5).clamp(0.0, 1.0).toDouble();
  }

  double _normFk(double? v) {
    if (v == null) return 0.5;
    return 1.0 - ((v - 5.0) / 35.0).clamp(0.0, 1.0).toDouble();
  }

  double _normNetKarMarji(double? v) {
    if (v == null) return 0.5;
    return v.clamp(0.0, 0.30).toDouble() / 0.30;
  }

  double _normOkBuyume(double? v) {
    if (v == null) return 0.5;
    return (v + 0.5).clamp(0.0, 1.5).toDouble() / 1.5;
  }

  String _pct(double? v) =>
      v == null ? '—' : '%${(v * 100).toStringAsFixed(1)}';

  String _x(double? v) => v == null ? '—' : '${v.toStringAsFixed(1)}x';

  String _sayi(double? v, {int fr = 2}) =>
      v == null ? '—' : v.toStringAsFixed(fr);

  String _roeAlt(double? v) {
    if (v == null) return '—';
    if (v >= 0.20) return 'Çok güçlü';
    if (v >= 0.12) return 'İyi';
    if (v >= 0.05) return 'Orta';
    return 'Zayıf';
  }

  String _pdDdAlt(double? v) {
    if (v == null) return '—';
    if (v < 1.0) return 'Ucuz';
    if (v < 2.5) return 'Makul';
    if (v < 4.0) return 'Yüksek';
    return 'Çok yüksek';
  }

  String _fkAlt(double? v) {
    if (v == null) return '—';
    if (v < 10) return 'Düşük';
    if (v < 20) return 'Orta';
    if (v < 35) return 'Yüksek';
    return 'Çok yüksek';
  }

  String _marjAlt(double? v) {
    if (v == null) return '—';
    if (v >= 0.20) return 'Güçlü';
    if (v >= 0.10) return 'Normal';
    if (v >= 0.0) return 'Zayıf';
    return 'Zarar';
  }

  String _borcAlt(double? v) {
    if (v == null) return '—';
    if (v < 1.0) return 'Düşük';
    if (v < 3.0) return 'Orta';
    return 'Yüksek';
  }

  String _betaAlt(double? v) {
    if (v == null) return '—';
    if (v < 0.8) return 'Defansif';
    if (v < 1.2) return 'Piyasa ile';
    return 'Agresif';
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;

    final bool veriYok = _roe == null &&
        _pdDd == null &&
        _fk == null &&
        _netKarMarji == null &&
        _okBuyume == null &&
        _borcFavok == null &&
        _beta == null &&
        _rsi14 == null;

    if (veriYok) {
      return SingleChildScrollView(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 40, 16, 24),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(
                    Icons.bar_chart_outlined,
                    size: 48,
                    color: cs.onSurfaceVariant,
                  ),
                  const SizedBox(height: 12),
                  Text(
                    'Finansal veri henüz yok',
                    style: TextStyle(
                      fontSize: 14,
                      color: cs.onSurfaceVariant,
                    ),
                  ),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: _GetiriPerformansBolumu(hisseData: hisseData),
            ),
          ],
        ),
      );
    }

    final radarDegerler = [
      _normRoe(_roe),
      _normFk(_fk),
      _normNetKarMarji(_netKarMarji),
      _normOkBuyume(_okBuyume),
      _normPdDd(_pdDd),
    ];

    const radarEtiketler = [
      'ROE',
      'F/K',
      'Kâr Marjı',
      'Büyüme',
      'Değerleme',
    ];

    final barVeriler = [
      _BarVeri(
        etiket: 'Değerleme',
        oran: _normPdDd(_pdDd),
        renk: const Color(0xFF4A90E2),
      ),
      _BarVeri(
        etiket: 'Büyüme',
        oran: _normOkBuyume(_okBuyume),
        renk: const Color(0xFF9B59B6),
      ),
      _BarVeri(
        etiket: 'Kâr Marjı',
        oran: _normNetKarMarji(_netKarMarji),
        renk: const Color(0xFFE6A817),
      ),
      _BarVeri(
        etiket: 'ROE',
        oran: _normRoe(_roe),
        renk: cs.primary,
      ),
      _BarVeri(
        etiket: 'Borç',
        oran: _borcFavok == null
            ? 0.5
            : 1.0 - (_borcFavok! / 5.0).clamp(0.0, 1.0).toDouble(),
        renk: cs.error,
      ),
    ];

    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SizedBox(
                width: 150,
                height: 150,
                child: CustomPaint(
                  painter: _RadarPainter(
                    degerler: radarDegerler,
                    etiketler: radarEtiketler,
                    renk: cs.primary,
                  ),
                ),
              ),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  children: barVeriler
                      .map(
                        (b) => Padding(
                          padding: const EdgeInsets.only(bottom: 10),
                          child: _BarSatir(veri: b),
                        ),
                      )
                      .toList(),
                ),
              ),
            ],
          ),
          const SizedBox(height: 20),
          _MetrikGrid(
            metrikler: [
              _MetrikVeri(
                etiket: 'F/K',
                deger: _x(_fk),
                alt: _fkAlt(_fk),
              ),
              _MetrikVeri(
                etiket: 'PD/DD',
                deger: _sayi(_pdDd),
                alt: _pdDdAlt(_pdDd),
              ),
              _MetrikVeri(
                etiket: 'Net Kâr Marjı',
                deger: _pct(_netKarMarji),
                alt: _marjAlt(_netKarMarji),
              ),
              _MetrikVeri(
                etiket: 'ROE',
                deger: _pct(_roe),
                alt: _roeAlt(_roe),
              ),
              _MetrikVeri(
                etiket: 'Borç/FAVÖK',
                deger: _sayi(_borcFavok),
                alt: _borcAlt(_borcFavok),
              ),
              _MetrikVeri(
                etiket: 'Beta',
                deger: _sayi(_beta),
                alt: _betaAlt(_beta),
              ),
            ],
          ),
          if (_rsi14 != null) ...[
            const SizedBox(height: 14),
            _RsiKart(rsi: _rsi14!),
          ],
          // ── Fundamental Engine Skoru ─────────────────────────────
          _FundamentalSkorBolumu(hisseData: hisseData),

          // ── Getiri Performansı ────────────────────────────────
          _GetiriPerformansBolumu(hisseData: hisseData),

          const SizedBox(height: 24),
        ],
      ),
    );
  }
}

// ── Fundamental Engine verileri ──────────────────────────────────
class _FundamentalSkorBolumu extends StatelessWidget {
  final Map<String, dynamic> hisseData;
  const _FundamentalSkorBolumu({required this.hisseData});

  Color _skorRengi(BuildContext context, double skor) {
    final cs = Theme.of(context).colorScheme;
    if (skor >= 7) return cs.primary;
    if (skor >= 4) return cs.tertiary;
    return cs.error;
  }

  static String _normalizePeriod(String raw) {
    final m = RegExp(r'^(\d{4})\s+(.+)$').firstMatch(raw.trim());
    if (m == null) return raw.trim();
    final year = m.group(1)!;
    switch (m.group(2)!.trim()) {
      case '3 Aylık':  return '$year Q1';
      case '6 Aylık':  return '$year Q2';
      case '9 Aylık':  return '$year Q3';
      case '12 Aylık': return '$year FY';
      case 'Yıllık':   return '$year FY';
      default: return raw.trim();
    }
  }

  void _aciklamaGoster(BuildContext context, String aciklama) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: (ctx) {
        final cs = Theme.of(ctx).colorScheme;
        return Padding(
          padding: EdgeInsets.only(bottom: MediaQuery.of(ctx).viewInsets.bottom),
          child: ConstrainedBox(
            constraints: BoxConstraints(
              maxHeight: MediaQuery.of(ctx).size.height * 0.7,
            ),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Center(
                  child: Container(
                    margin: const EdgeInsets.only(top: 10, bottom: 6),
                    width: 32,
                    height: 4,
                    decoration: BoxDecoration(
                      color: cs.onSurfaceVariant.withValues(alpha: 0.3),
                      borderRadius: BorderRadius.circular(99),
                    ),
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(20, 6, 20, 12),
                  child: Text(
                    'Finansal Açıklama',
                    style: TextStyle(
                      fontSize: 15,
                      fontWeight: FontWeight.w600,
                      color: cs.onSurface,
                    ),
                  ),
                ),
                Divider(height: 1, color: cs.outlineVariant),
                Flexible(
                  child: SingleChildScrollView(
                    padding: const EdgeInsets.fromLTRB(20, 16, 20, 24),
                    child: Text(
                      aciklama,
                      style: TextStyle(
                        fontSize: 13,
                        color: cs.onSurface,
                        height: 1.6,
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;

    final finansalSkor      = (hisseData['finansal_skor']      as num?)?.toDouble();
    final finansalLabel     =  hisseData['finansal_skor_label'] as String?;
    final finansalSubscores =  hisseData['finansal_subscores']  as Map<String, dynamic>?;
    final piotroskiScore    = (hisseData['piotroski_score']     as num?)?.toInt();
    final finansalAciklama  =  hisseData['finansal_aciklama']   as String?;
    final rawPeriod         = (hisseData['finansal_period']     as String?)?.trim()
                           ?? (hisseData['financial_period']    as String?)?.trim()
                           ?? (hisseData['period']              as String?)?.trim();
    final finansalDonem     = (rawPeriod != null && rawPeriod.isNotEmpty)
                              ? _normalizePeriod(rawPeriod)
                              : null;

    if (finansalSkor == null &&
        (finansalSubscores == null || finansalSubscores.isEmpty) &&
        piotroskiScore == null &&
        (finansalAciklama == null || finansalAciklama.isEmpty)) {
      return const SizedBox.shrink();
    }

    const subskorAdlar = <String, String>{
      'profitability': 'Karlılık',
      'growth':        'Büyüme',
      'valuation':     'Değerleme',
      'stability':     'İstikrar',
      'balance_sheet': 'Bilanço',
      'cash_flow':     'Nakit Akışı',
    };

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Divider(),
        const SizedBox(height: 8),

        // Başlık + skor + label
        Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('Finansal Skor',
                      style: TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.w600,
                          color: cs.onSurface)),
                  if (finansalLabel != null && finansalLabel.isNotEmpty)
                    Text(finansalLabel,
                        style: TextStyle(
                            fontSize: 11, color: cs.onSurfaceVariant)),
                ],
              ),
            ),
            if (finansalSkor != null)
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
                decoration: BoxDecoration(
                  color: _skorRengi(context, finansalSkor)
                      .withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(
                  '${finansalSkor.toStringAsFixed(2)} / 10',
                  style: TextStyle(
                      fontSize: 14,
                      fontWeight: FontWeight.bold,
                      color: _skorRengi(context, finansalSkor)),
                ),
              ),
          ],
        ),

        // Alt kırılımlar
        if (finansalSubscores != null &&
            subskorAdlar.keys.any((k) => finansalSubscores[k] != null)) ...[
          const SizedBox(height: 10),
          Text('Alt Kırılımlar',
              style: TextStyle(
                  fontSize: 11,
                  color: cs.onSurfaceVariant,
                  fontWeight: FontWeight.w600)),
          if (finansalDonem != null) ...[
            const SizedBox(height: 2),
            Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text('Dönem: $finansalDonem',
                    style: TextStyle(fontSize: 11, color: cs.onSurfaceVariant)),
                if (finansalAciklama != null && finansalAciklama.isNotEmpty) ...[
                  const SizedBox(width: 4),
                  GestureDetector(
                    onTap: () => _aciklamaGoster(context, finansalAciklama),
                    child: Icon(
                      Icons.info_outline,
                      size: 14,
                      color: cs.onSurfaceVariant,
                    ),
                  ),
                ],
              ],
            ),
          ],
          const SizedBox(height: 4),
          for (final e in subskorAdlar.entries)
            if (finansalSubscores[e.key] != null)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 2),
                child: Row(
                  children: [
                    Expanded(
                      child: Text(e.value,
                          style: TextStyle(
                              fontSize: 12, color: cs.onSurfaceVariant)),
                    ),
                    Text(
                      (finansalSubscores[e.key] as num)
                          .toDouble()
                          .toStringAsFixed(2),
                      style: TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.bold,
                          color: _skorRengi(
                              context,
                              (finansalSubscores[e.key] as num)
                                  .toDouble())),
                    ),
                  ],
                ),
              ),
        ],

        // Piotroski
        if (piotroskiScore != null) ...[
          const SizedBox(height: 8),
          Row(
            children: [
              Expanded(
                child: Text('Piotroski',
                    style: TextStyle(
                        fontSize: 12, color: cs.onSurfaceVariant)),
              ),
              Text('$piotroskiScore / 9',
                  style: TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.bold,
                      color: _skorRengi(
                          context, piotroskiScore * 10.0 / 9.0))),
            ],
          ),
        ],

        const SizedBox(height: 8),
      ],
    );
  }
}

class _BarVeri {
  final String etiket;
  final double oran;
  final Color renk;

  const _BarVeri({
    required this.etiket,
    required this.oran,
    required this.renk,
  });
}

class _BarSatir extends StatelessWidget {
  final _BarVeri veri;

  const _BarSatir({
    required this.veri,
  });

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;

    return Row(
      children: [
        SizedBox(
          width: 72,
          child: Text(
            veri.etiket,
            style: TextStyle(
              fontSize: 11,
              color: cs.onSurfaceVariant,
            ),
          ),
        ),
        Expanded(
          child: ClipRRect(
            borderRadius: BorderRadius.circular(99),
            child: LinearProgressIndicator(
              value: veri.oran.clamp(0.0, 1.0).toDouble(),
              minHeight: 6,
              backgroundColor: cs.surfaceContainerHighest,
              valueColor: AlwaysStoppedAnimation<Color>(veri.renk),
            ),
          ),
        ),
      ],
    );
  }
}

class _MetrikVeri {
  final String etiket;
  final String deger;
  final String alt;

  const _MetrikVeri({
    required this.etiket,
    required this.deger,
    required this.alt,
  });
}

class _MetrikGrid extends StatelessWidget {
  final List<_MetrikVeri> metrikler;

  const _MetrikGrid({
    required this.metrikler,
  });

  @override
  Widget build(BuildContext context) {
    return GridView.count(
      crossAxisCount: 3,
      crossAxisSpacing: 8,
      mainAxisSpacing: 8,
      childAspectRatio: 1.15,
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      children: metrikler.map((m) => _MetrikKart(veri: m)).toList(),
    );
  }
}

class _MetrikKart extends StatelessWidget {
  final _MetrikVeri veri;

  const _MetrikKart({
    required this.veri,
  });

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: cs.surface,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Text(
            veri.etiket,
            style: TextStyle(
              fontSize: 11,
              color: cs.onSurfaceVariant,
            ),
          ),
          const SizedBox(height: 2),
          Text(
            veri.deger,
            style: TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.w500,
              color: cs.onSurface,
            ),
          ),
          const SizedBox(height: 2),
          Text(
            veri.alt,
            style: TextStyle(
              fontSize: 10,
              color: cs.onSurfaceVariant,
            ),
          ),
        ],
      ),
    );
  }
}

class _RsiKart extends StatelessWidget {
  final double rsi;

  const _RsiKart({
    required this.rsi,
  });

  String get _durum {
    if (rsi >= 70) return 'Aşırı alım bölgesi';
    if (rsi <= 30) return 'Aşırı satım bölgesi';
    if (rsi >= 55) return 'Güçlü momentum';
    if (rsi <= 45) return 'Zayıf momentum';
    return 'Nötr bölge';
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;

    final renk = rsi >= 70
        ? Colors.red
        : rsi <= 30
            ? Colors.orange
            : rsi >= 55
                ? cs.primary
                : cs.onSurfaceVariant;

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: cs.surface,
        borderRadius: BorderRadius.circular(10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Text(
                'RSI 14',
                style: TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w700,
                ),
              ),
              const Spacer(),
              Text(
                rsi.toStringAsFixed(1),
                style: TextStyle(
                  fontSize: 18,
                  fontWeight: FontWeight.w800,
                  color: renk,
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          ClipRRect(
            borderRadius: BorderRadius.circular(99),
            child: LinearProgressIndicator(
              value: (rsi / 100).clamp(0.0, 1.0).toDouble(),
              minHeight: 8,
              backgroundColor: cs.surfaceContainerHighest,
              valueColor: AlwaysStoppedAnimation<Color>(renk),
            ),
          ),
          const SizedBox(height: 6),
          Row(
            children: [
              Text(
                '30',
                style: TextStyle(
                  fontSize: 10,
                  color: cs.onSurfaceVariant,
                ),
              ),
              const Spacer(),
              Text(
                _durum,
                style: TextStyle(
                  fontSize: 11,
                  color: cs.onSurfaceVariant,
                ),
              ),
              const Spacer(),
              Text(
                '70',
                style: TextStyle(
                  fontSize: 10,
                  color: cs.onSurfaceVariant,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _RadarPainter extends CustomPainter {
  final List<double> degerler;
  final List<String> etiketler;
  final Color renk;

  _RadarPainter({
    required this.degerler,
    required this.etiketler,
    required this.renk,
  }) : assert(degerler.length == etiketler.length);

  @override
  void paint(Canvas canvas, Size size) {
    final merkez = Offset(size.width / 2, size.height / 2);
    final maxYaricap = math.min(size.width, size.height) / 2 - 14;
    final n = degerler.length;

    final acilar = List<double>.generate(
      n,
      (i) => -math.pi / 2 + (2 * math.pi * i / n),
    );

    final izgaraPaint = Paint()
      ..color = renk.withValues(alpha: 0.15)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 0.5;

    for (final r in [0.33, 0.66, 1.0]) {
      final path = Path();

      for (var i = 0; i < n; i++) {
        final x = merkez.dx + maxYaricap * r * math.cos(acilar[i]);
        final y = merkez.dy + maxYaricap * r * math.sin(acilar[i]);

        if (i == 0) {
          path.moveTo(x, y);
        } else {
          path.lineTo(x, y);
        }
      }

      path.close();
      canvas.drawPath(path, izgaraPaint);
    }

    final eksenPaint = Paint()
      ..color = renk.withValues(alpha: 0.18)
      ..strokeWidth = 0.5;

    for (var i = 0; i < n; i++) {
      canvas.drawLine(
        merkez,
        Offset(
          merkez.dx + maxYaricap * math.cos(acilar[i]),
          merkez.dy + maxYaricap * math.sin(acilar[i]),
        ),
        eksenPaint,
      );
    }

    final dataPath = Path();
    final noktalar = <Offset>[];

    for (var i = 0; i < n; i++) {
      final r = maxYaricap * degerler[i].clamp(0.0, 1.0).toDouble();
      final p = Offset(
        merkez.dx + r * math.cos(acilar[i]),
        merkez.dy + r * math.sin(acilar[i]),
      );

      noktalar.add(p);

      if (i == 0) {
        dataPath.moveTo(p.dx, p.dy);
      } else {
        dataPath.lineTo(p.dx, p.dy);
      }
    }

    dataPath.close();

    final dolguPaint = Paint()
      ..shader = RadialGradient(
        colors: [
          renk.withValues(alpha: 0.55),
          renk.withValues(alpha: 0.20),
        ],
      ).createShader(
        Rect.fromCircle(
          center: merkez,
          radius: maxYaricap,
        ),
      )
      ..style = PaintingStyle.fill;

    canvas.drawPath(dataPath, dolguPaint);

    final cizgiPaint = Paint()
      ..color = renk
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.5
      ..strokeJoin = StrokeJoin.round;

    canvas.drawPath(dataPath, cizgiPaint);

    final noktaPaint = Paint()..color = renk;

    for (final p in noktalar) {
      canvas.drawCircle(p, 2.5, noktaPaint);
    }

    for (var i = 0; i < n; i++) {
      final etiketYaricap = maxYaricap + 8;
      final lx = merkez.dx + etiketYaricap * math.cos(acilar[i]);
      final ly = merkez.dy + etiketYaricap * math.sin(acilar[i]);

      final tp = TextPainter(
        text: TextSpan(
          text: etiketler[i],
          style: TextStyle(
            fontSize: 9,
            color: renk.withValues(alpha: 0.9),
            fontWeight: FontWeight.w500,
          ),
        ),
        textDirection: ui.TextDirection.ltr,
      )..layout();

      tp.paint(
        canvas,
        Offset(
          lx - tp.width / 2,
          ly - tp.height / 2,
        ),
      );
    }
  }

  @override
  bool shouldRepaint(_RadarPainter old) {
    return old.degerler != degerler ||
        old.etiketler != etiketler ||
        old.renk != renk;
  }
}

// ── Getiri Performansı bölümü ─────────────────────────────────────────────────
class _GetiriPerformansBolumu extends StatelessWidget {
  final Map<String, dynamic> hisseData;
  const _GetiriPerformansBolumu({required this.hisseData});

  static const _donemler = <(String, String)>[
    ('1 Gün',   'gunluk_degisim_yuzde'),
    ('1 Hafta', 'haftalik_degisim_yuzde'),
    ('1 Ay',    'aylik_degisim_yuzde'),
    ('3 Ay',    'uc_ay_degisim_yuzde'),
    ('6 Ay',    'alti_ay_degisim_yuzde'),
    ('YBB',     'ybb_degisim_yuzde'),
    ('1 Yıl',   'yillik_degisim_yuzde'),
  ];

  double? _d(String key) {
    final v = hisseData[key];
    return v is num ? v.toDouble() : null;
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;

    final values = _donemler
        .map((e) => (etiket: e.$1, deger: _d(e.$2)))
        .toList();
    final temettu = _d('temettu_verimi');

    final maxAbs = values
        .map((e) => e.deger?.abs() ?? 0.0)
        .fold(0.0, math.max);
    final normalizer = maxAbs > 0 ? maxAbs : 1.0;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Divider(),
        const SizedBox(height: 8),
        Text(
          'Getiri Performansı',
          style: TextStyle(
            fontSize: 13,
            fontWeight: FontWeight.w600,
            color: cs.onSurface,
          ),
        ),
        const SizedBox(height: 8),
        for (final e in values)
          _GetiriSatir(
            etiket: e.etiket,
            deger: e.deger,
            normalizer: normalizer,
          ),
        if (temettu != null) ...[
          const SizedBox(height: 2),
          _GetiriSatir(
            etiket: 'Temettü',
            deger: temettu,
            normalizer: normalizer,
            isTemettu: true,
          ),
        ],
        const SizedBox(height: 8),
      ],
    );
  }
}

class _GetiriSatir extends StatelessWidget {
  final String etiket;
  final double? deger;
  final double normalizer;
  final bool isTemettu;

  const _GetiriSatir({
    required this.etiket,
    required this.deger,
    required this.normalizer,
    this.isTemettu = false,
  });

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;

    if (deger == null) {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 3),
        child: Row(
          children: [
            SizedBox(
              width: 64,
              child: Text(
                etiket,
                style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant),
              ),
            ),
            const Expanded(child: SizedBox.shrink()),
            Text('—', style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant)),
          ],
        ),
      );
    }

    final pozitif = isTemettu || deger! >= 0;
    final barRenk = isTemettu
        ? cs.primary
        : pozitif
            ? Colors.green.shade600
            : Colors.red.shade600;

    final barOran = (deger!.abs() / normalizer).clamp(0.0, 1.0);
    final degerMetni = isTemettu
        ? '%${deger!.toStringAsFixed(2)}'
        : '${deger! >= 0 ? '+' : ''}${deger!.toStringAsFixed(2)}%';

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        children: [
          SizedBox(
            width: 64,
            child: Text(
              etiket,
              style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant),
            ),
          ),
          Expanded(
            child: Align(
              alignment: Alignment.centerLeft,
              child: FractionallySizedBox(
                alignment: Alignment.centerLeft,
                widthFactor: barOran < 0.05 ? 0.05 : barOran,
                child: Container(
                  height: 6,
                  decoration: BoxDecoration(
                    color: barRenk.withValues(alpha: 0.85),
                    borderRadius: BorderRadius.circular(99),
                  ),
                ),
              ),
            ),
          ),
          const SizedBox(width: 8),
          SizedBox(
            width: 76,
            child: Text(
              degerMetni,
              textAlign: TextAlign.right,
              style: TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w600,
                color: isTemettu ? cs.onSurface : barRenk,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
