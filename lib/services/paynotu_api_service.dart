import 'dart:convert';
import 'package:http/http.dart' as http;

class PayNotuApiService {
  static const String _baseUrl =
      'http://192.168.1.2:8000';

  static const Duration _timeout = Duration(seconds: 15);

  // ── /score/{ticker} ──────────────────────────────────────────────────────────

  /// Bir hisse için tam PayNotu skorunu hesaplar.
  /// Backend'den canlı hesaplama döner (Firestore cache değil).
  static Future<PayNotuSkorSonucu> skorHesapla(String ticker) async {
    final response = await http
        .get(Uri.parse('$_baseUrl/score/$ticker'))
        .timeout(_timeout);

    if (response.statusCode == 200) {
      return PayNotuSkorSonucu.fromJson(
          jsonDecode(response.body) as Map<String, dynamic>);
    }
    throw ApiException(response.statusCode, response.body);
  }

  // ── /score/{ticker}/financial-only ──────────────────────────────────────────

  /// Sadece finansal skoru döner — hızlı test veya ön yükleme için.
  static Future<Map<String, dynamic>> finansalSkorAl(String ticker) async {
    final response = await http
        .get(Uri.parse('$_baseUrl/score/$ticker/financial-only'))
        .timeout(_timeout);

    if (response.statusCode == 200) {
      return jsonDecode(response.body) as Map<String, dynamic>;
    }
    throw ApiException(response.statusCode, response.body);
  }
}

// ── Model ────────────────────────────────────────────────────────────────────

class PayNotuSkorSonucu {
  final String ticker;
  final double? paynotuScore;
  final double financialScore;
  final double emotionalScore;
  final double emotionalGrip;
  final double gripIntensity;
  final bool isSentimentDivergence;
  final bool hasReviews;
  final Map<String, dynamic> details;
  final Map<String, dynamic> temel;

  PayNotuSkorSonucu({
    required this.ticker,
    required this.paynotuScore,
    required this.financialScore,
    required this.emotionalScore,
    required this.emotionalGrip,
    required this.gripIntensity,
    required this.isSentimentDivergence,
    required this.hasReviews,
    required this.details,
    required this.temel,
  });

  factory PayNotuSkorSonucu.fromJson(Map<String, dynamic> json) {
    return PayNotuSkorSonucu(
      ticker:         json['ticker'] as String,
      paynotuScore:   (json['paynotu_score'] as num?)?.toDouble(),
      financialScore: ((json['raw_spek_score'] ?? json['spek_score']) ?? 0.0).toDouble(),
      emotionalScore: (json['emotional_score'] ?? 0.0).toDouble(),
      emotionalGrip:  (json['emotional_grip']  ?? 0.0).toDouble(),
      gripIntensity:  (json['grip_intensity']  ?? 0.0).toDouble(),
      isSentimentDivergence: json['is_sentiment_divergence'] as bool? ?? false,
      hasReviews:     json['has_reviews']      as bool? ?? false,
      details:        (json['details'] as Map<String, dynamic>?) ?? {},
      temel:          (json['temel']   as Map<String, dynamic>?) ?? {},
    );
  }

  // Kolaylık erişimleri — details içinden
  int    get speculativeDays  => (details['speculative_days'] ?? 0) as int;
  double get topsisScore      => (details['topsis'] ?? 0.0).toDouble();
  double get pumpSimilarity   => (details['pump_similarity'] ?? 0.0).toDouble();
  bool   get ipoPenaltyApplied => details['ipo_penalty_applied'] as bool? ?? false;

  // temel içinden
  double get roe          => (temel['roe']          ?? 0.0).toDouble();
  double get karMarji     => (temel['kar_marji']     ?? 0.0).toDouble();
  double get pdDd         => (temel['pd_dd']         ?? 0.0).toDouble();
  double get borcFavok    => (temel['borc_favok']    ?? 0.0).toDouble();
  String get temelPeriod  => (temel['period']        ?? '') as String;
  String get temelKaynak  => (temel['kaynak']        ?? '') as String;
}

// ── Hata sınıfı ──────────────────────────────────────────────────────────────

class ApiException implements Exception {
  final int statusCode;
  final String body;
  ApiException(this.statusCode, this.body);

  @override
  String toString() => 'ApiException($statusCode): $body';
}
