import 'package:flutter/material.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:intl/intl.dart';

/// Halk Paneli
/// ───────────
/// Analiz sekmesinin "Halk" alt sekmesi.
/// Söz Hakkı kullananların değerlendirmelerini salt-okunur olarak gösterir.
///
/// İçerik:
///   • 3 metric kart: Pozitif yorum %, Toplam yorum, Ortalama puan
///   • Duygu dağılım çubuğu (NLP duygu_tonu üzerinden, fallback: yıldız)
///   • 5 seviyeli yıldız dağılım barları (filtre olarak da çalışır)
///   • Yorum listesi: ilk 10 + "Daha fazla göster"
///   • Yorum kartına tıklayınca → kullanıcı bilgi bottom sheet açılır
///
/// Veri kaynakları:
///   • Hisseye ait yorumlar: hisseler/{symbol}/yorumlar
///   • Yorum sahibinin profili: users/{uid}
///
/// Anayasa:
///   • Immutable veri modelleri (_YorumModel, _HalkIstatistik)
///   • Atomic Firestore okuma (StreamBuilder)
///   • Strongly typed (`Map<String, dynamic>` doğrudan dolaşmaz)
///   • Hardcoded renk yok — Theme.of(context).colorScheme
class HalkPanel extends StatefulWidget {
  final String symbol;
  const HalkPanel({super.key, required this.symbol});

  @override
  State<HalkPanel> createState() => _HalkPanelState();
}

class _HalkPanelState extends State<HalkPanel> {
  int _gosterilen = 10;
  int? _filtre;

  @override
  Widget build(BuildContext context) {
    return StreamBuilder<QuerySnapshot>(
      stream: FirebaseFirestore.instance
          .collection('hisseler')
          .doc(widget.symbol)
          .collection('yorumlar')
          .orderBy('tarih', descending: true)
          .snapshots(),
      builder: (context, snap) {
        if (snap.connectionState == ConnectionState.waiting) {
          return Center(
            child: CircularProgressIndicator(
              color: Theme.of(context).colorScheme.primary,
            ),
          );
        }

        if (snap.hasError) {
          return Center(
            child: Text(
              'Yorumlar yüklenemedi.',
              style: TextStyle(
                color: Theme.of(context).colorScheme.onSurfaceVariant,
              ),
            ),
          );
        }

        final docs = snap.data?.docs ?? [];

        if (docs.isEmpty) {
          return _BosListe();
        }

        final yorumlar =
            docs.map((d) => _YorumModel.fromDoc(d)).toList(growable: false);
        final istat = _HalkIstatistik.hesapla(yorumlar);

        final filtreli = _filtre == null
            ? yorumlar
            : yorumlar.where((y) => y.puan == _filtre).toList(growable: false);

        return ListView(
          padding: const EdgeInsets.all(16),
          children: [
            _OzetKartlari(istatistik: istat),
            const SizedBox(height: 16),
            _DuyguDagilimi(istatistik: istat),
            const SizedBox(height: 16),
            _DagilimBarlari(
              istatistik: istat,
              secili: _filtre,
              onSecili: (yildiz) {
                setState(() {
                  _filtre = (_filtre == yildiz) ? null : yildiz;
                  _gosterilen = 10;
                });
              },
            ),
            const SizedBox(height: 14),
            _FiltreEtiketi(
              filtre: _filtre,
              toplam: filtreli.length,
              onTemizle: () => setState(() {
                _filtre = null;
                _gosterilen = 10;
              }),
            ),
            const SizedBox(height: 8),
            ...filtreli
                .take(_gosterilen)
                .map((y) => _YorumKarti(yorum: y, symbol: widget.symbol)),
            if (filtreli.length > _gosterilen) ...[
              const SizedBox(height: 8),
              Center(
                child: TextButton.icon(
                  onPressed: () => setState(() => _gosterilen += 10),
                  icon: const Icon(Icons.expand_more, size: 18),
                  label: Text(
                    'Daha fazla göster (${filtreli.length - _gosterilen} yorum daha)',
                    style: const TextStyle(fontSize: 12),
                  ),
                ),
              ),
            ],
            const SizedBox(height: 24),
          ],
        );
      },
    );
  }
}

class _BosListe extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.chat_bubble_outline,
                size: 56, color: cs.onSurfaceVariant),
            const SizedBox(height: 12),
            Text('Henüz değerlendirme yok',
                style: TextStyle(
                    fontSize: 14,
                    fontWeight: FontWeight.w500,
                    color: cs.onSurface)),
            const SizedBox(height: 4),
            Text(
              'Söz Hakkı Kullan butonuyla ilk\ndeğerlendiren ol.',
              style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant),
              textAlign: TextAlign.center,
            ),
          ],
        ),
      ),
    );
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// İmmutable Veri Modelleri
// ─────────────────────────────────────────────────────────────────────────────

/// Yorum dokümanında `duygu_tonu` Duygusal Akıl servisinden gelir.
/// Eski/migration olmamış yorumlarda olmayabilir, o durumda yıldıza göre tahmin.
enum DuyguTonu { pozitif, notr, negatif }

@immutable
class _YorumModel {
  final String id;
  final String uid;
  final int puan;
  final String displayName;
  final String yorum;
  final String? position;
  final DateTime? tarih;
  final int faydaliOy;
  final int faydaliOlmayanOy;
  final List<String> oylayanlar;
  final bool maviTik;
  final DuyguTonu duyguTonu;

  const _YorumModel({
    required this.id,
    required this.uid,
    required this.puan,
    required this.displayName,
    required this.yorum,
    required this.position,
    required this.tarih,
    required this.faydaliOy,
    required this.faydaliOlmayanOy,
    required this.oylayanlar,
    required this.maviTik,
    required this.duyguTonu,
  });

  factory _YorumModel.fromDoc(QueryDocumentSnapshot doc) {
    final d = doc.data() as Map<String, dynamic>;
    return _YorumModel(
      id: doc.id,
      uid: (d['uid'] as String?) ?? doc.id,
      puan: (d['puan'] as int?) ?? 0,
      displayName: (d['displayName'] as String?) ?? 'Anonim',
      yorum: (d['yorum'] as String?) ?? '',
      position: d['position'] as String?,
      tarih: (d['tarih'] as Timestamp?)?.toDate(),
      faydaliOy: (d['faydali_oy'] as int?) ?? 0,
      faydaliOlmayanOy: (d['faydali_olmayan_oy'] as int?) ?? 0,
      oylayanlar: List<String>.from(d['oylayan_kullanicilar'] ?? []),
      maviTik: d['yazarin_mavi_tik'] == true,
      duyguTonu: _duyguCoz(d),
    );
  }

  /// Önce Duygusal Akıl'ın duygu_tonu alanına bak; yoksa yıldıza göre tahmin.
  static DuyguTonu _duyguCoz(Map<String, dynamic> d) {
    final dt = (d['duygu_tonu'] as String?)?.toLowerCase();
    if (dt == 'pozitif') return DuyguTonu.pozitif;
    if (dt == 'negatif') return DuyguTonu.negatif;
    if (dt == 'nötr' || dt == 'notr') return DuyguTonu.notr;
    // Fallback: yıldız bazlı
    final p = (d['puan'] as int?) ?? 3;
    if (p >= 4) return DuyguTonu.pozitif;
    if (p <= 2) return DuyguTonu.negatif;
    return DuyguTonu.notr;
  }
}

@immutable
class _HalkIstatistik {
  final int toplam;
  final double ortalama;
  final Map<int, int> yildizDagilim; // 1-5 yıldız sayıları
  final int pozitifSayi; // duygu_tonu'na göre
  final int notrSayi;
  final int negatifSayi;

  const _HalkIstatistik({
    required this.toplam,
    required this.ortalama,
    required this.yildizDagilim,
    required this.pozitifSayi,
    required this.notrSayi,
    required this.negatifSayi,
  });

  factory _HalkIstatistik.hesapla(List<_YorumModel> yorumlar) {
    if (yorumlar.isEmpty) {
      return const _HalkIstatistik(
        toplam: 0,
        ortalama: 0,
        yildizDagilim: {1: 0, 2: 0, 3: 0, 4: 0, 5: 0},
        pozitifSayi: 0,
        notrSayi: 0,
        negatifSayi: 0,
      );
    }

    final yildiz = <int, int>{1: 0, 2: 0, 3: 0, 4: 0, 5: 0};
    var toplamPuan = 0;
    var poz = 0, ntr = 0, neg = 0;

    for (final y in yorumlar) {
      final p = y.puan.clamp(1, 5);
      yildiz[p] = (yildiz[p] ?? 0) + 1;
      toplamPuan += p;
      switch (y.duyguTonu) {
        case DuyguTonu.pozitif:
          poz++;
        case DuyguTonu.notr:
          ntr++;
        case DuyguTonu.negatif:
          neg++;
      }
    }

    return _HalkIstatistik(
      toplam: yorumlar.length,
      ortalama: toplamPuan / yorumlar.length,
      yildizDagilim: Map.unmodifiable(yildiz),
      pozitifSayi: poz,
      notrSayi: ntr,
      negatifSayi: neg,
    );
  }

  double get pozitifOran => toplam == 0 ? 0 : pozitifSayi / toplam;
  double get mesafeliOran => toplam == 0 ? 0 : notrSayi / toplam;
  double get negatifOran => toplam == 0 ? 0 : negatifSayi / toplam;

  int get maxYildizDagilim {
    var maks = 0;
    for (final v in yildizDagilim.values) {
      if (v > maks) maks = v;
    }
    return maks;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Görsel Bileşenler — Özet
// ─────────────────────────────────────────────────────────────────────────────

class _OzetKartlari extends StatelessWidget {
  final _HalkIstatistik istatistik;
  const _OzetKartlari({required this.istatistik});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Row(
      children: [
        Expanded(
          child: _MetricKart(
            deger: '%${(istatistik.pozitifOran * 100).round()}',
            etiket: 'Pozitif Yorum',
            renk: istatistik.pozitifOran >= 0.6
                ? cs.primary
                : istatistik.pozitifOran >= 0.4
                    ? cs.tertiary
                    : cs.error,
          ),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: _MetricKart(
            deger: '${istatistik.toplam}',
            etiket: 'Toplam Yorum',
          ),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: _MetricKart(
            deger: istatistik.ortalama.toStringAsFixed(1),
            etiket: 'Ortalama Puan',
            renk: cs.tertiary,
          ),
        ),
      ],
    );
  }
}

class _MetricKart extends StatelessWidget {
  final String deger;
  final String etiket;
  final Color? renk;
  const _MetricKart({
    required this.deger,
    required this.etiket,
    this.renk,
  });

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 8),
      decoration: BoxDecoration(
        color: cs.surface,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        children: [
          Text(
            deger,
            style: TextStyle(
              fontSize: 20,
              fontWeight: FontWeight.w500,
              color: renk ?? cs.onSurface,
            ),
          ),
          const SizedBox(height: 2),
          Text(
            etiket,
            style: TextStyle(fontSize: 11, color: cs.onSurfaceVariant),
            textAlign: TextAlign.center,
          ),
        ],
      ),
    );
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Duygu Dağılımı Çubuğu
// ─────────────────────────────────────────────────────────────────────────────

class _DuyguDagilimi extends StatelessWidget {
  final _HalkIstatistik istatistik;
  const _DuyguDagilimi({required this.istatistik});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    if (istatistik.toplam == 0) return const SizedBox.shrink();

    final poz = (istatistik.pozitifOran * 100).round();
    final mes = (istatistik.mesafeliOran * 100).round();
    final neg = (istatistik.negatifOran * 100).round();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'Duygu Dağılımı',
          style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant),
        ),
        const SizedBox(height: 6),
        ClipRRect(
          borderRadius: BorderRadius.circular(99),
          child: SizedBox(
            height: 8,
            child: Row(
              children: [
                if (istatistik.pozitifOran > 0)
                  Expanded(
                    flex: (istatistik.pozitifOran * 1000).round(),
                    child: Container(color: cs.primary),
                  ),
                if (istatistik.mesafeliOran > 0)
                  Expanded(
                    flex: (istatistik.mesafeliOran * 1000).round(),
                    child: Container(color: cs.tertiary),
                  ),
                if (istatistik.negatifOran > 0)
                  Expanded(
                    flex: (istatistik.negatifOran * 1000).round(),
                    child: Container(color: cs.error),
                  ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 6),
        Wrap(
          spacing: 12,
          runSpacing: 4,
          children: [
            _LegendNokta(renk: cs.primary, metin: 'Pozitif %$poz'),
            _LegendNokta(renk: cs.tertiary, metin: 'Mesafeli %$mes'),
            _LegendNokta(renk: cs.error, metin: 'Negatif %$neg'),
          ],
        ),
      ],
    );
  }
}

class _LegendNokta extends StatelessWidget {
  final Color renk;
  final String metin;
  const _LegendNokta({required this.renk, required this.metin});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 8,
          height: 8,
          decoration: BoxDecoration(color: renk, shape: BoxShape.circle),
        ),
        const SizedBox(width: 4),
        Text(metin,
            style: TextStyle(fontSize: 11, color: cs.onSurfaceVariant)),
      ],
    );
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Yıldız Dağılım Barları
// ─────────────────────────────────────────────────────────────────────────────

class _DagilimBarlari extends StatelessWidget {
  final _HalkIstatistik istatistik;
  final int? secili;
  final ValueChanged<int> onSecili;

  const _DagilimBarlari({
    required this.istatistik,
    required this.secili,
    required this.onSecili,
  });

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final maxDeger =
        istatistik.maxYildizDagilim == 0 ? 1 : istatistik.maxYildizDagilim;

    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: cs.surface,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Yıldız Dağılımı',
            style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w500,
              color: cs.onSurfaceVariant,
            ),
          ),
          const SizedBox(height: 8),
          for (var yildiz = 5; yildiz >= 1; yildiz--)
            _DagilimSatir(
              yildiz: yildiz,
              sayi: istatistik.yildizDagilim[yildiz] ?? 0,
              maxSayi: maxDeger,
              secili: secili == yildiz,
              onTap: () => onSecili(yildiz),
            ),
        ],
      ),
    );
  }
}

class _DagilimSatir extends StatelessWidget {
  final int yildiz;
  final int sayi;
  final int maxSayi;
  final bool secili;
  final VoidCallback onTap;

  const _DagilimSatir({
    required this.yildiz,
    required this.sayi,
    required this.maxSayi,
    required this.secili,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final oran = sayi / maxSayi;

    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(4),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 3),
        child: Row(
          children: [
            SizedBox(
              width: 30,
              child: Row(
                children: [
                  Text(
                    '$yildiz',
                    style: TextStyle(
                      fontSize: 11,
                      fontWeight:
                          secili ? FontWeight.w500 : FontWeight.normal,
                      color: cs.onSurface,
                    ),
                  ),
                  const SizedBox(width: 2),
                  const Icon(Icons.star, size: 10, color: Color(0xFFFFC107)),
                ],
              ),
            ),
            Expanded(
              child: ClipRRect(
                borderRadius: BorderRadius.circular(99),
                child: LinearProgressIndicator(
                  value: oran,
                  minHeight: 5,
                  backgroundColor: cs.surfaceContainerHighest,
                  valueColor: AlwaysStoppedAnimation<Color>(
                    secili ? cs.primary : cs.primary.withValues(alpha: 0.65),
                  ),
                ),
              ),
            ),
            const SizedBox(width: 8),
            SizedBox(
              width: 28,
              child: Text(
                '$sayi',
                style: TextStyle(fontSize: 10, color: cs.onSurfaceVariant),
                textAlign: TextAlign.right,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _FiltreEtiketi extends StatelessWidget {
  final int? filtre;
  final int toplam;
  final VoidCallback onTemizle;

  const _FiltreEtiketi({
    required this.filtre,
    required this.toplam,
    required this.onTemizle,
  });

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Row(
      children: [
        Text(
          filtre == null
              ? 'Tüm yorumlar ($toplam)'
              : '$filtre ★ yorumlar ($toplam)',
          style: TextStyle(
            fontSize: 12,
            fontWeight: FontWeight.w500,
            color: cs.onSurface,
          ),
        ),
        const Spacer(),
        if (filtre != null)
          TextButton.icon(
            onPressed: onTemizle,
            icon: const Icon(Icons.close, size: 14),
            label: const Text('Filtreyi temizle'),
            style: TextButton.styleFrom(
              padding: const EdgeInsets.symmetric(horizontal: 8),
              minimumSize: const Size(0, 28),
              tapTargetSize: MaterialTapTargetSize.shrinkWrap,
              textStyle: const TextStyle(fontSize: 11),
            ),
          ),
      ],
    );
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Yorum Kartı — TIKLANABİLİR, kullanıcı bilgi sheet açar
// ─────────────────────────────────────────────────────────────────────────────

class _YorumKarti extends StatelessWidget {
  final _YorumModel yorum;
  final String symbol;
  const _YorumKarti({required this.yorum, required this.symbol});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final tarihMetni = yorum.tarih == null
        ? ''
        : DateFormat('dd.MM.yyyy').format(yorum.tarih!);

    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Material(
        color: cs.surface,
        borderRadius: BorderRadius.circular(12),
        child: InkWell(
          onTap: () => _KullaniciSheet.goster(context, yorum),
          borderRadius: BorderRadius.circular(12),
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // ── Kullanıcı başlık satırı ──
                Row(
                  children: [
                    CircleAvatar(
                      radius: 16,
                      backgroundColor: cs.primary,
                      child: Text(
                        yorum.displayName.isNotEmpty
                            ? yorum.displayName[0].toUpperCase()
                            : 'A',
                        style: const TextStyle(
                          color: Colors.white,
                          fontWeight: FontWeight.bold,
                          fontSize: 13,
                        ),
                      ),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            children: [
                              Flexible(
                                child: Text(
                                  yorum.displayName,
                                  style: const TextStyle(
                                    fontWeight: FontWeight.bold,
                                    fontSize: 13,
                                  ),
                                  overflow: TextOverflow.ellipsis,
                                ),
                              ),
                              if (yorum.maviTik) ...[
                                const SizedBox(width: 4),
                                const Icon(Icons.verified,
                                    size: 13, color: Colors.blue),
                              ],
                              if (yorum.position != null) ...[
                                const SizedBox(width: 6),
                                _PositionRozeti(position: yorum.position!),
                              ],
                            ],
                          ),
                          Row(
                            children: [
                              ...List.generate(
                                5,
                                (i) => Icon(
                                  i < yorum.puan
                                      ? Icons.star
                                      : Icons.star_border,
                                  size: 12,
                                  color: const Color(0xFFFFC107),
                                ),
                              ),
                              const SizedBox(width: 6),
                              Text(
                                tarihMetni,
                                style: TextStyle(
                                    fontSize: 11,
                                    color: cs.onSurfaceVariant),
                              ),
                            ],
                          ),
                        ],
                      ),
                    ),
                    Icon(Icons.chevron_right,
                        size: 18, color: cs.onSurfaceVariant),
                  ],
                ),

                // ── Yorum metni ──
                if (yorum.yorum.isNotEmpty) ...[
                  const SizedBox(height: 8),
                  Text(
                    yorum.yorum,
                    style: TextStyle(
                      fontSize: 13,
                      color: cs.onSurface,
                      height: 1.35,
                    ),
                  ),
                ],

                // ── Beğeni / Beğenmeme / 3 Nokta menüsü ──
                const SizedBox(height: 8),
                _YorumAltBar(yorum: yorum, symbol: symbol),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Yorum Alt Bar — Beğeni, Beğenmeme, 3 Nokta Menüsü
// ─────────────────────────────────────────────────────────────────────────────

class _YorumAltBar extends StatefulWidget {
  final _YorumModel yorum;
  final String symbol;
  const _YorumAltBar({required this.yorum, required this.symbol});

  @override
  State<_YorumAltBar> createState() => _YorumAltBarState();
}

class _YorumAltBarState extends State<_YorumAltBar> {
  late int _faydali;
  late int _faydaliOlmayan;
  bool? _oyum; // true = beğendi, false = beğenmedi, null = oy vermedi

  @override
  void initState() {
    super.initState();
    _faydali = widget.yorum.faydaliOy;
    _faydaliOlmayan = widget.yorum.faydaliOlmayanOy;

    // Kullanıcı daha önce oy verdiyse durumu yansıt
    // (hangi yönde verdiği Firestore'da tutulmadığından sadece
    //  "zaten oy verdi" bilgisini kullanıyoruz — UI'da her ikisini de kilitliyoruz)
  }

  String? get _mevcutUid => FirebaseAuth.instance.currentUser?.uid;

  bool get _zatenOyVerdi =>
      _mevcutUid != null && widget.yorum.oylayanlar.contains(_mevcutUid);

  DocumentReference get _yorumRef => FirebaseFirestore.instance
      .collection('hisseler')
      .doc(widget.symbol)
      .collection('yorumlar')
      .doc(widget.yorum.id);

  Future<void> _oy(bool pozitif) async {
    final uid = _mevcutUid;
    if (uid == null) return;

    // Zaten oy verilmişse engelle
    if (_zatenOyVerdi) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Bu yoruma zaten oy verdiniz.'),
          duration: Duration(seconds: 1),
        ),
      );
      return;
    }

    // Optimistik güncelleme
    setState(() {
      if (pozitif) {
        _faydali++;
      } else {
        _faydaliOlmayan++;
      }
      _oyum = pozitif;
    });

    try {
      await _yorumRef.update({
        if (pozitif)
          'faydali_oy': FieldValue.increment(1)
        else
          'faydali_olmayan_oy': FieldValue.increment(1),
        'oylayan_kullanicilar': FieldValue.arrayUnion([uid]),
      });
    } catch (_) {
      // Hata durumunda geri al
      setState(() {
        if (pozitif) {
          _faydali--;
        } else {
          _faydaliOlmayan--;
        }
        _oyum = null;
      });
    }
  }

  void _sikayetAc() {
    final uid = _mevcutUid;
    if (uid == null) return;

    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Theme.of(context).colorScheme.surface,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (_) => _SikayetSheet(
        yorumcuUid: widget.yorum.uid,
        sikayetEdenUid: uid,
        hisseSymbol: widget.symbol,
        onBasari: () {
          if (mounted) {
            ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(
                  content: Text('Şikayetiniz iletildi, teşekkürler.')),
            );
          }
        },
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final oyVerildi = _zatenOyVerdi || _oyum != null;

    return Row(
      children: [
        // ── Beğeni butonu ──
        _OyButon(
          icon: Icons.thumb_up_outlined,
          iconSecili: Icons.thumb_up,
          sayi: _faydali,
          secili: _oyum == true,
          aktif: !oyVerildi,
          onTap: () => _oy(true),
        ),
        const SizedBox(width: 12),

        // ── Beğenmeme butonu ──
        _OyButon(
          icon: Icons.thumb_down_outlined,
          iconSecili: Icons.thumb_down,
          sayi: _faydaliOlmayan,
          secili: _oyum == false,
          aktif: !oyVerildi,
          onTap: () => _oy(false),
        ),

        const Spacer(),

        // ── 3 Nokta Menüsü ──
        PopupMenuButton<String>(
          icon: Icon(Icons.more_horiz, size: 18, color: cs.onSurfaceVariant),
          padding: EdgeInsets.zero,
          itemBuilder: (_) => [
            PopupMenuItem<String>(
              value: 'sikayet',
              child: Row(
                children: [
                  Icon(Icons.flag_outlined, size: 16, color: cs.error),
                  const SizedBox(width: 8),
                  Text(
                    'Şikayet Et',
                    style: TextStyle(fontSize: 13, color: cs.error),
                  ),
                ],
              ),
            ),
          ],
          onSelected: (val) {
            if (val == 'sikayet') _sikayetAc();
          },
        ),
      ],
    );
  }
}

class _OyButon extends StatelessWidget {
  final IconData icon;
  final IconData iconSecili;
  final int sayi;
  final bool secili;
  final bool aktif;
  final VoidCallback onTap;

  const _OyButon({
    required this.icon,
    required this.iconSecili,
    required this.sayi,
    required this.secili,
    required this.aktif,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final renk = secili
        ? cs.primary
        : aktif
            ? cs.onSurfaceVariant
            : cs.onSurfaceVariant.withValues(alpha: 0.4);

    return InkWell(
      onTap: aktif ? onTap : null,
      borderRadius: BorderRadius.circular(4),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 2),
        child: Row(
          children: [
            Icon(secili ? iconSecili : icon, size: 14, color: renk),
            const SizedBox(width: 4),
            Text(
              '$sayi',
              style: TextStyle(fontSize: 11, color: renk),
            ),
          ],
        ),
      ),
    );
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Şikayet Sheet — detay_screen.dart'taki _SikayetSheet ile aynı mantık
// ─────────────────────────────────────────────────────────────────────────────

class _SikayetSheet extends StatefulWidget {
  const _SikayetSheet({
    required this.yorumcuUid,
    required this.sikayetEdenUid,
    required this.hisseSymbol,
    required this.onBasari,
  });

  final String yorumcuUid;
  final String sikayetEdenUid;
  final String hisseSymbol;
  final VoidCallback onBasari;

  @override
  State<_SikayetSheet> createState() => _SikayetSheetState();
}

class _SikayetSheetState extends State<_SikayetSheet> {
  static const _sebepler = <String, String>{
    '🚫 Küfür / Hakaret': 'Küfür / Hakaret',
    '⚠️ Yanıltıcı Bilgi': 'Yanıltıcı Bilgi',
    '🔁 Spam': 'Spam',
    '📝 Diğer': 'Diğer',
  };

  String? _secilen;
  final _aciklamaCtrl = TextEditingController();
  bool _gonderiliyor = false;

  @override
  void dispose() {
    _aciklamaCtrl.dispose();
    super.dispose();
  }

  Future<void> _gonder() async {
    if (_secilen == null) return;
    setState(() => _gonderiliyor = true);
    try {
      await FirebaseFirestore.instance.collection('raporlar').add({
        'yorumcu_uid': widget.yorumcuUid,
        'sikayet_eden_uid': widget.sikayetEdenUid,
        'hisse_symbol': widget.hisseSymbol,
        'sebep': _sebepler[_secilen]!,
        'aciklama':
            _secilen == '📝 Diğer' ? _aciklamaCtrl.text.trim() : '',
        'tarih': FieldValue.serverTimestamp(),
        'durum': 'beklemede',
        'incelendi': false,
      });
      if (mounted) Navigator.pop(context);
      widget.onBasari();
    } catch (_) {
      if (mounted) setState(() => _gonderiliyor = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;

    return Padding(
      padding: EdgeInsets.only(
        bottom: MediaQuery.of(context).viewInsets.bottom + 16,
        left: 16,
        right: 16,
        top: 20,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Tutamak
          Center(
            child: Container(
              width: 36,
              height: 4,
              decoration: BoxDecoration(
                color: cs.outlineVariant,
                borderRadius: BorderRadius.circular(2),
              ),
            ),
          ),
          const SizedBox(height: 16),
          const Text(
            'Şikayet Sebebi',
            style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
          ),
          const SizedBox(height: 8),
          RadioGroup<String>(
            groupValue: _secilen,
            onChanged: (v) => setState(() => _secilen = v),
            child: Column(
              children: _sebepler.keys.map((label) => GestureDetector(
                    onTap: () => setState(() => _secilen = label),
                    child: Padding(
                      padding: const EdgeInsets.symmetric(vertical: 8.0),
                      child: Row(
                        children: [
                          Radio<String>(value: label),
                          Expanded(
                            child: Text(label, style: const TextStyle(fontSize: 14)),
                          ),
                        ],
                      ),
                    ),
                  )).toList(),
            ),
          ),
          if (_secilen == '📝 Diğer') ...[
            const SizedBox(height: 8),
            TextField(
              controller: _aciklamaCtrl,
              maxLines: 3,
              decoration: const InputDecoration(
                hintText: 'Açıklamanızı yazın...',
                border: OutlineInputBorder(),
                contentPadding:
                    EdgeInsets.symmetric(horizontal: 12, vertical: 10),
              ),
            ),
          ],
          const SizedBox(height: 16),
          SizedBox(
            width: double.infinity,
            child: ElevatedButton(
              onPressed: _secilen == null || _gonderiliyor ? null : _gonder,
              style: ElevatedButton.styleFrom(
                backgroundColor: cs.primary,
                foregroundColor: Colors.white,
              ),
              child: _gonderiliyor
                  ? const SizedBox(
                      height: 18,
                      width: 18,
                      child: CircularProgressIndicator(
                          strokeWidth: 2, color: Colors.white),
                    )
                  : const Text('Gönder'),
            ),
          ),
        ],
      ),
    );
  }
}

class _PositionRozeti extends StatelessWidget {
  final String position;
  const _PositionRozeti({required this.position});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final (bg, fg, label) = switch (position) {
      'portfoy' => (
          cs.primary.withValues(alpha: 0.1),
          cs.primary,
          'Portföyde',
        ),
      'cikti' => (
          cs.error.withValues(alpha: 0.1),
          cs.error,
          'Çıktı',
        ),
      _ => (
          cs.tertiary.withValues(alpha: 0.1),
          cs.tertiary,
          'Takipte',
        ),
    };

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(4),
      ),
      child: Text(
        label,
        style: TextStyle(
          fontSize: 10,
          color: fg,
          fontWeight: FontWeight.bold,
        ),
      ),
    );
  }
}

// ═════════════════════════════════════════════════════════════════════════════
// KULLANICI BİLGİ SHEET
// ═════════════════════════════════════════════════════════════════════════════

class _KullaniciSheet extends StatelessWidget {
  final _YorumModel yorum;
  const _KullaniciSheet({required this.yorum});

  static void goster(BuildContext context, _YorumModel yorum) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Theme.of(context).colorScheme.surface,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (_) => _KullaniciSheet(yorum: yorum),
    );
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;

    return SafeArea(
      child: FutureBuilder<DocumentSnapshot>(
        future: FirebaseFirestore.instance
            .collection('users')
            .doc(yorum.uid)
            .get(),
        builder: (context, snap) {
          final data = (snap.data?.data() as Map<String, dynamic>?) ?? {};
          final profil = _KullaniciProfili.fromData(data, yorum);

          return Padding(
            padding: const EdgeInsets.fromLTRB(20, 12, 20, 24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                // Tutamak
                Container(
                  width: 36,
                  height: 4,
                  decoration: BoxDecoration(
                    color: cs.outlineVariant,
                    borderRadius: BorderRadius.circular(2),
                  ),
                ),
                const SizedBox(height: 16),
                // Avatar + isim + mavi tik
                Row(
                  children: [
                    CircleAvatar(
                      radius: 26,
                      backgroundColor: cs.primary,
                      child: Text(
                        profil.displayName.isNotEmpty
                            ? profil.displayName[0].toUpperCase()
                            : 'A',
                        style: const TextStyle(
                          color: Colors.white,
                          fontWeight: FontWeight.bold,
                          fontSize: 22,
                        ),
                      ),
                    ),
                    const SizedBox(width: 14),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            children: [
                              Flexible(
                                child: Text(
                                  profil.displayName,
                                  style: const TextStyle(
                                    fontSize: 16,
                                    fontWeight: FontWeight.bold,
                                  ),
                                  overflow: TextOverflow.ellipsis,
                                ),
                              ),
                              if (profil.maviTik) ...[
                                const SizedBox(width: 4),
                                const Icon(Icons.verified,
                                    size: 16, color: Colors.blue),
                              ],
                            ],
                          ),
                          if (profil.uyelikTarihiMetni != null) ...[
                            const SizedBox(height: 2),
                            Text(
                              profil.uyelikTarihiMetni!,
                              style: TextStyle(
                                fontSize: 11,
                                color: cs.onSurfaceVariant,
                              ),
                            ),
                          ],
                        ],
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 16),
                // Loader veya 3 metric kart
                if (snap.connectionState == ConnectionState.waiting)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 12),
                    child: CircularProgressIndicator(color: cs.primary),
                  )
                else
                  Row(
                    children: [
                      Expanded(
                        child: _MetricKart(
                          deger: '${profil.toplamYorum}',
                          etiket: 'Toplam Yorum',
                        ),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: _MetricKart(
                          deger: profil.ortalamaPuan == null
                              ? '—'
                              : profil.ortalamaPuan!.toStringAsFixed(1),
                          etiket: 'Ortalama Puan',
                          renk: cs.tertiary,
                        ),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: _MetricKart(
                          deger: profil.guvenSkoru == null
                              ? '—'
                              : profil.guvenSkoru!.toStringAsFixed(1),
                          etiket: 'Güven Skoru',
                          renk: profil.guvenSkoruRengi(cs),
                        ),
                      ),
                    ],
                  ),
                const SizedBox(height: 16),
                // Bilgi notu
                Container(
                  padding: const EdgeInsets.symmetric(
                      horizontal: 12, vertical: 8),
                  decoration: BoxDecoration(
                    color: cs.primary.withValues(alpha: 0.08),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Row(
                    children: [
                      Icon(Icons.info_outline, size: 14, color: cs.primary),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          'Güven skoru hesap yaşı, yorum çeşitliliği ve topluluk onayına göre hesaplanır.',
                          style: TextStyle(
                            fontSize: 11,
                            color: cs.onSurfaceVariant,
                            height: 1.35,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          );
        },
      ),
    );
  }
}

@immutable
class _KullaniciProfili {
  final String displayName;
  final bool maviTik;
  final int toplamYorum;
  final double? ortalamaPuan;
  final double? guvenSkoru;
  final String? uyelikTarihiMetni;

  const _KullaniciProfili({
    required this.displayName,
    required this.maviTik,
    required this.toplamYorum,
    required this.ortalamaPuan,
    required this.guvenSkoru,
    required this.uyelikTarihiMetni,
  });

  factory _KullaniciProfili.fromData(
    Map<String, dynamic> d,
    _YorumModel yorum,
  ) {
    final isim = (d['displayName'] as String?)?.trim();
    final guven = (d['guven_skoru'] as num?)?.toDouble();
    final maviTik = d['mavi_tik'] == true || (guven != null && guven >= 10);

    final toplam = (d['toplam_yorum'] as int?) ?? 0;
    final ortalama = (d['ortalama_puan'] as num?)?.toDouble();

    final uyelikTs = d['created_at'] as Timestamp? ??
        d['createdAt'] as Timestamp? ??
        d['kayit_tarihi'] as Timestamp?;
    final uyelikMetni = uyelikTs == null
        ? null
        : 'Üyelik: ${DateFormat('MMM yyyy', 'tr_TR').format(uyelikTs.toDate())}';

    return _KullaniciProfili(
      displayName:
          (isim != null && isim.isNotEmpty) ? isim : yorum.displayName,
      maviTik: maviTik,
      toplamYorum: toplam,
      ortalamaPuan: ortalama,
      guvenSkoru: guven,
      uyelikTarihiMetni: uyelikMetni,
    );
  }

  Color guvenSkoruRengi(ColorScheme cs) {
    if (guvenSkoru == null) return cs.onSurface;
    if (guvenSkoru! >= 7) return cs.primary;
    if (guvenSkoru! >= 4) return cs.tertiary;
    return cs.error;
  }
}