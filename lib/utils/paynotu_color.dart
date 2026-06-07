import 'package:flutter/material.dart';

// ── Renk sabitleri ────────────────────────────────────────────────────────────

const Color _kKirmizi = Color(0xFFE53935);
const Color _kTuruncu = Color(0xFFFF6F00);
const Color _kSari    = Color(0xFFFFD600);
const Color _kYesil   = Color(0xFF2E7D32);

// ── Firestore dağılım eşikleri (610 aktif hisse, 2026-04-11) ─────────────────
//
//   Min 1.30  |  P25 2.96  |  P50 3.44  |  P75 3.95  |  P90 4.36  |  Max 5.62
//
//   Alt %25  → yeşil bölge     (0   – P25)
//   %25–50   → sarı bölge      (P25 – P50)
//   %50–75   → turuncu bölge   (P50 – P75)
//   Üst %25  → kırmızı bölge   (P75 –  ∞ ; tam kırmızı P90'dan itibaren)

const double _p25 = 2.96;
const double _p50 = 3.44;
const double _p75 = 3.95;
const double _p90 = 4.36;   // tam kırmızı eşiği

// ── Spek günü okuyucu ─────────────────────────────────────────────────────────

/// Firestore data map'inden spek_gun değerini çıkarır.
/// Önce [spek_gun_sayisi] field'ına bakar;
/// bulamazsa [finansal_taban] map içindeki [spek_gun] değerini kullanır.
int spekGunAl(Map<String, dynamic> data) {
  final v = data['spek_gun_sayisi'];
  if (v != null) return (v as num).toInt();

  final ft = data['finansal_taban'];
  if (ft is Map) {
    final sg = ft['spek_gun'];
    if (sg != null) return (sg as num).toInt();
  }

  return 0;
}

// ── İç hesaplama fonksiyonları ────────────────────────────────────────────────


/// Skoru renk bantlarına çevirir — bantlar arası [Color.lerp] ile yumuşak geçiş.
///
/// 0.00 – P25(2.96) → Yeşil (sabit)
/// P25  – P50(3.44) → Yeşil → Sarı gradyanı
/// P50  – P75(3.95) → Sarı → Turuncu gradyanı
/// P75  – P90(4.36) → Turuncu → Kırmızı gradyanı
/// P90  – 10.0      → Kırmızı (sabit)
Color _skorToColor(double s) {
  final c = s.clamp(0.0, 10.0);
  if (c <= _p25) return _kYesil;
  if (c <= _p50) return Color.lerp(_kYesil,   _kSari,    (c - _p25) / (_p50 - _p25))!;
  if (c <= _p75) return Color.lerp(_kSari,    _kTuruncu, (c - _p50) / (_p75 - _p50))!;
  if (c <= _p90) return Color.lerp(_kTuruncu, _kKirmizi, (c - _p75) / (_p90 - _p75))!;
  return _kKirmizi;
}

// ── Sektör renk paleti ────────────────────────────────────────────────────────

/// Hisse sektörüne göre avatar arka plan rengi döndürür.
/// Logo olmayan hisseler için `_logoFallback` tarafından kullanılır.
Color sektorRenk(String sector) {
  switch (sector.trim()) {
    case 'Financial Services':     return const Color(0xFF1565C0); // Koyu mavi
    case 'Industrials':            return const Color(0xFF546E7A); // Çelik grisi
    case 'Basic Materials':        return const Color(0xFF5D4037); // Kahverengi
    case 'Consumer Cyclical':      return const Color(0xFF6A1B9A); // Mor
    case 'Consumer Defensive':     return const Color(0xFF00695C); // Koyu teal
    case 'Technology':             return const Color(0xFF0097A7); // Cyan
    case 'Energy':                 return const Color(0xFFE65100); // Turuncu
    case 'Healthcare':             return const Color(0xFFC62828); // Kırmızı
    case 'Real Estate':            return const Color(0xFFF57F17); // Amber
    case 'Communication Services': return const Color(0xFF283593); // İndigo
    case 'Utilities':              return const Color(0xFF0277BD); // Açık mavi
    default:                       return const Color(0xFF616161); // Nötr gri
  }
}

// ── Ana API ───────────────────────────────────────────────────────────────────

/// PayNotu kutusu için dinamik renk hesaplayıcı.
///
/// [skor]    → paynotu_skoru (0.0–10.0)
/// [spekGun] → spek_gun_sayisi (0+); 0 ise düzeltme uygulanmaz
///
/// Örnek sonuçlar (gerçek dağılıma göre):
///   skor < 2.96                 → Yeşil     (alt %25)
///   2.96 ≤ skor < 3.44         → Sarı      (%25–50)
///   3.44 ≤ skor < 3.95         → Turuncu   (%50–75)
///   skor ≥ 3.95 (tam → 4.36)  → Kırmızı   (üst %25)
Color getPayNotuColor(double skor) =>
    _skorToColor(skor.clamp(0.0, 10.0));
