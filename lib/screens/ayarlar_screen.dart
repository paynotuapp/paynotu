import 'package:flutter/material.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:google_sign_in/google_sign_in.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'yasal_yukumlulukler_screen.dart';
import 'giris_screen.dart';
import 'profil_screen.dart';
import 'geri_bildirim_screen.dart';
import 'package:provider/provider.dart';
import '../providers/theme_provider.dart';
import '../providers/user_provider.dart';

const String _appVersiyon = '1.0.0';

const _kTumBildirimler = 'pref_tum_bildirimler';
const _kEgitimBildirim = 'pref_egitim_bildirim';
const _kHaberBildirim  = 'pref_haber_bildirim';
const _kSembolBildirim = 'pref_sembol_bildirim';
const _kRsiBildirim    = 'pref_rsi_bildirim';
const _kDil            = 'pref_dil';
const _kKisiselIcerik  = 'pref_kisisel_icerik';


class AyarlarScreen extends StatefulWidget {
  const AyarlarScreen({super.key});

  @override
  State<AyarlarScreen> createState() => _AyarlarScreenState();
}

class _AyarlarScreenState extends State<AyarlarScreen> {
  String  _displayName      = '';
  String  _email            = '';
  String? _photoUrl;
  bool    _profilYukleniyor = true;

  bool _tumBildirimler = true;
  bool _kisiselIcerik  = true;

  String _dil = 'tr';

  @override
  void initState() {
    super.initState();
    _yukle();
  }

  Future<void> _yukle() async {
    final provider = context.read<UserProvider>();
    final uid = FirebaseAuth.instance.currentUser?.uid;
    final prefs = await SharedPreferences.getInstance();

    if (uid != null && provider.user == null) {
      await provider.fetchUserData(uid);
    }

    final user = provider.user;

    setState(() {
      _displayName      = user?.displayName ?? FirebaseAuth.instance.currentUser?.displayName ?? '';
      _email            = user?.email ?? FirebaseAuth.instance.currentUser?.email ?? '';
      _photoUrl         = user?.photoURL;
      _profilYukleniyor = false;
      _tumBildirimler   = prefs.getBool(_kTumBildirimler) ?? true;
      _dil              = prefs.getString(_kDil) ?? 'tr';
      _kisiselIcerik    = prefs.getBool(_kKisiselIcerik) ?? true;
    });
  }

  Future<void> _prefBool(String key, bool v) async => (await SharedPreferences.getInstance()).setBool(key, v);
  Future<void> _prefStr(String key, String v) async => (await SharedPreferences.getInstance()).setString(key, v);

  void _snack(String mesaj, {bool hata = false}) {
    if (!mounted) return;
    final cs = Theme.of(context).colorScheme;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Text(mesaj),
      backgroundColor: hata ? cs.error : cs.primary,
      duration: const Duration(seconds: 2),
    ));
  }

  // ── Widgetlar ─────────────────────────────────────────────────────────────

  Widget _bolumBaslik(String baslik) => Padding(
        padding: const EdgeInsets.fromLTRB(16, 24, 16, 8),
        child: Text(baslik,
            style: TextStyle(fontSize: 11, fontWeight: FontWeight.bold,
                color: Theme.of(context).colorScheme.primary, letterSpacing: 1.2)),
      );

  Widget _kart(List<Widget> icerik) {
    final cs = Theme.of(context).colorScheme;
    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 16),
      decoration: BoxDecoration(
        color: cs.surface,
        borderRadius: BorderRadius.circular(14),
        boxShadow: [BoxShadow(color: cs.shadow.withValues(alpha: 0.05), blurRadius: 6, offset: const Offset(0, 2))],
      ),
      child: Column(
        children: List.generate(icerik.length * 2 - 1, (i) {
          if (i.isOdd) return const Divider(height: 1, indent: 52, endIndent: 16);
          return icerik[i ~/ 2];
        }),
      ),
    );
  }

  Widget _oge({
    required IconData ikon,
    required String baslik,
    String? altyazi,
    Color? ikonRenk,
    Widget? trailing,
    VoidCallback? onTap,
  }) {
    final cs = Theme.of(context).colorScheme;
    final renk = ikonRenk ?? cs.primary;
    return InkWell(
      borderRadius: BorderRadius.circular(14),
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 13),
        child: Row(children: [
          Container(
            width: 36, height: 36,
            decoration: BoxDecoration(color: renk.withValues(alpha: 0.10), borderRadius: BorderRadius.circular(9)),
            child: Icon(ikon, size: 20, color: renk),
          ),
          const SizedBox(width: 14),
          Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(baslik, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w500)),
            if (altyazi != null) Text(altyazi, style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant)),
          ])),
          trailing ?? Icon(Icons.arrow_forward_ios, size: 14, color: cs.onSurfaceVariant),
        ]),
      ),
    );
  }

  Widget _toggle({
    required IconData ikon, required String baslik, String? altyazi,
    Color? ikonRenk, required bool deger, required ValueChanged<bool> onChanged,
  }) =>
      _oge(
        ikon: ikon, baslik: baslik, altyazi: altyazi, ikonRenk: ikonRenk,
        trailing: Switch(value: deger, activeTrackColor: Theme.of(context).colorScheme.primary, onChanged: onChanged),
      );

  Widget _kilitliOge({required IconData ikon, required String baslik, String? altyazi}) {
    final cs = Theme.of(context).colorScheme;
    return _oge(
      ikon: ikon, baslik: baslik, altyazi: altyazi, ikonRenk: cs.onSurfaceVariant,
      trailing: Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
        decoration: BoxDecoration(color: cs.surfaceContainerHighest, borderRadius: BorderRadius.circular(8)),
        child: Text('Yakında', style: TextStyle(fontSize: 11, color: cs.onSurfaceVariant)),
      ),
      onTap: () => _snack('Bu özellik yakında kullanıma girecek'),
    );
  }

  // ── AppBar aksiyonları ────────────────────────────────────────────────────

  Widget _dilButon(String emoji, String kod) {
    final cs = Theme.of(context).colorScheme;
    final secili = _dil == kod;
    return GestureDetector(
      onTap: () async {
        if (_dil == kod) return;
        setState(() => _dil = kod);
        await _prefStr(_kDil, kod);
        _snack('Dil değiştirildi — uygulamayı yeniden başlatın');
      },
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 200),
        padding: const EdgeInsets.all(3),
        decoration: BoxDecoration(
          border: Border.all(color: secili ? cs.onPrimary : Colors.transparent, width: 2),
          borderRadius: BorderRadius.circular(6),
          color: secili ? cs.onPrimary.withValues(alpha: 0.2) : Colors.transparent,
        ),
        child: Text(emoji, style: const TextStyle(fontSize: 22)),
      ),
    );
  }

  Widget _temaButon(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final provider = context.watch<ThemeProvider>();
    final ikon = switch (provider.themeMode) {
      ThemeMode.light  => Icons.wb_sunny_outlined,
      ThemeMode.dark   => Icons.dark_mode_outlined,
      ThemeMode.system => Icons.brightness_auto_outlined,
    };
    return GestureDetector(
      onTap: () => context.read<ThemeProvider>().toggleTheme(),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
        child: Icon(ikon, color: cs.onPrimary, size: 24),
      ),
    );
  }

  // ── Profil satırı ─────────────────────────────────────────────────────────

  Widget _hesapProfil() {
    final cs = Theme.of(context).colorScheme;
    return InkWell(
      borderRadius: BorderRadius.circular(14),
      onTap: () async {
        final sonuc = await Navigator.push(context, MaterialPageRoute(builder: (_) => const ProfilScreen()));
        if (sonuc == true) _yukle();
      },
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        child: Row(children: [
          CircleAvatar(
            radius: 26,
            backgroundColor: cs.primary.withValues(alpha: 0.12),
            backgroundImage: (_photoUrl != null && _photoUrl!.isNotEmpty) ? NetworkImage(_photoUrl!) : null,
            child: (_photoUrl == null || _photoUrl!.isEmpty)
                ? Text(
                    _displayName.isNotEmpty ? _displayName[0].toUpperCase() : '?',
                    style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: cs.primary))
                : null,
          ),
          const SizedBox(width: 14),
          Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(
              _profilYukleniyor ? 'Yükleniyor...' : _displayName.isEmpty ? 'İsimsiz' : _displayName,
              style: const TextStyle(fontSize: 15, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 2),
            Text(_email, style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant)),
          ])),
          Icon(Icons.arrow_forward_ios, size: 14, color: cs.onSurfaceVariant),
        ]),
      ),
    );
  }

  // ── Oturum kapat ──────────────────────────────────────────────────────────

  void _oturumuKapat() {
    final cs = Theme.of(context).colorScheme;
    showDialog(
      context: context,
      builder: (_) => AlertDialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: const Text('Oturumu Kapat', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
        content: const Text('Hesabınızdan çıkış yapılacak.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('İptal')),
          ElevatedButton(
            onPressed: () async {
              final nav = Navigator.of(context);
              context.read<UserProvider>().clearUser();
              await GoogleSignIn().signOut();
              await FirebaseAuth.instance.signOut();
              nav.pushAndRemoveUntil(
                MaterialPageRoute(builder: (_) => const GirisScreen()),
                (_) => false,
              );
            },
            style: ElevatedButton.styleFrom(backgroundColor: cs.error),
            child: Text('Çıkış Yap', style: TextStyle(color: cs.onError)),
          ),
        ],
      ),
    );
  }

  // ── BUILD ─────────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Scaffold(
      backgroundColor: Theme.of(context).scaffoldBackgroundColor,
      appBar: AppBar(
        backgroundColor: cs.primary,
        elevation: 0,
        leading: IconButton(
          icon: Icon(Icons.arrow_back, color: cs.onPrimary),
          onPressed: () => Navigator.pop(context),
        ),
        title: Text('Ayarlar',
            style: TextStyle(color: cs.onPrimary, fontSize: 18, fontWeight: FontWeight.bold)),
        actions: [
          _dilButon('🇹🇷', 'tr'),
          const SizedBox(width: 4),
          _dilButon('🇬🇧', 'en'),
          const SizedBox(width: 8),
          _temaButon(context),
          const SizedBox(width: 8),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.only(bottom: 40),
        children: [

          // ── HESAP ──────────────────────────────────────────────────────
          _bolumBaslik('HESAP'),
          _kart([_hesapProfil()]),

          // ── BİLDİRİMLER ────────────────────────────────────────────────
          _bolumBaslik('BİLDİRİMLER'),
          _kart([
            _oge(
              ikon: Icons.notifications_outlined,
              baslik: 'Bildirim Ayarları',
              altyazi: _tumBildirimler ? 'Açık' : 'Kapalı',
              trailing: Icon(Icons.arrow_forward_ios, size: 14, color: cs.onSurfaceVariant),
              onTap: () => Navigator.push(context,
                  MaterialPageRoute(builder: (_) => _BildirimAyarlariScreen(
                    tumBildirimler: _tumBildirimler,
                    onDegisti: () => _yukle(),
                  ))),
            ),
          ]),

          // ── GİZLİLİK ───────────────────────────────────────────────────
          _bolumBaslik('GİZLİLİK'),
          _kart([
            _toggle(
              ikon: Icons.tune_outlined,
              baslik: 'Kişiselleştirilmiş İçerik',
              altyazi: 'İlgi alanlarına göre içerik önerileri',
              deger: _kisiselIcerik,
              onChanged: (v) async {
                setState(() => _kisiselIcerik = v);
                await _prefBool(_kKisiselIcerik, v);
              },
            ),
          ]),

          // ── ABONELİK & ÖDEME ───────────────────────────────────────────
          _bolumBaslik('ABONELİK & ÖDEME'),
          _kart([
            _kilitliOge(ikon: Icons.workspace_premium_outlined, baslik: 'PayNotu Premium',
                altyazi: 'Gelişmiş analiz ve öncelikli destek'),
            _kilitliOge(ikon: Icons.payment_outlined, baslik: 'Ödeme Yöntemleri'),
            _oge(
              ikon: Icons.favorite_border,
              baslik: 'Düzenli Bağışta Bulun',
              altyazi: 'Projeyi destekleyin',
              ikonRenk: cs.tertiary,
              onTap: () => _snack('Bağış özelliği yakında aktif olacak'),
            ),
          ]),

          // ── DESTEK ─────────────────────────────────────────────────────
          _bolumBaslik('DESTEK'),
          _kart([
            _oge(
              ikon: Icons.help_outline,
              baslik: 'Sıkça Sorulan Sorular',
              altyazi: 'support@paynotu.com',
              onTap: () => Navigator.push(context,
                  MaterialPageRoute(builder: (_) => const _SSSScreen())),
            ),
            _oge(
              ikon: Icons.feedback_outlined,
              baslik: 'Geri Bildirim Gönder',
              altyazi: 'info@paynotu.com',
              onTap: () => Navigator.push(context,
                  MaterialPageRoute(builder: (_) => const GeriBildirimScreen())),
            ),
          ]),

          // ── HAKKINDA ───────────────────────────────────────────────────
          _bolumBaslik('HAKKINDA'),
          _kart([
            ListTile(
              leading: Icon(Icons.gavel_outlined),
              title: Text('Yasal Yükümlülükler'),
              trailing: Icon(Icons.chevron_right_rounded),
              onTap: () => Navigator.push(
                context,
                MaterialPageRoute(
                  builder: (_) => const YasalYukumluluklerScreen(),
                ),
              ),
            ),
            _oge(ikon: Icons.info_outline, baslik: 'Uygulama Versiyonu', altyazi: _appVersiyon,
                trailing: const SizedBox.shrink(), onTap: null),
          ]),

          // ── GİRİŞ ──────────────────────────────────────────────────────
          _bolumBaslik('GİRİŞ'),
          _kart([
            _oge(
              ikon: Icons.logout,
              baslik: 'Oturumu Kapat',
              ikonRenk: cs.error,
              trailing: Icon(Icons.arrow_forward_ios, size: 14, color: cs.error),
              onTap: _oturumuKapat,
            ),
          ]),

          const SizedBox(height: 16),
        ],
      ),
    );
  }
}

// ── Bildirim Ayarları Alt Sayfası ─────────────────────────────────────────────

class _BildirimAyarlariScreen extends StatefulWidget {
  final bool tumBildirimler;
  final VoidCallback onDegisti;

  const _BildirimAyarlariScreen({
    required this.tumBildirimler,
    required this.onDegisti,
  });

  @override
  State<_BildirimAyarlariScreen> createState() => _BildirimAyarlariScreenState();
}

class _BildirimAyarlariScreenState extends State<_BildirimAyarlariScreen> {
  bool _kisayolDurum   = true;
  bool _egitimBildirim = true;
  bool _haberBildirim  = true;
  bool _sembolBildirim = true;
  bool _rsiBildirim    = true;

  @override
  void initState() {
    super.initState();
    _yukle();
  }

  Future<void> _yukle() async {
    final prefs = await SharedPreferences.getInstance();
    setState(() {
      _egitimBildirim = prefs.getBool(_kEgitimBildirim) ?? true;
      _haberBildirim  = prefs.getBool(_kHaberBildirim)  ?? true;
      _sembolBildirim = prefs.getBool(_kSembolBildirim) ?? true;
      _rsiBildirim    = prefs.getBool(_kRsiBildirim)    ?? true;
      _kisayolDurum   = _egitimBildirim || _haberBildirim || _sembolBildirim || _rsiBildirim;
    });
  }

  Future<void> _masterDegis(bool deger) async {
    final prefs = await SharedPreferences.getInstance();
    setState(() {
      _kisayolDurum   = deger;
      _egitimBildirim = deger;
      _haberBildirim  = deger;
      _sembolBildirim = deger;
      _rsiBildirim    = deger;
    });
    for (final key in [_kEgitimBildirim, _kHaberBildirim, _kSembolBildirim, _kRsiBildirim]) {
      await prefs.setBool(key, deger);
    }
    widget.onDegisti();
  }

  Future<void> _altDegis(String key, bool deger, void Function(bool) setter) async {
    setState(() => setter(deger));
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(key, deger);
    widget.onDegisti();
  }

  Widget _toggle({
    required IconData ikon,
    required String baslik,
    String? altyazi,
    required bool deger,
    required ValueChanged<bool> onChanged,
  }) {
    final cs = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 13),
      child: Row(children: [
        Container(
          width: 36, height: 36,
          decoration: BoxDecoration(
            color: cs.primary.withValues(alpha: 0.10),
            borderRadius: BorderRadius.circular(9),
          ),
          child: Icon(ikon, size: 20, color: cs.primary),
        ),
        const SizedBox(width: 14),
        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(baslik, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w500)),
          if (altyazi != null) Text(altyazi, style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant)),
        ])),
        Switch(
          value: deger,
          activeTrackColor: cs.primary,
          onChanged: onChanged,
        ),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Scaffold(
      backgroundColor: Theme.of(context).scaffoldBackgroundColor,
      appBar: AppBar(
        backgroundColor: cs.primary,
        elevation: 0,
        leading: IconButton(
          icon: Icon(Icons.arrow_back, color: cs.onPrimary),
          onPressed: () => Navigator.pop(context),
        ),
        title: Text('Bildirim Ayarları',
            style: TextStyle(color: cs.onPrimary, fontWeight: FontWeight.bold)),
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Container(
            decoration: BoxDecoration(
              color: cs.surface,
              borderRadius: BorderRadius.circular(14),
              boxShadow: [BoxShadow(color: cs.shadow.withValues(alpha: 0.05), blurRadius: 6, offset: const Offset(0, 2))],
            ),
            child: Column(children: [
              _toggle(ikon: Icons.notifications_outlined, baslik: 'Tüm Bildirimler',
                  altyazi: 'Tümünü aç / kapat',
                  deger: _kisayolDurum,
                  onChanged: _masterDegis),
              const Divider(height: 1, indent: 52, endIndent: 16),
              _toggle(ikon: Icons.school_outlined, baslik: 'Eğitim Bildirimleri',
                  altyazi: 'İpuçları ve öğretici içerikler', deger: _egitimBildirim,
                  onChanged: (v) => _altDegis(_kEgitimBildirim, v, (x) => _egitimBildirim = x)),
              const Divider(height: 1, indent: 52, endIndent: 16),
              _toggle(ikon: Icons.newspaper_outlined, baslik: 'Haber Bildirimleri',
                  altyazi: 'Piyasa haberleri ve güncel gelişmeler', deger: _haberBildirim,
                  onChanged: (v) => _altDegis(_kHaberBildirim, v, (x) => _haberBildirim = x)),
              const Divider(height: 1, indent: 52, endIndent: 16),
              _toggle(ikon: Icons.candlestick_chart_outlined, baslik: 'Sembol Bildirimleri',
                  altyazi: 'Yalnızca takipteki sembolleriniz', deger: _sembolBildirim,
                  onChanged: (v) => _altDegis(_kSembolBildirim, v, (x) => _sembolBildirim = x)),
              const Divider(height: 1, indent: 52, endIndent: 16),
              _toggle(ikon: Icons.show_chart, baslik: 'RSI Bildirimleri',
                  altyazi: 'Aşırı alım / satım sinyalleri', deger: _rsiBildirim,
                  onChanged: (v) => _altDegis(_kRsiBildirim, v, (x) => _rsiBildirim = x)),
            ]),
          ),
        ],
      ),
    );
  }
}

// ── SSS ───────────────────────────────────────────────────────────────────────

class _SSSScreen extends StatelessWidget {
  const _SSSScreen();

  static const _sorular = [
    ('PayNotu skoru nasıl hesaplanır?',
     'Finansal motor (%65) ve duygusal motor (%35) birleşimiyle hesaplanır. Finansal motor TOPSIS + Entropi ağırlık yöntemiyle 7 kriter üzerinden çalışır. Duygusal motor ise kullanıcı yorumlarını Bayesian stabilizer, zaman sönümlemesi ve anomali tespitinden geçirerek işler.'),
    ('Spekülatif derece ne anlama gelir?',
     'Normal: düşük risk, Dikkat: orta risk, Spekülatif: yüksek risk, Aşırı Riskli: manipülasyon şüphesi. Finansal motor tarafından teknik göstergelerle günlük olarak güncellenir.'),
    ('Takip listeme nasıl hisse eklerim?',
     'Hisse kartını sola kaydırarak göz simgesine tıklayın veya hisse detay ekranındaki takip butonunu kullanın.'),
    ('Yorum puanlarım neden değişiyor?',
     'Yorumlarınız zaman sönümlemesi, kullanıcı güven çarpanı ve Bayesian stabilizer katmanlarından geçerek dinamik olarak değerlendirilir. Eski yorumların ağırlığı her ay azalır.'),
    ('Balina tuzağı nedir?',
     'Bir hissenin açılışta %9+ yükselerek kapanışta %5+ düşmesi durumu. Organize manipülasyon işareti olabilir. Sistem bu örüntüyü otomatik tespit eder.'),
    ('Günde kaç yorum yapabilirim?',
     'Her kullanıcı günde en fazla 3 yorum yapabilir. Yorumlarınızın ağırlığı güven skorunuza ve geçmiş yorumlarınızın isabetine göre belirlenir.'),
  ];

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Scaffold(
      backgroundColor: Theme.of(context).scaffoldBackgroundColor,
      appBar: AppBar(
        backgroundColor: cs.primary,
        leading: IconButton(
          icon: Icon(Icons.arrow_back, color: cs.onPrimary),
          onPressed: () => Navigator.pop(context),
        ),
        title: Text('Sıkça Sorulan Sorular',
            style: TextStyle(color: cs.onPrimary, fontWeight: FontWeight.bold)),
      ),
      body: ListView.builder(
        padding: const EdgeInsets.all(16),
        itemCount: _sorular.length,
        itemBuilder: (ctx, i) {
          final (soru, cevap) = _sorular[i];
          final ctxCs = Theme.of(ctx).colorScheme;
          return Container(
            margin: const EdgeInsets.only(bottom: 10),
            decoration: BoxDecoration(
              color: ctxCs.surface,
              borderRadius: BorderRadius.circular(12),
              boxShadow: [BoxShadow(color: ctxCs.shadow.withValues(alpha: 0.04), blurRadius: 4)],
            ),
            child: ExpansionTile(
              tilePadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
              iconColor: ctxCs.primary,
              collapsedIconColor: ctxCs.onSurfaceVariant,
              title: Text(soru, style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600)),
              children: [
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
                  child: Text(cevap, style: TextStyle(fontSize: 13, color: ctxCs.onSurface, height: 1.5)),
                ),
              ],
            ),
          );
        },
      ),
    );
  }
}
