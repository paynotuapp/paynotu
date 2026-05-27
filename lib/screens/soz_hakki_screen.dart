import 'package:flutter/material.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'dart:async';
import 'dart:math';
import 'package:pay/services/duygusal_akil_service.dart';

class SozHakkiScreen extends StatefulWidget {
  final String symbol;
  final String hisseAdi;
  const SozHakkiScreen({
    super.key,
    required this.symbol,
    required this.hisseAdi,
  });

  @override
  State<SozHakkiScreen> createState() => _SozHakkiScreenState();
}

class _SozHakkiScreenState extends State<SozHakkiScreen> {
  int _secilenYildiz = 0;
  String? _secilenPosition;
  final _yorumController = TextEditingController();
  final _scrollController = ScrollController();
  final _yorumFocusNode = FocusNode();
  bool _gonderiliyor = false;
  Map<String, dynamic>? _mevcutYorum;
  Map<String, dynamic>? _kullaniciData;
  bool _yukleniyor = true;
  Timer? _icerikTimer;
  String _icerikDurumu = 'temiz';   // temiz | şüpheli | engellendi
  String _icerikAciklama = '';

  final List<Map<String, dynamic>> _positionSecenekleri = [
    {
      'value': 'portfoy',
      'label': 'Portföyümde',
      'icon': Icons.trending_up,
      'color': const Color(0xFF00C853),
    },
    {
      'value': 'takip',
      'label': 'Takip Ediyorum',
      'icon': Icons.remove_red_eye,
      'color': Colors.blue,
    },
    {
      'value': 'cikti',
      'label': 'Sattım & Çıktım',
      'icon': Icons.trending_down,
      'color': Colors.red,
    },
  ];

  @override
  void initState() {
    super.initState();
    _mevcutYorumCek();
    _kullaniciVerisiCek();
    _yorumFocusNode.addListener(() {
      if (_yorumFocusNode.hasFocus) {
        Future.delayed(const Duration(milliseconds: 300), () {
          _scrollController.animateTo(
            _scrollController.position.maxScrollExtent,
            duration: const Duration(milliseconds: 300),
            curve: Curves.easeOut,
          );
        });
      }
    });
  }

  @override
  void dispose() {
    _icerikTimer?.cancel();
    _yorumController.dispose();
    _scrollController.dispose();
    _yorumFocusNode.dispose();
    super.dispose();
  }

  Future<void> _kullaniciVerisiCek() async {
    final uid = FirebaseAuth.instance.currentUser?.uid;
    if (uid == null) return;
    final doc = await FirebaseFirestore.instance.collection('users').doc(uid).get();
    if (doc.exists && mounted) {
      setState(() => _kullaniciData = doc.data());
    }
  }

  Future<void> _mevcutYorumCek() async {
    final uid = FirebaseAuth.instance.currentUser?.uid;
    if (uid == null) return;

    final doc = await FirebaseFirestore.instance
        .collection('hisseler')
        .doc(widget.symbol)
        .collection('yorumlar')
        .doc(uid)
        .get();

    if (doc.exists && mounted) {
      final data = doc.data()!;
      setState(() {
        _mevcutYorum = data;
        _secilenYildiz = (data['puan'] as int?) ?? 0;
        _secilenPosition = data['position'] as String?;
        _yorumController.text = data['yorum'] ?? '';
        _yukleniyor = false;
      });
    } else if (mounted) {
      setState(() => _yukleniyor = false);
    }
  }

  bool _yirmiDortSaatGectiMi() {
    return true; // geçici olarak devre dışı
  }

  double _agirlikHesapla(int updateCount) {
    return max(0.10, 1.0 * pow(0.65, updateCount));
  }

  Widget _rozetWidget() {
    final gs = (_kullaniciData?['guven_skoru'] as num? ?? 0.0).toDouble();
    final String etiket;
    final Color renk;
    final IconData ikon;
    if (gs >= 10) {
      etiket = 'Mavi Tik';
      renk = Colors.blue;
      ikon = Icons.verified;
    } else if (gs >= 7) {
      etiket = 'Uzman';
      renk = Colors.blue;
      ikon = Icons.circle;
    } else if (gs >= 4) {
      etiket = 'Güvenilir';
      renk = Colors.brown;
      ikon = Icons.circle;
    } else {
      etiket = 'Yeni Ses';
      renk = Colors.black54;
      ikon = Icons.circle;
    }
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(ikon, size: 10, color: renk),
        const SizedBox(width: 3),
        Text(
          '$etiket  •  Güven: ${gs.toStringAsFixed(1)}/10',
          style: TextStyle(
              fontSize: 11, color: renk, fontWeight: FontWeight.w600),
        ),
      ],
    );
  }

  void _icerikKontrolEt(String metin) {
    _icerikTimer?.cancel();
    if (metin.trim().isEmpty) {
      setState(() {
        _icerikDurumu = 'temiz';
        _icerikAciklama = '';
      });
      return;
    }
    _icerikTimer = Timer(const Duration(milliseconds: 500), () async {
      final sonuc = await DuygusalAkilService.icerikKontrol(metin);
      if (mounted) {
        setState(() {
          _icerikDurumu = sonuc.durum;
          _icerikAciklama = sonuc.durum != 'temiz' ? sonuc.aciklama : '';
        });
      }
    });
  }

  void _yorumKurallariDialog() {
    showDialog(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Yorum Kuralları',
            style: TextStyle(fontWeight: FontWeight.bold)),
        content: const SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'PayNotu, yatırımcıların birbirine güvendiği bir topluluktur. '
                'Bu güveni korumak için aşağıdaki kurallara uymanızı rica ederiz.',
                style: TextStyle(fontSize: 13, height: 1.5),
              ),
              SizedBox(height: 14),
              _KuralBaslik(baslik: 'Kabul edilen yorumlar'),
              SizedBox(height: 4),
              Text(
                'Deneyimlerinize dayalı, nesnel ve ölçülü değerlendirmeler yazın. '
                'Şirketin performansı, yönetim kalitesi, temettü politikası veya '
                'uzun vadeli vizyonu hakkındaki görüşlerinizi paylaşabilirsiniz.',
                style: TextStyle(fontSize: 13, height: 1.5),
              ),
              SizedBox(height: 14),
              _KuralBaslik(baslik: 'Kabul edilmeyen yorumlar'),
              SizedBox(height: 4),
              Text(
                'Küfür, hakaret ve kişisel saldırı içeren yorumlar sistem tarafından '
                'otomatik olarak engellenir. "Kesin alın", "yarın uçacak", '
                '"herkese söyleyin" gibi yönlendirici ve manipülatif ifadeler yasaktır. '
                'Aynı yorumun tekrar tekrar paylaşılması spam olarak değerlendirilir.',
                style: TextStyle(fontSize: 13, height: 1.5),
              ),
              SizedBox(height: 14),
              _KuralBaslik(baslik: 'Yorum hakkı sistemi'),
              SizedBox(height: 4),
              Text(
                'Her kullanıcı uygulamaya katıldığında 10 yorum hakkı hediye olarak '
                'tanımlanır. Sonraki aylarda yorum hakkınız güven skorunuzla orantılı '
                'olarak belirlenir. Güven skorunuz arttıkça aylık yorum hakkınız da '
                'artar, en fazla 100 yoruma kadar ulaşabilirsiniz. Aynı hisseye '
                'yaptığınız yorumu 24 saat sonra güncelleyebilirsiniz, güncelleme '
                'yorum hakkı tüketmez.',
                style: TextStyle(fontSize: 13, height: 1.5),
              ),
              SizedBox(height: 14),
              _KuralBaslik(baslik: 'Topluluk denetimi'),
              SizedBox(height: 4),
              Text(
                'Diğer kullanıcılar yorumlarınızı faydalı veya faydasız olarak '
                'değerlendirebilir. Topluluk tarafından faydasız bulunan yorumların '
                'sistem üzerindeki etkisi otomatik olarak azalır. Kaliteli ve dürüst '
                'yorumlar ise güven skorunuzu yükselterek sesinize daha fazla ağırlık '
                'kazandırır.',
                style: TextStyle(fontSize: 13, height: 1.5),
              ),
              SizedBox(height: 14),
              _KuralBaslik(baslik: 'Güven skoru ve mavi tik'),
              SizedBox(height: 4),
              Text(
                'Güven skorunuz hesap yaşınıza, yorum çeşitliliğinize ve topluluk '
                'onayına göre 0 ile 10 arasında hesaplanır. 10 üzerinden 10 güven '
                'skoruna ulaşan kullanıcılar mavi tik rozeti kazanır.',
                style: TextStyle(fontSize: 13, height: 1.5),
              ),
              SizedBox(height: 14),
              _KuralBaslik(baslik: 'Sorumluluk reddi', renk: Colors.orange),
              SizedBox(height: 4),
              Text(
                "PayNotu'daki hiçbir yorum yatırım tavsiyesi niteliği taşımaz. "
                'Tüm yatırım kararlarınızı kendi araştırmanıza dayandırın.',
                style: TextStyle(fontSize: 13, height: 1.5),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: Text('Anladım',
                style: TextStyle(color: Theme.of(context).colorScheme.primary)),
          ),
        ],
      ),
    );
  }

  Future<void> _yorumGonder() async {
    final uid = FirebaseAuth.instance.currentUser?.uid;
    final displayName =
        FirebaseAuth.instance.currentUser?.displayName ?? 'Anonim';
    if (uid == null) return;

    if (_secilenYildiz == 0) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Lütfen puan verin.')),
      );
      return;
    }

    if (_secilenPosition == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Lütfen pozisyon seçin.')),
      );
      return;
    }

    setState(() => _gonderiliyor = true);

    // ── KULLANICI BELGESİ ──────────────────────────────────────────
    final userRef = FirebaseFirestore.instance.collection('users').doc(uid);
    final userSnap = await userRef.get();
    final userData = userSnap.data() ?? {};

    // ── AYLIK YORUM HAKKI KONTROLÜ ─────────────────────────────────
    final ayBaslangici = userData['ay_baslangic_tarihi'] as Timestamp?;
    int kullanilan = (userData['kullanilan_yorum_hakki'] as int?) ?? 0;
    int aylikHak = (userData['aylik_yorum_hakki'] as int?) ?? 10;

    // Ay değişmiş mi kontrol et
    if (ayBaslangici != null) {
      final baslangic = ayBaslangici.toDate();
      final simdi = DateTime.now();
      if (simdi.year != baslangic.year || simdi.month != baslangic.month) {
        // Yeni ay — sıfırla ve hakkı yeniden hesapla
        kullanilan = 0;
        final hosgeldinHakki = userData['hosgeldin_hakki'] as bool? ?? true;
        if (!hosgeldinHakki) {
          final guvenSkoruMevcut =
              (userData['guven_skoru'] as num? ?? 0.0).toDouble();
          aylikHak = max(5, (guvenSkoruMevcut * 10).toInt());
          await userRef.update({
            'kullanilan_yorum_hakki': 0,
            'ay_baslangic_tarihi': FieldValue.serverTimestamp(),
            'aylik_yorum_hakki': aylikHak,
            'hosgeldin_hakki': false,
          });
        } else {
          await userRef.update({
            'kullanilan_yorum_hakki': 0,
            'ay_baslangic_tarihi': FieldValue.serverTimestamp(),
          });
        }
      }
    }

    final yeniYorum = _mevcutYorum == null;

    // ── 24 SAAT KONTROLÜ ───────────────────────────────────────────
    if (!yeniYorum && !_yirmiDortSaatGectiMi()) {
      final fark = DateTime.now()
          .difference((_mevcutYorum!['tarih'] as Timestamp).toDate());
      final kalanSaat = 24 - fark.inHours;
      if (mounted) {
        setState(() => _gonderiliyor = false);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content:
                Text('Yorumunuzu $kalanSaat saat sonra güncelleyebilirsiniz.'),
          ),
        );
      }
      return;
    }

    // ── AYLIK HAK KONTROLÜ (sadece yeni yorumlar) ─────────────────
    if (yeniYorum && kullanilan >= aylikHak) {
      if (mounted) {
        setState(() => _gonderiliyor = false);
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Bu ay yorum hakkınız doldu.')),
        );
      }
      return;
    }

    // ── ETKİ ÇARPANI HESAPLA ───────────────────────────────────────
    final guvenSkoru =
        (userData['guven_skoru'] as num? ?? 0.0).toDouble();
    final double etkiCarpani;
    if (guvenSkoru >= 10) {
      etkiCarpani = 1.00;
    } else if (guvenSkoru >= 7) {
      etkiCarpani = 0.90;
    } else if (guvenSkoru >= 4) {
      etkiCarpani = 0.50;
    } else {
      etkiCarpani = 0.10;
    }
    final yazarinMaviTik = guvenSkoru >= 10;

    // ── YORUM KAYDET ───────────────────────────────────────────────
    final hisseRef = FirebaseFirestore.instance
        .collection('hisseler')
        .doc(widget.symbol);
    final yorumRef = hisseRef.collection('yorumlar').doc(uid);

    final updateCount =
        (_mevcutYorum?['updateCount'] as int? ?? 0) +
            (_mevcutYorum != null ? 1 : 0);
    final agirlik = _agirlikHesapla(updateCount);

    final eskiHistory =
        List<Map<String, dynamic>>.from(_mevcutYorum?['history'] ?? []);
    if (_mevcutYorum != null) {
      eskiHistory.add({
        'puan': _mevcutYorum!['puan'],
        'yorum': _mevcutYorum!['yorum'],
        'position': _mevcutYorum!['position'],
        'tarih': _mevcutYorum!['tarih'],
        'agirlik': _mevcutYorum!['agirlik'] ?? 1.0,
      });
    }

    await yorumRef.set({
      'uid': uid,
      'displayName': displayName,
      'puan': _secilenYildiz,
      'yorum': _yorumController.text.trim(),
      'position': _secilenPosition,
      'tarih': FieldValue.serverTimestamp(),
      'faydali_oy': _mevcutYorum?['faydali_oy'] ?? 0,
      'faydali_olmayan_oy': _mevcutYorum?['faydali_olmayan_oy'] ?? 0,
      'oylayan_kullanicilar': _mevcutYorum?['oylayan_kullanicilar'] ?? [],
      'raporSayisi': _mevcutYorum?['raporSayisi'] ?? 0,
      'updateCount': updateCount,
      'agirlik': agirlik,
      'etki_carpani': etkiCarpani,
      'yazarin_mavi_tik': yazarinMaviTik,
      'history': eskiHistory,
    });

    // ── HİSSE İSTATİSTİKLERİ ──────────────────────────────────────
    final yorumlarSnap = await hisseRef.collection('yorumlar').get();
    final yorumlar = yorumlarSnap.docs.map((d) => d.data()).toList();

    double toplamAgirlikliPuan = 0;
    double toplamAgirlik = 0;
    int positiveCount = 0;
    int negativeCount = 0;
    for (final y in yorumlar) {
      final puan = (y['puan'] as int?) ?? 0;
      final agirlikY = (y['agirlik'] as double?) ?? 1.0;
      toplamAgirlikliPuan += puan * agirlikY;
      toplamAgirlik += agirlikY;
      if (puan >= 4) positiveCount++;
      if (puan <= 2) negativeCount++;
    }

    final yorumSayisi = yorumlar.length;
    final ortalama =
        toplamAgirlik > 0 ? toplamAgirlikliPuan / toplamAgirlik : 0.0;

    const m = 10;
    const C = 3.0;
    final v = yorumSayisi;
    final wr = (v / (v + m)) * ortalama + (m / (v + m)) * C;

    await hisseRef.update({
      'yorumSayisi': yorumSayisi,
      'ortalamaPuan': ortalama,
      'weightedRating': wr * 2,
      'positiveCount': positiveCount,
      'negativeCount': negativeCount,
    });

    // ── KULLANICI İSTATİSTİKLERİ GÜNCELLE ─────────────────────────
    // Bu kullanıcının tüm hisselerdeki yorumlarını tara, toplam ve ortalama hesapla
    try {
      final tumYorumlar = await FirebaseFirestore.instance
          .collectionGroup('yorumlar')
          .where('uid', isEqualTo: uid)
          .get();

      int kullaniciToplam = 0;
      double kullaniciToplamPuan = 0;
      for (final doc in tumYorumlar.docs) {
        final p = (doc.data()['puan'] as int?) ?? 0;
        if (p >= 1 && p <= 5) {
          kullaniciToplam++;
          kullaniciToplamPuan += p;
        }
      }
      final kullaniciOrtalama = kullaniciToplam > 0
          ? kullaniciToplamPuan / kullaniciToplam
          : 0.0;

      await userRef.update({
        'toplam_yorum':  kullaniciToplam,
        'ortalama_puan': double.parse(kullaniciOrtalama.toStringAsFixed(2)),
      });
    } catch (e) {
      debugPrint('[SOZ_HAKKI] Kullanıcı istatistik güncelleme hatası: $e');
    }

    // ── YORUM HAKKI TÜKET (sadece yeni yorumlar) ──────────────────
    if (yeniYorum) {
      await userRef.update({
        'kullanilan_yorum_hakki': FieldValue.increment(1),
      });
    }

    // ── DUYGUSAL AKIL — SKORLAMA ───────────────────────────────────
    try {
      final user = FirebaseAuth.instance.currentUser;
      final hesapYas = user?.metadata.creationTime != null
          ? DateTime.now().difference(user!.metadata.creationTime!).inDays
          : 0;
      final skor = await DuygusalAkilService.yorumuSkorla(
        yorumMetni: _yorumController.text.trim(),
        puan: _secilenYildiz.toDouble(),
        kullaniciId: uid,
        hesapYasGun: hesapYas,
        toplamYorumSayisi: yorumSayisi,
        yorumCesitliligi: 0.5,
        yorumTimestamp: DateTime.now().millisecondsSinceEpoch ~/ 1000,
        faydaliOy: (_mevcutYorum?['faydali_oy'] as int?) ?? 0,
        faydaliOlmayanOy: (_mevcutYorum?['faydali_olmayan_oy'] as int?) ?? 0,
        hisseKodu: widget.symbol,
      );
      if (skor != null) {
        debugPrint('[SOZ_HAKKI] Skor geldi: duygu=${skor.duyguTonu}, guven=${skor.guvenSkoru}');
        debugPrint('[SOZ_HAKKI] yorumRef.update çağırılıyor: ${yorumRef.path}');
        // 1. Yorum dokümanına sentiment bilgilerini yaz — Halk paneli buradan okuyor
        await yorumRef.update({
          'duygu_tonu':         skor.duyguTonu,
          'guven_skoru':        skor.guvenSkoru,
          'itibar_skoru':       skor.itibarSkoru,
          'manipulasyon_riski': skor.manipulasyonRiski,
        });

        // 2. Hisse skorunu güncelle
        await hisseRef.update({'paynotu_skoru': skor.paynotu});

        // 3. Kullanıcı güven skoru ve mavi tik
        final yeniGuven = skor.guvenSkoru;
        await userRef.update({
          'guven_skoru': yeniGuven,
          'mavi_tik': yeniGuven >= 10,
        });
        if (mounted) {
          setState(() => _kullaniciData = {
                ...(_kullaniciData ?? {}),
                'guven_skoru': yeniGuven,
                'mavi_tik': yeniGuven >= 10,
              });
        }
      }
    } catch (e, st) {
      debugPrint('[SOZ_HAKKI] HATA: $e');
      debugPrint('[SOZ_HAKKI] Stack: $st');
    }

    if (mounted) {
      setState(() => _gonderiliyor = false);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(yeniYorum
              ? 'Yorumunuz kaydedildi!'
              : 'Yorumunuz güncellendi!'),
          backgroundColor: Theme.of(context).colorScheme.primary,
        ),
      );
      Navigator.pop(context);
    }
  }

  @override
  Widget build(BuildContext context) {
    final displayName =
        FirebaseAuth.instance.currentUser?.displayName ?? 'Kullanıcı';
    final harf = displayName.isNotEmpty ? displayName[0].toUpperCase() : 'K';
    final gonderButonYazisi = _mevcutYorum == null ? 'Gönder' : 'Güncelle';

    return Scaffold(
      backgroundColor: Theme.of(context).scaffoldBackgroundColor,
      appBar: AppBar(
        backgroundColor: Theme.of(context).colorScheme.primary,
        elevation: 0,
        leading: IconButton(
          icon: const Icon(Icons.close, color: Colors.white),
          onPressed: () => Navigator.pop(context),
        ),
        title: Text(
          widget.symbol,
          style: const TextStyle(
              color: Colors.white, fontWeight: FontWeight.bold),
        ),
      ),
      body: _yukleniyor
          ? Center(
              child: CircularProgressIndicator(color: Theme.of(context).colorScheme.primary))
          : SingleChildScrollView(
              controller: _scrollController,
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  // ── KULLANICI BİLGİSİ ──────────────────────────
                  Container(
                    color: Theme.of(context).colorScheme.surface,
                    padding: const EdgeInsets.symmetric(
                        horizontal: 14, vertical: 10),
                    child: Row(
                      children: [
                        CircleAvatar(
                          radius: 20,
                          backgroundColor: Theme.of(context).colorScheme.primary,
                          child: Text(harf,
                              style: const TextStyle(
                                  color: Colors.white,
                                  fontWeight: FontWeight.bold,
                                  fontSize: 16)),
                        ),
                        const SizedBox(width: 10),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(displayName,
                                  style: const TextStyle(
                                      fontWeight: FontWeight.bold,
                                      fontSize: 14)),
                              Wrap(
                                spacing: 8,
                                runSpacing: 2,
                                crossAxisAlignment: WrapCrossAlignment.center,
                                children: [
                                  _rozetWidget(),
                                  GestureDetector(
                                    onTap: _yorumKurallariDialog,
                                    child: Text(
                                      'Yorum Kuralları',
                                      style: TextStyle(
                                          fontSize: 11,
                                          color: Theme.of(context).colorScheme.onSurfaceVariant,
                                          decoration:
                                              TextDecoration.underline),
                                    ),
                                  ),
                                ],
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ),

                  const SizedBox(height: 8),

                  // Mevcut yorum uyarısı
                  if (_mevcutYorum != null)
                    Container(
                      margin: const EdgeInsets.only(bottom: 8),
                      padding: const EdgeInsets.symmetric(
                          horizontal: 12, vertical: 8),
                      decoration: BoxDecoration(
                        color: Theme.of(context).colorScheme.primary.withValues(alpha: 0.1),
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: Row(
                        children: [
                          Icon(Icons.info_outline,
                              color: Theme.of(context).colorScheme.primary, size: 16),
                          const SizedBox(width: 8),
                          Expanded(
                            child: Text(
                              'Mevcut yorumunuz güncellenecek.',
                              style: TextStyle(
                                  fontSize: 11,
                                  color: Theme.of(context).colorScheme.primary),
                            ),
                          ),
                        ],
                      ),
                    ),

                  // ── POZİSYON + YILDIZ ──────────────────────────
                  Container(
                    color: Theme.of(context).colorScheme.surface,
                    padding: const EdgeInsets.all(12),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        // Pozisyon seçimi
                        const Text('Pozisyonunuz',
                            style: TextStyle(
                                fontWeight: FontWeight.bold, fontSize: 13)),
                        const SizedBox(height: 8),
                        Row(
                          children: _positionSecenekleri.map((p) {
                            final secili = _secilenPosition == p['value'];
                            return Expanded(
                              child: GestureDetector(
                                onTap: () => setState(
                                    () => _secilenPosition = p['value']),
                                child: Container(
                                  margin: const EdgeInsets.only(right: 6),
                                  padding: const EdgeInsets.symmetric(
                                      vertical: 8),
                                  decoration: BoxDecoration(
                                    color: secili
                                        ? (p['color'] as Color)
                                            .withValues(alpha: 0.1)
                                        : Colors.grey.shade100,
                                    borderRadius: BorderRadius.circular(8),
                                    border: Border.all(
                                      color: secili
                                          ? p['color'] as Color
                                          : Colors.transparent,
                                      width: 1.5,
                                    ),
                                  ),
                                  child: Column(
                                    mainAxisSize: MainAxisSize.min,
                                    children: [
                                      Icon(p['icon'] as IconData,
                                          color: secili
                                              ? p['color'] as Color
                                              : Theme.of(context).colorScheme.onSurfaceVariant,
                                          size: 18),
                                      const SizedBox(height: 3),
                                      Text(
                                        p['label'] as String,
                                        textAlign: TextAlign.center,
                                        style: TextStyle(
                                          fontSize: 10,
                                          fontWeight: secili
                                              ? FontWeight.bold
                                              : FontWeight.normal,
                                          color: secili
                                              ? p['color'] as Color
                                              : Theme.of(context).colorScheme.onSurfaceVariant,
                                        ),
                                      ),
                                    ],
                                  ),
                                ),
                              ),
                            );
                          }).toList(),
                        ),

                        const SizedBox(height: 12),
                        const Divider(height: 1),
                        const SizedBox(height: 12),

                        // Yıldız seçimi (pozisyon seçilince aktif)
                        const Text('Puanınız',
                            style: TextStyle(
                                fontWeight: FontWeight.bold, fontSize: 13)),
                        const SizedBox(height: 8),
                        AbsorbPointer(
                          absorbing: _secilenPosition == null,
                          child: Opacity(
                            opacity: _secilenPosition == null ? 0.4 : 1.0,
                            child: Row(
                              mainAxisAlignment: MainAxisAlignment.center,
                              children: List.generate(5, (i) {
                                return GestureDetector(
                                  onTap: () => setState(
                                      () => _secilenYildiz = i + 1),
                                  child: Icon(
                                    i < _secilenYildiz
                                        ? Icons.star
                                        : Icons.star_border,
                                    size: 40,
                                    color: const Color(0xFFFFC107),
                                  ),
                                );
                              }),
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),

                  const SizedBox(height: 8),

                  // ── YORUM KUTUSU ────────────────────────────────
                  Container(
                    color: Theme.of(context).colorScheme.surface,
                    padding: const EdgeInsets.all(12),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text('Yorumunuz',
                            style: TextStyle(
                                fontWeight: FontWeight.bold, fontSize: 13)),
                        const SizedBox(height: 8),
                        AbsorbPointer(
                          absorbing: _secilenPosition == null,
                          child: Opacity(
                            opacity: _secilenPosition == null ? 0.4 : 1.0,
                            child: TextField(
                              controller: _yorumController,
                              focusNode: _yorumFocusNode,
                              maxLines: 4,
                              maxLength: 225,
                              onChanged: _icerikKontrolEt,
                              decoration: InputDecoration(
                                hintText: _secilenPosition == null
                                    ? 'Önce pozisyon seçin...'
                                    : 'Deneyiminizi paylaşın...',
                                filled: true,
                                fillColor: _icerikDurumu == 'engellendi'
                                    ? Colors.red.shade50
                                    : _icerikDurumu == 'şüpheli'
                                        ? Colors.orange.shade50
                                        : Colors.grey.shade100,
                                border: OutlineInputBorder(
                                  borderRadius: BorderRadius.circular(10),
                                  borderSide: BorderSide.none,
                                ),
                                enabledBorder: OutlineInputBorder(
                                  borderRadius: BorderRadius.circular(10),
                                  borderSide: BorderSide(
                                    color: _icerikDurumu == 'engellendi'
                                        ? Colors.red.shade300
                                        : _icerikDurumu == 'şüpheli'
                                            ? Colors.orange.shade300
                                            : Colors.transparent,
                                    width: 1.5,
                                  ),
                                ),
                                contentPadding: const EdgeInsets.all(12),
                              ),
                            ),
                          ),
                        ),
                        if (_icerikDurumu != 'temiz' && _icerikAciklama.isNotEmpty)
                          Padding(
                            padding: const EdgeInsets.only(top: 6, bottom: 2),
                            child: Row(
                              children: [
                                Icon(
                                  _icerikDurumu == 'engellendi'
                                      ? Icons.block
                                      : Icons.warning_amber_rounded,
                                  size: 14,
                                  color: _icerikDurumu == 'engellendi'
                                      ? Colors.red
                                      : Colors.orange,
                                ),
                                const SizedBox(width: 6),
                                Expanded(
                                  child: Text(
                                    _icerikAciklama,
                                    style: TextStyle(
                                      fontSize: 11,
                                      color: _icerikDurumu == 'engellendi'
                                          ? Colors.red
                                          : Colors.orange.shade800,
                                    ),
                                  ),
                                ),
                              ],
                            ),
                          ),
                        const SizedBox(height: 8),
                        SizedBox(
                          width: double.infinity,
                          child: ElevatedButton(
                            onPressed: (_gonderiliyor || _icerikDurumu == 'engellendi')
                                ? null
                                : _yorumGonder,
                            style: ElevatedButton.styleFrom(
                              backgroundColor: Colors.black,
                              shape: RoundedRectangleBorder(
                                  borderRadius: BorderRadius.circular(8)),
                              padding:
                                  const EdgeInsets.symmetric(vertical: 12),
                            ),
                            child: _gonderiliyor
                                ? const SizedBox(
                                    width: 20,
                                    height: 20,
                                    child: CircularProgressIndicator(
                                        color: Colors.white, strokeWidth: 2),
                                  )
                                : Text(
                                    gonderButonYazisi,
                                    style: const TextStyle(
                                        color: Colors.white,
                                        fontWeight: FontWeight.bold,
                                        fontSize: 15),
                                  ),
                          ),
                        ),
                      ],
                    ),
                  ),

                  const SizedBox(height: 24),
                ],
              ),
            ),
    );
  }
}

class _KuralBaslik extends StatelessWidget {
  final String baslik;
  final Color renk;
  const _KuralBaslik({required this.baslik, this.renk = const Color(0xFF00C853)});

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Container(
          width: 3,
          height: 14,
          decoration: BoxDecoration(
            color: renk,
            borderRadius: BorderRadius.circular(2),
          ),
        ),
        const SizedBox(width: 8),
        Text(
          baslik,
          style: TextStyle(
            fontSize: 13,
            fontWeight: FontWeight.bold,
            color: renk,
          ),
        ),
      ],
    );
  }
}