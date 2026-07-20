/// PayNotu Katman B — segment (senaryo) modelleri.
///
/// Kaynak: backend/models/scenario.py (ScenarioType, AnomalyComponents,
/// ScenarioSegment, ScenarioBundle — birebir Dart karşılığı) ve
/// backend/docs/paynotu_motor_v2_spec_v1_1.md §9 (SegmentCard'ın 11 türetilmiş
/// `seg_*` alanı). Firestore yolu: `hisseler/{ticker}.scenarios`.
///
/// Madde 12: segment seçimi yalnız hangi hazır verinin gösterildiğini
/// değiştirir; hiçbir alan Dart'ta OHLCV'den yeniden hesaplanmaz.
library;

enum ScenarioType {
  pump('pump'),
  accumulation('accumulation'),
  distribution('distribution'),
  breakout('breakout'),
  manipulation('manipulation'),
  consolidation('consolidation'),
  ipoPeriod('ipo_period'),
  spkPumpDump('spk_pump_dump');

  final String value;
  const ScenarioType(this.value);

  static ScenarioType? fromValue(dynamic v) {
    if (v is! String) return null;
    for (final t in ScenarioType.values) {
      if (t.value == v) return t;
    }
    return null;
  }
}

/// Segment'e özgü alt skorlar (0.0-1.0). SegmentCard'ın 4 grubundan
/// Fiyat/Hacim/Volatilite/Şekil satırlarını besler (Şekil ← pump).
class AnomalyComponents {
  final double fiyat;
  final double hacim;
  final double volatilite;
  final double pump;

  const AnomalyComponents({
    required this.fiyat,
    required this.hacim,
    required this.volatilite,
    required this.pump,
  });

  factory AnomalyComponents.fromFirestore(Map<String, dynamic> json) {
    return AnomalyComponents(
      fiyat: (json['fiyat'] as num?)?.toDouble() ?? 0.0,
      hacim: (json['hacim'] as num?)?.toDouble() ?? 0.0,
      volatilite: (json['volatilite'] as num?)?.toDouble() ?? 0.0,
      pump: (json['pump'] as num?)?.toDouble() ?? 0.0,
    );
  }
}

class ScenarioSegment {
  final ScenarioType? type;
  final int startIndex;
  final int endIndex;
  final String startDate; // ISO 8601 (YYYY-MM-DD)
  final String endDate;
  final String title;
  final String description;
  final double confidence; // 0.0-1.0
  final AnomalyComponents subscores;

  const ScenarioSegment({
    required this.type,
    required this.startIndex,
    required this.endIndex,
    required this.startDate,
    required this.endDate,
    required this.title,
    required this.description,
    required this.confidence,
    required this.subscores,
  });

  factory ScenarioSegment.fromFirestore(Map<String, dynamic> json) {
    final rawSub = json['subscores'];
    return ScenarioSegment(
      type: ScenarioType.fromValue(json['type']),
      startIndex: (json['start_index'] as num?)?.toInt() ?? 0,
      endIndex: (json['end_index'] as num?)?.toInt() ?? 0,
      startDate: (json['start_date'] as String?) ?? '',
      endDate: (json['end_date'] as String?) ?? '',
      title: (json['title'] as String?) ?? '',
      description: (json['description'] as String?) ?? '',
      confidence: (json['confidence'] as num?)?.toDouble() ?? 0.0,
      subscores: rawSub is Map
          ? AnomalyComponents.fromFirestore(
              rawSub.map((k, v) => MapEntry(k.toString(), v)),
            )
          : const AnomalyComponents(
              fiyat: 0.0, hacim: 0.0, volatilite: 0.0, pump: 0.0),
    );
  }

  /// "X gün önce başladı" — bugünden startDate'e işlem/takvim günü farkı.
  int? get baslangicGunOnce {
    final d = DateTime.tryParse(startDate);
    if (d == null) return null;
    return DateTime.now().difference(d).inDays;
  }

  /// "Y gün sürdü" — startDate ile endDate arası.
  int? get sureGun {
    final s = DateTime.tryParse(startDate);
    final e = DateTime.tryParse(endDate);
    if (s == null || e == null) return null;
    return e.difference(s).inDays;
  }
}

class ScenarioBundle {
  final List<ScenarioSegment> segments; // kronolojik sıralı
  final int totalWindowDays;
  final String classifierVersion;

  const ScenarioBundle({
    required this.segments,
    required this.totalWindowDays,
    required this.classifierVersion,
  });

  bool get isEmpty => segments.isEmpty;

  /// `hisseler/{ticker}.scenarios` alanı yoksa/boşsa boş bundle döner.
  factory ScenarioBundle.fromFirestore(dynamic json) {
    if (json is! Map) {
      return const ScenarioBundle(
          segments: [], totalWindowDays: 0, classifierVersion: '');
    }
    final m = json.map((k, v) => MapEntry(k.toString(), v));
    final rawSegments = m['segments'];
    final segments = <ScenarioSegment>[];
    if (rawSegments is List) {
      for (final s in rawSegments) {
        if (s is Map) {
          segments.add(
            ScenarioSegment.fromFirestore(
              s.map((k, v) => MapEntry(k.toString(), v)),
            ),
          );
        }
      }
    }
    return ScenarioBundle(
      segments: segments,
      totalWindowDays: (m['total_window_days'] as num?)?.toInt() ?? 0,
      classifierVersion: (m['classifier_version'] as String?) ?? '',
    );
  }
}

/// Katman B segment kartı (spec §9) — 11 türetilmiş `seg_*` alanın tamamı
/// typed sınıfta karşılığını bulur. Bugün itibarıyla `scenarios` map'i bu
/// 11 alanı HENÜZ taşımıyor (yalnız title/description/confidence/tarihler
/// ve 4 grup subscore var) — backend genişletmesi ayrı iş emridir; o ana
/// kadar bu alanlar null kalır ve UI'da gizlenir (Madde 12 uyumlu, UI kırılmaz).
class SegmentCard {
  final String title;
  final double confidence;
  final int? baslangicGunOnce;
  final int? sureGun;

  // Dört grup — mevcut kaynak: ScenarioSegment.subscores (0-1 normalize)
  final double fiyatGrubu;
  final double hacimGrubu;
  final double volatiliteGrubu;
  final double sekilGrubu; // ← subscores.pump

  // 11 türetilmiş satır (spec §9) — `scenarios` map'te henüz yok, hepsi null
  final double? segTotalReturn;
  final double? segExcessVsXu100;
  final double? segSharpestDayPercent;
  final String? segSharpestDayDate;
  final double? segVolumeMultiple;
  final double? segVolumeGini;
  final double? segVolVsOwnMedian;
  final double? segIntradayRange;
  final double? segRsiExtreme;
  final int? segUpStreakMax;
  final double? segPeakRetrace;
  final double? segPostPeakVolume;

  const SegmentCard({
    required this.title,
    required this.confidence,
    required this.baslangicGunOnce,
    required this.sureGun,
    required this.fiyatGrubu,
    required this.hacimGrubu,
    required this.volatiliteGrubu,
    required this.sekilGrubu,
    this.segTotalReturn,
    this.segExcessVsXu100,
    this.segSharpestDayPercent,
    this.segSharpestDayDate,
    this.segVolumeMultiple,
    this.segVolumeGini,
    this.segVolVsOwnMedian,
    this.segIntradayRange,
    this.segRsiExtreme,
    this.segUpStreakMax,
    this.segPeakRetrace,
    this.segPostPeakVolume,
  });

  /// [extra] — segment'in `scenarios` map'indeki kendi node'unda ileride
  /// eklenebilecek `seg_*` alanları (bugün boş dict). Backend genişleyince
  /// bu factory'nin gövdesi değişir, çağıran widget değişmez.
  factory SegmentCard.fromSegment(
    ScenarioSegment segment, {
    Map<String, dynamic> extra = const {},
  }) {
    return SegmentCard(
      title: segment.title,
      confidence: segment.confidence,
      baslangicGunOnce: segment.baslangicGunOnce,
      sureGun: segment.sureGun,
      fiyatGrubu: segment.subscores.fiyat,
      hacimGrubu: segment.subscores.hacim,
      volatiliteGrubu: segment.subscores.volatilite,
      sekilGrubu: segment.subscores.pump,
      segTotalReturn: (extra['seg_total_return'] as num?)?.toDouble(),
      segExcessVsXu100: (extra['seg_excess_vs_xu100'] as num?)?.toDouble(),
      segSharpestDayPercent:
          (extra['seg_sharpest_day_percent'] as num?)?.toDouble(),
      segSharpestDayDate: extra['seg_sharpest_day_date'] as String?,
      segVolumeMultiple: (extra['seg_volume_multiple'] as num?)?.toDouble(),
      segVolumeGini: (extra['seg_volume_gini'] as num?)?.toDouble(),
      segVolVsOwnMedian: (extra['seg_vol_vs_own_median'] as num?)?.toDouble(),
      segIntradayRange: (extra['seg_intraday_range'] as num?)?.toDouble(),
      segRsiExtreme: (extra['seg_rsi_extreme'] as num?)?.toDouble(),
      segUpStreakMax: (extra['seg_up_streak_max'] as num?)?.toInt(),
      segPeakRetrace: (extra['seg_peak_retrace'] as num?)?.toDouble(),
      segPostPeakVolume: (extra['seg_post_peak_volume'] as num?)?.toDouble(),
    );
  }
}
