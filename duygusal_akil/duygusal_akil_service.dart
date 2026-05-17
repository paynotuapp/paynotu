// duygusal_akil_service.dart
// PayNotu projesine eklenecek servis katmanı
// lib/services/duygusal_akil_service.dart

import 'dart:convert';
import 'package:http/http.dart' as http;

class DuygusalAkilService {
  // Lokal test için: http://localhost:8000
  // Railway deploy sonrası: https://duygusal-akil.up.railway.app
  static const String _baseUrl = 'http://localhost:8000';

  /// Yorum gönderilmeden önce içerik kontrolü yapar.
  /// TextField onChange'de çağrılır.
  /// true = gönderilebilir, false = engellendi
  static Future<IcerikKontrolSonucu> icerikKontrol(String metin) async {
    try {
      final response = await http.post(
        Uri.parse('$_baseUrl/icerik-kontrol'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'metin': metin}),
      );

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        return IcerikKontrolSonucu.fromJson(data);
      }
      return IcerikKontrolSonucu.temiz();
    } catch (e) {
      // Servis erişilemezse engelleme yapma
      return IcerikKontrolSonucu.temiz();
    }
  }

  /// Yorum submit edildiğinde çağrılır.
  /// Skoru hesaplar, Firebase'e kaydedilecek değerleri döner.
  static Future<SkorSonucu?> yorumuSkorla({
    required String yorumMetni,
    required double puan,
    required String kullaniciId,
    required int hesapYasGun,
    required int toplamYorumSayisi,
    required double yorumCesitliligi,
    required int yorumTimestamp,
    required int faydaliOy,
    required int faydaliOlmayanOy,
    required String hisseKodu,
  }) async {
    try {
      final response = await http.post(
        Uri.parse('$_baseUrl/yorumu-skorla'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'yorum_metni': yorumMetni,
          'puan': puan,
          'kullanici_id': kullaniciId,
          'hesap_yas_gun': hesapYasGun,
          'toplam_yorum_sayisi': toplamYorumSayisi,
          'yorum_cesitliligi': yorumCesitliligi,
          'yorum_timestamp': yorumTimestamp,
          'faydali_oy': faydaliOy,
          'faydali_olmayan_oy': faydaliOlmayanOy,
          'hisse_kodu': hisseKodu,
        }),
      );

      if (response.statusCode == 200) {
        return SkorSonucu.fromJson(jsonDecode(response.body));
      }

      if (response.statusCode == 400) {
        // İçerik engellendi
        final hata = jsonDecode(response.body);
        throw Exception(hata['detail']);
      }

      return null;
    } catch (e) {
      rethrow;
    }
  }
}

// --- Model Sınıfları ---

class IcerikKontrolSonucu {
  final String durum; // temiz | şüpheli | engellendi
  final String aciklama;
  final int riskPuani;

  IcerikKontrolSonucu({
    required this.durum,
    required this.aciklama,
    required this.riskPuani,
  });

  bool get gonderilebildi => durum != 'engellendi';
  bool get supheliMi => durum == 'şüpheli';

  factory IcerikKontrolSonucu.fromJson(Map<String, dynamic> json) {
    return IcerikKontrolSonucu(
      durum: json['durum'] ?? 'temiz',
      aciklama: json['aciklama'] ?? '',
      riskPuani: json['risk_puani'] ?? 0,
    );
  }

  factory IcerikKontrolSonucu.temiz() {
    return IcerikKontrolSonucu(
      durum: 'temiz',
      aciklama: 'İçerik uygun',
      riskPuani: 0,
    );
  }
}

class SkorSonucu {
  final double guvenSkoru;      // 0-100
  final double itibarSkoru;     // 0-10
  final String manipulasyonRiski; // Düşük | Orta | Yüksek
  final String duyguTonu;       // Pozitif | Negatif | Nötr
  final String icerikDurumu;    // temiz | şüpheli | engellendi
  final double zamanAgirlik;    // 0-1
  final String aciklama;

  SkorSonucu({
    required this.guvenSkoru,
    required this.itibarSkoru,
    required this.manipulasyonRiski,
    required this.duyguTonu,
    required this.icerikDurumu,
    required this.zamanAgirlik,
    required this.aciklama,
  });

  factory SkorSonucu.fromJson(Map<String, dynamic> json) {
    return SkorSonucu(
      guvenSkoru: (json['guven_skoru'] ?? 0).toDouble(),
      itibarSkoru: (json['itibar_skoru'] ?? 0).toDouble(),
      manipulasyonRiski: json['manipulasyon_riski'] ?? 'Düşük',
      duyguTonu: json['duygu_tonu'] ?? 'Nötr',
      icerikDurumu: json['icerik_durumu'] ?? 'temiz',
      zamanAgirlik: (json['zaman_agirlik'] ?? 1.0).toDouble(),
      aciklama: json['aciklama'] ?? '',
    );
  }

  /// Rozet sistemi için profil etiketi
  String get rozetEtiketi {
    if (guvenSkoru >= 80) return '🟡 OY';
    if (guvenSkoru >= 65) return '🟣 PY';
    if (guvenSkoru >= 50) return '🔵 UY';
    if (guvenSkoru >= 30) return '🟤 KY';
    return '⚫ Yeni Ses';
  }
}
