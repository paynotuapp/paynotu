import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

// ── Sıralama yönü ────────────────────────────────────────────────────────────

enum SiralaYon {
  artan,
  azalan,
}

extension SiralaYonX on SiralaYon {
  String get label {
    switch (this) {
      case SiralaYon.artan:  return 'Artan';
      case SiralaYon.azalan: return 'Azalan';
    }
  }

  IconData get ikon {
    switch (this) {
      case SiralaYon.artan:  return Icons.arrow_upward;
      case SiralaYon.azalan: return Icons.arrow_downward;
    }
  }
}

// ── Sıralama alanı ────────────────────────────────────────────────────────────

enum SiralaAlan {
  adaGore,
  halkSkoru,
  anomaliSkoru,
  paynotu,
}

extension SiralaAlanX on SiralaAlan {
  String get label {
    switch (this) {
      case SiralaAlan.adaGore:      return 'Ada Göre Sırala';
      case SiralaAlan.halkSkoru:    return 'Halk Skoruna Göre';
      case SiralaAlan.anomaliSkoru: return 'Anomali Skoruna Göre';
      case SiralaAlan.paynotu:      return 'PayNotu\'na Göre';
    }
  }

  IconData get ikon {
    switch (this) {
      case SiralaAlan.adaGore:      return Icons.sort_by_alpha;
      case SiralaAlan.halkSkoru:    return Icons.star_border;
      case SiralaAlan.anomaliSkoru: return Icons.analytics_outlined;
      case SiralaAlan.paynotu:      return Icons.speed_outlined;
    }
  }
}

// ── Filtre / sıralama durumu ─────────────────────────────────────────────────

class HisseFiltreDurum {
  final SiralaYon  siralaYon;
  final SiralaAlan siralaAlan;

  const HisseFiltreDurum({
    this.siralaYon  = SiralaYon.artan,
    this.siralaAlan = SiralaAlan.adaGore,
  });

  /// Varsayılandan herhangi bir fark var mı? (panel rozeti / ikon için)
  bool get aktif =>
      siralaYon  != SiralaYon.artan ||
      siralaAlan != SiralaAlan.adaGore;

  /// Eski kullanım adı korunuyor; artık sıralama seçimi de aktif durum sayılır.
  bool get filtreAktif => aktif;

  HisseFiltreDurum copyWith({
    SiralaYon?  siralaYon,
    SiralaAlan? siralaAlan,
  }) =>
      HisseFiltreDurum(
        siralaYon:  siralaYon  ?? this.siralaYon,
        siralaAlan: siralaAlan ?? this.siralaAlan,
      );

  // ── SharedPreferences ────────────────────────────────────────────────────

  static HisseFiltreDurum fromPrefs(SharedPreferences prefs) {
    final yeniYonIdx  = prefs.getInt('filtre_sirala_yon');
    final yeniAlanIdx = prefs.getInt('filtre_sirala_alan');

    if (yeniYonIdx != null || yeniAlanIdx != null) {
      final yonIdx = (yeniYonIdx ?? 0)
          .clamp(0, SiralaYon.values.length - 1)
          .toInt();
      final alanIdx = (yeniAlanIdx ?? 0)
          .clamp(0, SiralaAlan.values.length - 1)
          .toInt();
      return HisseFiltreDurum(
        siralaYon:  SiralaYon.values[yonIdx],
        siralaAlan: SiralaAlan.values[alanIdx],
      );
    }

    // Eski tek enum'lu kayıtları mümkün olduğunca doğru şekilde yeni yapıya taşı.
    final eskiSirala = prefs.getInt('filtre_sirala') ?? 0;
    switch (eskiSirala) {
      case 1: // Eski: adaGoreAzalan
        return const HisseFiltreDurum(
          siralaYon: SiralaYon.azalan,
          siralaAlan: SiralaAlan.adaGore,
        );
      case 2: // Eski: azalanPay
        return const HisseFiltreDurum(
          siralaYon: SiralaYon.azalan,
          siralaAlan: SiralaAlan.paynotu,
        );
      case 3: // Eski: artanPay
        return const HisseFiltreDurum(
          siralaYon: SiralaYon.artan,
          siralaAlan: SiralaAlan.paynotu,
        );
      case 6: // Eski: finansalTaban
        return const HisseFiltreDurum(
          siralaYon: SiralaYon.azalan,
          siralaAlan: SiralaAlan.anomaliSkoru,
        );
      case 0:
      default:
        return const HisseFiltreDurum();
    }
  }

  Future<void> kaydet(SharedPreferences prefs) async {
    await prefs.setInt('filtre_sirala_yon',  siralaYon.index);
    await prefs.setInt('filtre_sirala_alan', siralaAlan.index);

    // Eski filtre kayıtları yeni panelde kullanılmıyor.
    await prefs.remove('filtre_sirala');
    await prefs.remove('filtre_puan');
    await prefs.remove('filtre_yorum');
  }
}
