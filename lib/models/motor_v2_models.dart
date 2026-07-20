/// PayNotu Motor v2 — typed model katmanı.
///
/// Kaynak: backend/docs/paynotu_component_interface.md §2 (enum'lar), §7
/// (MotorV2Result/ComponentScore), backend/docs/paynotu_motor_v2_spec_v1_1.md
/// §8 (bilgi kartları). Tip sözleşmesinin tek kaynağı bu dokümanlardır —
/// burada tekrar yorumlanmaz, birebir taşınır.
///
/// Gölge dönemde (`motor_v2` alanı Firestore'da henüz yazılmıyor) tüm
/// `fromFirestore` çağrıları `null` girdiyle çalışır ve boş/`null` model
/// döner — widget katmanı bunu "Yeterli veri yok" durumuna çevirir.
library;

/// Satır/bileşen güven kademesi. Deterministik, gün-bazlı (spec §1) — float DEĞİL.
enum Confidence {
  dusuk('dusuk'),
  orta('orta'),
  yuksek('yuksek');

  final String value;
  const Confidence(this.value);

  static Confidence? fromValue(dynamic v) {
    if (v is! String) return null;
    for (final c in Confidence.values) {
      if (c.value == v) return c;
    }
    return null;
  }
}

/// Bir satırın/kartın çıktı biçimi. Format seçimi widget'larda buradan yapılır.
enum OutputType {
  score('score'),
  percentage('percentage'),
  ratio('ratio'),
  days('days'),
  date('date'),
  count('count'),
  label('label'),
  text('text');

  final String value;
  const OutputType(this.value);
}

/// Anayasa bileşen tablosundaki 5 davranış bileşeni.
enum ComponentId {
  karakterOynaklik('karakter_oynaklik', 'Karakter / Oynaklık'),
  sokAktivitesi('sok_aktivitesi', 'Şok Aktivitesi'),
  likiditeYapisi('likidite_yapisi', 'Likidite Yapısı'),
  fiyatHacimSekli('fiyat_hacim_sekli', 'Fiyat-Hacim Şekli'),
  rejimIstikrarsizligi('rejim_istikrarsizligi', 'Rejim İstikrarsızlığı');

  final String id;
  final String uiAdi;
  const ComponentId(this.id, this.uiAdi);

  static ComponentId? fromId(String id) {
    for (final c in ComponentId.values) {
      if (c.id == id) return c;
    }
    return null;
  }
}

/// `ComponentResult`'ın Firestore'a giden alt kümesi (interface §7).
/// `diagnostics` ve ham `metrics` burada YOK — composer'da daralır.
class ComponentScore {
  final double? score; // 0–10; null = hesaplanamadı
  final Confidence confidence;
  final String explanationTr; // SPK-uyumlu 1–2 cümle (Madde 10)

  const ComponentScore({
    required this.score,
    required this.confidence,
    required this.explanationTr,
  });

  ComponentScore copyWith({
    double? score,
    Confidence? confidence,
    String? explanationTr,
  }) {
    return ComponentScore(
      score: score ?? this.score,
      confidence: confidence ?? this.confidence,
      explanationTr: explanationTr ?? this.explanationTr,
    );
  }

  factory ComponentScore.fromFirestore(Map<String, dynamic> json) {
    return ComponentScore(
      score: (json['score'] as num?)?.toDouble(),
      confidence: Confidence.fromValue(json['confidence']) ?? Confidence.dusuk,
      explanationTr: (json['explanation_tr'] as String?) ??
          'Bu bileşen için yeterli veri bulunmuyor.',
    );
  }
}

// ─────────────────────────────────────────────────────────────────────────
// Katman A — Bilgi kartları (skorsuz, spec §8)
// Alan adları spec ID'lerinden mekanik türetilir: snake_case → camelCase,
// info_ öneki düşer; bileşik Tip iki alana bölünür (…Percent + …Days vb.)
// ─────────────────────────────────────────────────────────────────────────

class TarihselKonumCard {
  final double? pricePercentile5y; // info_price_percentile_5y (percentage)
  final double? madDevMedian250; // info_mad_dev_median250 (ratio, "+2.7 MAD")
  final double? athDistancePercent; // info_ath_distance (percentage)
  final int? athDistanceDays; // info_ath_distance (days)
  final double? atlDistancePercent; // info_atl_distance (percentage)
  final int? atlDistanceDays; // info_atl_distance (days)
  final String? trendStateLabel; // info_trend_state (label)
  final int? trendStateDays; // info_trend_state (days)
  final double? return30d; // info_return_30d (percentage)
  final int? consecutiveUp30d; // info_consecutive_up_30d (count)

  const TarihselKonumCard({
    this.pricePercentile5y,
    this.madDevMedian250,
    this.athDistancePercent,
    this.athDistanceDays,
    this.atlDistancePercent,
    this.atlDistanceDays,
    this.trendStateLabel,
    this.trendStateDays,
    this.return30d,
    this.consecutiveUp30d,
  });

  bool get isEmpty =>
      pricePercentile5y == null &&
      madDevMedian250 == null &&
      athDistancePercent == null &&
      atlDistancePercent == null &&
      trendStateLabel == null &&
      return30d == null &&
      consecutiveUp30d == null;

  factory TarihselKonumCard.fromMetrics(Map<String, dynamic> metrics) {
    return TarihselKonumCard(
      pricePercentile5y: _d(metrics['info_price_percentile_5y']),
      madDevMedian250: _d(metrics['info_mad_dev_median250']),
      athDistancePercent: _d(metrics['info_ath_distance_percent']),
      athDistanceDays: _i(metrics['info_ath_distance_days']),
      atlDistancePercent: _d(metrics['info_atl_distance_percent']),
      atlDistanceDays: _i(metrics['info_atl_distance_days']),
      trendStateLabel: metrics['info_trend_state_label'] as String?,
      trendStateDays: _i(metrics['info_trend_state_days']),
      return30d: _d(metrics['info_return_30d']),
      consecutiveUp30d: _i(metrics['info_consecutive_up_30d']),
    );
  }
}

class DayaniklilikCard {
  final double? maxDrawdown5y; // info_max_drawdown_5y (percentage)
  final int? recoveryMedianDays; // info_recovery_median_days (days)
  final double? ulcerPercentile; // info_ulcer_percentile (percentage)
  final int? majorDdCount; // info_major_dd_count (count)

  const DayaniklilikCard({
    this.maxDrawdown5y,
    this.recoveryMedianDays,
    this.ulcerPercentile,
    this.majorDdCount,
  });

  bool get isEmpty =>
      maxDrawdown5y == null &&
      recoveryMedianDays == null &&
      ulcerPercentile == null &&
      majorDdCount == null;

  factory DayaniklilikCard.fromMetrics(Map<String, dynamic> metrics) {
    return DayaniklilikCard(
      maxDrawdown5y: _d(metrics['info_max_drawdown_5y']),
      recoveryMedianDays: _i(metrics['info_recovery_median_days']),
      ulcerPercentile: _d(metrics['info_ulcer_percentile']),
      majorDdCount: _i(metrics['info_major_dd_count']),
    );
  }
}

class EvrimCard {
  final List<String>? yearLabels; // info_year_labels (label[])
  final String? currentCharacterLabel; // info_current_character (label)
  final int? currentCharacterDays; // info_current_character (days)

  const EvrimCard({
    this.yearLabels,
    this.currentCharacterLabel,
    this.currentCharacterDays,
  });

  bool get isEmpty =>
      (yearLabels == null || yearLabels!.isEmpty) &&
      currentCharacterLabel == null;

  factory EvrimCard.fromMetrics(Map<String, dynamic> metrics) {
    final rawLabels = metrics['info_year_labels'];
    return EvrimCard(
      yearLabels: rawLabels is List
          ? rawLabels.map((e) => e.toString()).toList(growable: false)
          : null,
      currentCharacterLabel: metrics['info_current_character_label'] as String?,
      currentCharacterDays: _i(metrics['info_current_character_days']),
    );
  }
}

class HafizaCard {
  final int? lastMarkedPeriodDays; // info_last_marked_period (days)
  final int? lastOutlierDayDays; // info_last_outlier_day (days)
  final int? lastVolumeBurstDays; // info_last_volume_burst (days)
  final int? newFlags90d; // info_new_flags_90d (count)

  const HafizaCard({
    this.lastMarkedPeriodDays,
    this.lastOutlierDayDays,
    this.lastVolumeBurstDays,
    this.newFlags90d,
  });

  bool get isEmpty =>
      lastMarkedPeriodDays == null &&
      lastOutlierDayDays == null &&
      lastVolumeBurstDays == null &&
      newFlags90d == null;

  factory HafizaCard.fromMetrics(Map<String, dynamic> metrics) {
    return HafizaCard(
      lastMarkedPeriodDays: _i(metrics['info_last_marked_period']),
      lastOutlierDayDays: _i(metrics['info_last_outlier_day']),
      lastVolumeBurstDays: _i(metrics['info_last_volume_burst']),
      newFlags90d: _i(metrics['info_new_flags_90d']),
    );
  }
}

// ─────────────────────────────────────────────────────────────────────────
// MotorV2Result — kompozisyon (spec §7)
// ─────────────────────────────────────────────────────────────────────────

class MotorV2Result {
  final int version; // 2
  final String specVersion; // Version Contract, örn. "1.1"
  final String configFingerprint;
  final String computedAt; // ISO 8601 UTC
  final Map<ComponentId, ComponentScore> components;
  final double? compositeRaw;
  final double? compositeFinal;
  final bool ipoModulatorApplied;

  // Ham metrics haritası — YALNIZ bu dosya içinde, kart fabrikalarına
  // geçirmek için tutulur. Widget katmanı buna asla doğrudan erişmez.
  final Map<String, dynamic> _metrics;

  const MotorV2Result({
    required this.version,
    required this.specVersion,
    required this.configFingerprint,
    required this.computedAt,
    required this.components,
    required this.compositeRaw,
    required this.compositeFinal,
    required this.ipoModulatorApplied,
    required Map<String, dynamic> metrics,
  }) : _metrics = metrics;

  MotorV2Result copyWith({
    int? version,
    String? specVersion,
    String? configFingerprint,
    String? computedAt,
    Map<ComponentId, ComponentScore>? components,
    double? compositeRaw,
    double? compositeFinal,
    bool? ipoModulatorApplied,
    Map<String, dynamic>? metrics,
  }) {
    return MotorV2Result(
      version: version ?? this.version,
      specVersion: specVersion ?? this.specVersion,
      configFingerprint: configFingerprint ?? this.configFingerprint,
      computedAt: computedAt ?? this.computedAt,
      components: components ?? this.components,
      compositeRaw: compositeRaw ?? this.compositeRaw,
      compositeFinal: compositeFinal ?? this.compositeFinal,
      ipoModulatorApplied: ipoModulatorApplied ?? this.ipoModulatorApplied,
      metrics: metrics ?? _metrics,
    );
  }

  ComponentScore? component(ComponentId id) => components[id];

  TarihselKonumCard get tarihselKonum =>
      TarihselKonumCard.fromMetrics(_metrics);
  DayaniklilikCard get dayaniklilik => DayaniklilikCard.fromMetrics(_metrics);
  EvrimCard get evrim => EvrimCard.fromMetrics(_metrics);
  HafizaCard get hafiza => HafizaCard.fromMetrics(_metrics);

  /// `motor_v2` alanı Firestore'da yoksa (gölge dönem tamamlanmadı) null döner.
  static MotorV2Result? fromFirestore(dynamic json) {
    if (json is! Map) return null;
    final m = json.map((k, v) => MapEntry(k.toString(), v));

    final rawComponents = m['components'];
    final components = <ComponentId, ComponentScore>{};
    if (rawComponents is Map) {
      rawComponents.forEach((key, value) {
        final id = ComponentId.fromId(key.toString());
        if (id != null && value is Map) {
          components[id] = ComponentScore.fromFirestore(
            value.map((k, v) => MapEntry(k.toString(), v)),
          );
        }
      });
    }

    final rawMetrics = m['metrics'];
    final metrics = rawMetrics is Map
        ? rawMetrics.map((k, v) => MapEntry(k.toString(), v))
        : <String, dynamic>{};

    return MotorV2Result(
      version: _i(m['version']) ?? 2,
      specVersion: (m['spec_version'] as String?) ?? '',
      configFingerprint: (m['config_fingerprint'] as String?) ?? '',
      computedAt: (m['computed_at'] as String?) ?? '',
      components: components,
      compositeRaw: _d(m['composite_raw']),
      compositeFinal: _d(m['composite_final']),
      ipoModulatorApplied: m['ipo_modulator_applied'] == true,
      metrics: metrics,
    );
  }
}

double? _d(dynamic v) => v is num ? v.toDouble() : null;
int? _i(dynamic v) => v is num ? v.toInt() : null;
