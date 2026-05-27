import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

class Il {
  final int id;
  final String ad;
  final List<String> ilceler;

  const Il({required this.id, required this.ad, required this.ilceler});

  factory Il.fromJson(Map<String, dynamic> json) {
    final districts = (json['districts'] as List? ?? []);
    return Il(
      id: json['id'] ?? 0,
      ad: json['name'] ?? '',
      ilceler: districts
          .map((d) => (d['name'] ?? '').toString())
          .where((s) => s.isNotEmpty)
          .toList(),
    );
  }
}

class LokasyonService {
  LokasyonService._();
  static final instance = LokasyonService._();

  static const _cacheKey = 'lokasyon_cache';
  static const _cacheZamanKey = 'lokasyon_cache_zaman';
  static const _cacheSuresi = Duration(days: 30);
  static const _apiUrl =
      'https://turkiyeapi.dev/api/v1/provinces?fields=name,districts';

  List<Il> _iller = [];
  bool _yuklendi = false;

  List<Il> get iller => _iller;
  List<String> get ilAdlari => _iller.map((il) => il.ad).toList();

  List<String> ilceListesi(String ilAdi) {
    try {
      return _iller.firstWhere((il) => il.ad == ilAdi).ilceler;
    } catch (_) {
      return [];
    }
  }

  Future<void> yukle() async {
    if (_yuklendi && _iller.isNotEmpty) return;

    // Önce cache'e bak
    final prefs = await SharedPreferences.getInstance();
    final cacheZaman = prefs.getInt(_cacheZamanKey) ?? 0;
    final simdi = DateTime.now().millisecondsSinceEpoch;
    final cacheGecerli =
        simdi - cacheZaman < _cacheSuresi.inMilliseconds;

    if (cacheGecerli) {
      final cacheJson = prefs.getString(_cacheKey);
      if (cacheJson != null) {
        try {
          final liste = (jsonDecode(cacheJson) as List)
              .map((e) => Il.fromJson(e))
              .toList();
          if (liste.isNotEmpty) {
            _iller = liste;
            _yuklendi = true;
            return;
          }
        } catch (_) {}
      }
    }

    // API'den çek
    try {
      final response = await http
          .get(Uri.parse(_apiUrl))
          .timeout(const Duration(seconds: 10));

      if (response.statusCode == 200) {
        final json = jsonDecode(response.body);
        final data = json['data'] as List? ?? [];
        _iller = data.map((e) => Il.fromJson(e)).toList();
        _iller.sort((a, b) => a.ad.compareTo(b.ad));
        _yuklendi = true;

        // Cache'e kaydet
        await prefs.setString(_cacheKey, jsonEncode(data));
        await prefs.setInt(_cacheZamanKey, simdi);
      }
    } catch (e) {
      debugPrint('LokasyonService hata: $e');
      // API başarısız — cache varsa onu kullan (süresi geçmiş olsa bile)
      final cacheJson = prefs.getString(_cacheKey);
      if (cacheJson != null) {
        try {
          _iller = (jsonDecode(cacheJson) as List)
              .map((e) => Il.fromJson(e))
              .toList();
          _yuklendi = _iller.isNotEmpty;
        } catch (_) {}
      }
    }
  }
}
