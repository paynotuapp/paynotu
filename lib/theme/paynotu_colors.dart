import 'package:flutter/material.dart';

/// PayNotu skoruna göre 9 adımlı renk sistemi.
///
/// Skor yönü: düşük = temiz/sakin, yüksek = riskli/dikkat.
/// Renk yönü: 0'a yakın koyu yeşil → 10'a yakın koyu kırmızı.
///
/// Bantlar (3 ana × 3 alt):
///   0.00 – 1.11  Koyu Yeşil   (en temiz)
///   1.12 – 2.22  Yeşil
///   2.23 – 3.33  Açık Yeşil
///   3.34 – 4.44  Limon Sarı   (yeşile çalan geçiş)
///   4.45 – 5.55  Sarı
///   5.56 – 6.67  Koyu Sarı    (turuncuya yaklaşıyor)
///   6.68 – 7.78  Turuncu
///   7.79 – 8.89  Kırmızı
///   8.90 – 10.00 Koyu Kırmızı (en riskli)
abstract final class PayNotuColors {
  // ─── 9 adımlı renk paleti ───────────────────────────────────────────────
  // Renkler yalnızca burada tanımlanır; widget'lar forScore() ile okur.

  static const Color _darkGreen   = Color(0xFF1B5E20); // 0.00–1.11
  static const Color _green       = Color(0xFF388E3C); // 1.12–2.22
  static const Color _lightGreen  = Color(0xFF81C784); // 2.23–3.33
  static const Color _lemonYellow = Color(0xFFCDDC39); // 3.34–4.44
  static const Color _yellow      = Color(0xFFFFEB3B); // 4.45–5.55
  static const Color _darkYellow  = Color(0xFFFFC107); // 5.56–6.67
  static const Color _orange      = Color(0xFFFF9800); // 6.68–7.78
  static const Color _red         = Color(0xFFE53935); // 7.79–8.89
  static const Color _darkRed     = Color(0xFFB71C1C); // 8.90–10.00

  static const List<Color> _steps = [
    _darkGreen,
    _green,
    _lightGreen,
    _lemonYellow,
    _yellow,
    _darkYellow,
    _orange,
    _red,
    _darkRed,
  ];

  // ─── Eşik sınırları (9 adım için 8 sınır) ──────────────────────────────
  static const double _step = 10.0 / 9.0; // ≈ 1.111

  // ─── Public API ─────────────────────────────────────────────────────────

  /// [score] değerine karşılık gelen rengi döndürür.
  /// [score] null ise (IPO / veri yok) nötr gri döner.
  static Color forScore(double? score) {
    if (score == null) return const Color(0xFF9E9E9E); // nötr gri
    final clamped = score.clamp(0.0, 10.0);
    final index = (clamped / _step).floor().clamp(0, _steps.length - 1);
    return _steps[index];
  }

  /// Skora karşılık gelen rengin üzerine yazılacak metin rengi.
  /// Koyu arka planlarda beyaz, açık arka planlarda siyah döner.
  static Color textColorFor(double? score) {
    if (score == null) return const Color(0xFF212121);
    final bg = forScore(score);
    return ThemeData.estimateBrightnessForColor(bg) == Brightness.dark
        ? const Color(0xFFFFFFFF)
        : const Color(0xFF212121);
  }

  /// Skora karşılık gelen Türkçe etiket.
  static String labelFor(double? score) {
    if (score == null) return 'Veri Yok';
    final clamped = score.clamp(0.0, 10.0);
    if (clamped < 3.34) return 'Sakin';
    if (clamped < 6.68) return 'Orta';
    return 'Dikkat';
  }
}
