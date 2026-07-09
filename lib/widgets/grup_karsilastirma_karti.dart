import 'dart:convert';
import 'dart:math' show max;
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:intl/intl.dart';

class GrupKarsilastirmaKarti extends StatefulWidget {
  final String symbol;
  final String apiBaseUrl;

  const GrupKarsilastirmaKarti({
    super.key,
    required this.symbol,
    required this.apiBaseUrl,
  });

  @override
  State<GrupKarsilastirmaKarti> createState() => _GrupKarsilastirmaKartiState();
}

class _GrupKarsilastirmaKartiState extends State<GrupKarsilastirmaKarti> {
  Map<String, dynamic>? _data;
  bool _loading = true;
  bool _hata = false;
  String? _selectedMetric;

  static const _metricOrder = <String>[
    'fk',
    'finansal_skor',
    'paynotu_skoru',
    'roe',
    'pd_dd',
  ];

  static final _fmtRatio   = NumberFormat('#,##0.0', 'tr_TR');
  static final _fmtScore   = NumberFormat('#,##0.00', 'tr_TR');
  static final _fmtPercent = NumberFormat('#,##0.0', 'tr_TR');

  @override
  void initState() {
    super.initState();
    _fetch();
  }

  @override
  void didUpdateWidget(GrupKarsilastirmaKarti oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.symbol != widget.symbol) {
      setState(() {
        _data          = null;
        _hata          = false;
        _loading       = true;
        _selectedMetric = null;
      });
      _fetch();
    }
  }

  Future<void> _fetch() async {
    final requestedSymbol = widget.symbol;
    if (requestedSymbol.isEmpty) {
      if (mounted) setState(() { _loading = false; _hata = false; });
      return;
    }

    if (kDebugMode) debugPrint('SEKTOR_COMPARE start symbol=$requestedSymbol');

    try {
      final uri = Uri.parse(
        '${widget.apiBaseUrl}/group-compare/${Uri.encodeComponent(requestedSymbol)}',
      );
      final response = await http
          .get(uri, headers: const {'Accept': 'application/json'})
          .timeout(const Duration(seconds: 15));

      if (!mounted || requestedSymbol != widget.symbol) return;

      if (response.statusCode == 200) {
        final decoded = jsonDecode(response.body) as Object?;
        if (decoded is Map<String, dynamic>) {
          final available =
              (decoded['available_metrics'] as Map<String, dynamic>?) ?? {};
          String? defaultMetric;
          for (final k in _metricOrder) {
            if (available.containsKey(k)) {
              defaultMetric = k;
              break;
            }
          }
          setState(() {
            _data           = decoded;
            _loading        = false;
            _hata           = false;
            _selectedMetric = defaultMetric;
          });
          return;
        }
      }

      if (mounted) setState(() { _loading = false; _hata = true; });
    } catch (e) {
      if (!mounted) return;
      if (kDebugMode) debugPrint('SEKTOR_COMPARE error symbol=$requestedSymbol error=$e');
      setState(() { _loading = false; _hata = true; });
    }
  }

  // ── Format helpers ────────────────────────────────────────────────────────

  String _formatVal(double v, String unit) {
    switch (unit) {
      case 'ratio':   return '${_fmtRatio.format(v)}x';
      case 'percent': return '%${_fmtPercent.format(v)}';
      default:        return _fmtScore.format(v);
    }
  }

  double? _metricVal(Map<String, dynamic> company, String key) {
    final metrics = company['metrics'] as Map<String, dynamic>?;
    if (metrics == null) return null;
    final v = metrics[key];
    if (v == null) return null;
    return (v as num).toDouble();
  }

  // ── Shell widget ─────────────────────────────────────────────────────────

  Widget _kart({required BuildContext context, required Widget child}) {
    final cs = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 12),
      decoration: BoxDecoration(
        color: cs.surface,
        borderRadius: BorderRadius.circular(10),
      ),
      child: child,
    );
  }

  Widget _baslikMetni(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Text(
      'Sektör Karşılaştırması',
      style: TextStyle(
        fontSize: 12,
        fontWeight: FontWeight.w700,
        color: cs.onSurface,
      ),
    );
  }

  // ── States ────────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;

    // Loading
    if (_loading) {
      return _kart(
        context: context,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _baslikMetni(context),
            const SizedBox(height: 8),
            Row(children: [
              SizedBox(
                width: 14, height: 14,
                child: CircularProgressIndicator(
                  strokeWidth: 1.5,
                  color: cs.onSurfaceVariant,
                ),
              ),
              const SizedBox(width: 8),
              Text(
                'Rakip veriler hazırlanıyor…',
                style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant),
              ),
            ]),
          ],
        ),
      );
    }

    // Hata
    if (_hata) {
      return _kart(
        context: context,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _baslikMetni(context),
            const SizedBox(height: 6),
            Text(
              'Sektör karşılaştırması yüklenemedi.',
              style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant),
            ),
            const SizedBox(height: 6),
            GestureDetector(
              onTap: () {
                setState(() { _loading = true; _hata = false; });
                _fetch();
              },
              child: Text(
                'Tekrar Dene',
                style: TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                  color: cs.primary,
                ),
              ),
            ),
          ],
        ),
      );
    }

    if (_data == null) return const SizedBox.shrink();

    final group     = _data!['group'] as Map<String, dynamic>?;
    final companies = ((_data!['companies']) as List?)
            ?.cast<Map<String, dynamic>>() ??
        [];
    final availableMetrics =
        (_data!['available_metrics'] as Map<String, dynamic>?) ?? {};
    final metricSummaries =
        (_data!['metric_summaries'] as Map<String, dynamic>?) ?? {};

    // Grup yok veya boş
    if (group == null || companies.isEmpty) {
      return _kart(
        context: context,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _baslikMetni(context),
            const SizedBox(height: 6),
            Text(
              'Bu hisse için yeterli karşılaştırma verisi bulunamadı.',
              style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant),
            ),
          ],
        ),
      );
    }

    final groupName       = (group['name'] as String?) ?? '';
    final limitedPeer     = (group['limited_peer_group'] as bool?) ?? false;
    final actualPeerCount = companies.where((c) => c['selected'] != true).length;

    final currentMetric = _selectedMetric;
    final metricInfo    = currentMetric != null
        ? (availableMetrics[currentMetric] as Map<String, dynamic>?)
        : null;
    final metricUnit    = (metricInfo?['unit'] as String?) ?? 'score';

    final summary   = currentMetric != null
        ? (metricSummaries[currentMetric] as Map<String, dynamic>?)
        : null;
    final peerAvg   = summary != null
        ? (summary['peer_average'] as num?)?.toDouble()
        : null;

    // Seçili metriğe göre büyükten küçüğe sırala; null en alta
    final sorted = [...companies];
    if (currentMetric != null) {
      sorted.sort((a, b) {
        final av = _metricVal(a, currentMetric);
        final bv = _metricVal(b, currentMetric);
        if (av == null && bv == null) return 0;
        if (av == null) return 1;
        if (bv == null) return -1;
        return bv.compareTo(av);
      });
    }

    // Bar normalleştirme: tüm geçerli pozitif değerlerin maksimumu
    double maxVal = 0;
    for (final c in sorted) {
      final v = currentMetric != null ? _metricVal(c, currentMetric) : null;
      if (v != null && v > maxVal) maxVal = v;
    }

    // Dropdown seçenekleri
    final dropdownItems = _metricOrder
        .where(availableMetrics.containsKey)
        .map((k) {
          final info  = availableMetrics[k] as Map<String, dynamic>?;
          final label = (info?['label'] as String?) ?? k;
          return DropdownMenuItem<String>(
            value: k,
            child: Text(label, style: const TextStyle(fontSize: 11)),
          );
        })
        .toList();

    return _kart(
      context: context,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // ── Başlık satırı ───────────────────────────────────────────────
          Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              _baslikMetni(context),
              const Spacer(),
              if (dropdownItems.isNotEmpty && currentMetric != null)
                DropdownButtonHideUnderline(
                  child: DropdownButton<String>(
                    value: currentMetric,
                    items: dropdownItems,
                    isDense: true,
                    style: TextStyle(fontSize: 11, color: cs.onSurface),
                    onChanged: (v) {
                      if (v != null) setState(() => _selectedMetric = v);
                    },
                  ),
                ),
            ],
          ),

          const SizedBox(height: 2),

          // ── Alt sektör + rakip sayısı ────────────────────────────────────
          Text(
            groupName,
            style: TextStyle(
              fontSize: 11,
              fontWeight: FontWeight.w500,
              color: cs.onSurfaceVariant,
            ),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
          ),
          Text(
            limitedPeer
                ? 'Bu sektörde karşılaştırılabilir $actualPeerCount rakip bulunmaktadır.'
                : 'Piyasa değerine göre en büyük 5 rakip',
            style: TextStyle(fontSize: 10, color: cs.onSurfaceVariant),
          ),

          const SizedBox(height: 10),

          // ── Bar grafik ──────────────────────────────────────────────────
          LayoutBuilder(
            builder: (context, constraints) {
              // Sütun genişlikleri
              const valueW  = 52.0;  // sol: değer
              const symW    = 52.0;  // sağ: sembol
              const gapL    = 6.0;   // değer-bar arası
              const gapR    = 6.0;   // bar-sembol arası
              final barAreaW = max(
                0.0,
                constraints.maxWidth - valueW - symW - gapL - gapR,
              );

              // Rakip ortalama çizgisinin bar alanı içindeki x konumu
              double? avgLineX;
              if (peerAvg != null && maxVal > 0 && peerAvg > 0) {
                avgLineX = (peerAvg / maxVal * barAreaW).clamp(0.0, barAreaW);
              }

              // Ortalama etiketi satırı
              Widget avgHeader = const SizedBox.shrink();
              if (avgLineX != null && peerAvg != null) {
                // Etiketi çizginin üstüne hizala, taşmasın
                const labelW = 90.0;
                double labelOffset = avgLineX + valueW + gapL - labelW / 2;
                labelOffset = labelOffset.clamp(
                  0.0,
                  constraints.maxWidth - labelW,
                );
                avgHeader = SizedBox(
                  height: 18,
                  child: Stack(
                    clipBehavior: Clip.none,
                    children: [
                      // Dikey çizgi (header kısmında)
                      Positioned(
                        left: avgLineX + valueW + gapL - 0.75,
                        top: 10,
                        bottom: 0,
                        child: Container(
                          width: 1.5,
                          color: cs.onSurfaceVariant.withValues(alpha: 0.40),
                        ),
                      ),
                      // Etiket
                      Positioned(
                        left: labelOffset,
                        top: 0,
                        child: Container(
                          width: labelW,
                          alignment: Alignment.center,
                          child: Text(
                            'Rakip Ort. ${_formatVal(peerAvg, metricUnit)}',
                            style: TextStyle(
                              fontSize: 9,
                              color: cs.onSurfaceVariant.withValues(alpha: 0.70),
                            ),
                            textAlign: TextAlign.center,
                          ),
                        ),
                      ),
                    ],
                  ),
                );
              }

              return Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  // Ortalama etiket satırı
                  avgHeader,
                  if (avgLineX != null) const SizedBox(height: 2),

                  // Bar satırları
                  ...sorted.map((company) {
                    final sym        = (company['symbol'] as String?) ?? '';
                    final isSelected = (company['selected'] as bool?) ?? false;
                    final val        = currentMetric != null
                        ? _metricVal(company, currentMetric)
                        : null;

                    // Bar oranı — minimum görünür genişlik (0.0 hariç)
                    double barRatio = 0.0;
                    if (val != null && val != 0.0 && maxVal > 0) {
                      barRatio = (val / maxVal).clamp(0.0, 1.0);
                    }
                    final minBarW = (val != null && val != 0.0) ? 4.0 : 0.0;
                    final barW    = max(minBarW, barAreaW * barRatio);

                    final barColor = isSelected
                        ? cs.primary
                        : cs.primary.withValues(alpha: 0.28);

                    return Padding(
                      padding: const EdgeInsets.only(bottom: 6),
                      child: SizedBox(
                        height: 20,
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.center,
                          children: [
                            // ── Değer (sol, right-align) ─────────────────
                            SizedBox(
                              width: valueW,
                              child: Text(
                                val != null
                                    ? _formatVal(val, metricUnit)
                                    : '—',
                                textAlign: TextAlign.right,
                                style: TextStyle(
                                  fontSize: 11,
                                  fontWeight: isSelected
                                      ? FontWeight.w600
                                      : FontWeight.w400,
                                  color: val != null
                                      ? cs.onSurface
                                      : cs.onSurfaceVariant,
                                ),
                              ),
                            ),
                            const SizedBox(width: gapL),

                            // ── Bar alanı (Stack: bar + avg çizgisi) ─────
                            SizedBox(
                              width: barAreaW,
                              height: 20,
                              child: Stack(
                                clipBehavior: Clip.none,
                                children: [
                                  // Bar
                                  Positioned(
                                    left: 0,
                                    top: 5,
                                    bottom: 5,
                                    child: Container(
                                      width: barW,
                                      decoration: BoxDecoration(
                                        color: barColor,
                                        borderRadius: BorderRadius.circular(2),
                                      ),
                                    ),
                                  ),
                                  // Rakip ortalama dikey çizgisi
                                  if (avgLineX != null)
                                    Positioned(
                                      left: avgLineX - 0.75,
                                      top: 0,
                                      bottom: 0,
                                      child: Container(
                                        width: 1.5,
                                        color: cs.onSurfaceVariant
                                            .withValues(alpha: 0.40),
                                      ),
                                    ),
                                ],
                              ),
                            ),
                            const SizedBox(width: gapR),

                            // ── Sembol (sağ) ─────────────────────────────
                            SizedBox(
                              width: symW,
                              child: Row(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  Flexible(
                                    child: Text(
                                      sym,
                                      overflow: TextOverflow.ellipsis,
                                      style: TextStyle(
                                        fontSize: 11,
                                        fontWeight: isSelected
                                            ? FontWeight.w700
                                            : FontWeight.w400,
                                        color: isSelected
                                            ? cs.onSurface
                                            : cs.onSurfaceVariant,
                                      ),
                                    ),
                                  ),
                                  // Seçili nokta göstergesi
                                  if (isSelected) ...[
                                    const SizedBox(width: 3),
                                    Container(
                                      width: 5,
                                      height: 5,
                                      decoration: BoxDecoration(
                                        color: cs.primary,
                                        shape: BoxShape.circle,
                                      ),
                                    ),
                                  ],
                                ],
                              ),
                            ),
                          ],
                        ),
                      ),
                    );
                  }),

                  // ── Alt bilgi ────────────────────────────────────────────
                  const SizedBox(height: 4),
                  Text(
                    'Vurgu rengi seçili şirketi gösterir. Renk iyi/kötü anlamına gelmez.',
                    style: TextStyle(
                      fontSize: 9,
                      color: cs.onSurfaceVariant.withValues(alpha: 0.60),
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    '— işareti, ilgili şirket için bu dönemde veri hesaplanamadığını gösterir (zarar, yetersiz geçmiş veya farklı bilanço modeli).',
                    style: TextStyle(
                      fontSize: 9,
                      color: cs.onSurfaceVariant.withValues(alpha: 0.60),
                    ),
                  ),
                ],
              );
            },
          ),
        ],
      ),
    );
  }
}
