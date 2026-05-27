import 'dart:io';
import 'package:cached_network_image/cached_network_image.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:firebase_storage/firebase_storage.dart';
import 'package:flutter/material.dart';
import 'package:flutter_form_builder/flutter_form_builder.dart';
import 'package:form_builder_validators/form_builder_validators.dart';
import 'package:image_cropper/image_cropper.dart';
import 'package:image_picker/image_picker.dart';
import 'package:intl/intl.dart';
import 'package:percent_indicator/percent_indicator.dart';
import 'package:google_sign_in/google_sign_in.dart';
import 'package:provider/provider.dart';
import '../models/user_model.dart';
import '../providers/user_provider.dart';
import '../services/lokasyon_service.dart';
import 'giris_screen.dart';

class ProfilScreen extends StatefulWidget {
  const ProfilScreen({super.key});

  @override
  State<ProfilScreen> createState() => _ProfilScreenState();
}

class _ProfilScreenState extends State<ProfilScreen> {
  final _formKey = GlobalKey<FormBuilderState>();
  bool _kaydediliyor = false;
  bool _fotYukleniyor = false;
  bool _lokasyonYukleniyor = false;

  // Hangi accordion açık: 0=kullanıcı, 1=kimlik, 2=sistem
  int _acikPanel = 0;

  String? _seciliUlke = 'Türkiye';
  String? _seciliIl;
  String? _seciliIlce;

  final _lokasyon = LokasyonService.instance;

  static const List<String> _ulkeler = [
    'Türkiye', 'Almanya', 'Amerika Birleşik Devletleri',
    'Avustralya', 'Avusturya', 'Azerbaycan', 'Belçika',
    'Birleşik Arap Emirlikleri', 'Birleşik Krallık',
    'Fransa', 'Hollanda', 'İspanya', 'İsveç', 'İsviçre',
    'İtalya', 'Japonya', 'Kanada', 'Kazakistan',
    'Kuzey Kıbrıs', 'Norveç', 'Suudi Arabistan',
    'Ukrayna', 'Yunanistan',
  ];

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      final uid = FirebaseAuth.instance.currentUser?.uid;
      if (uid != null) {
        await context.read<UserProvider>().fetchUserData(uid);
      }
      setState(() => _lokasyonYukleniyor = true);
      await _lokasyon.yukle();
      if (mounted) setState(() => _lokasyonYukleniyor = false);
    });
  }

  Future<void> _fotoDegistir() async {
    final picker = ImagePicker();
    final picked = await picker.pickImage(source: ImageSource.gallery);
    if (picked == null) return;

    final cropped = await ImageCropper().cropImage(
      sourcePath: picked.path,
      aspectRatio: const CropAspectRatio(ratioX: 1, ratioY: 1),
      compressQuality: 85,
      compressFormat: ImageCompressFormat.jpg,
      uiSettings: [
        AndroidUiSettings(toolbarTitle: 'Fotoğrafı Kırp', lockAspectRatio: true),
      ],
    );
    if (cropped == null) return;

    final dosya = File(cropped.path);
    final boyut = await dosya.length();
    if (boyut > 2 * 1024 * 1024) {
      _snack('Fotoğraf 2MB\'dan küçük olmalı', hata: true);
      return;
    }

    final user = FirebaseAuth.instance.currentUser;
    if (user == null) return;

    setState(() => _fotYukleniyor = true);
    try {
      final ref = FirebaseStorage.instance.ref().child('avatars/${user.uid}.jpg');
      await ref.putFile(dosya);
      final url = await ref.getDownloadURL();
      await user.updatePhotoURL(url);
      await FirebaseFirestore.instance
          .collection('users').doc(user.uid)
          .set({'photoURL': url}, SetOptions(merge: true));
      if (mounted) {
        context.read<UserProvider>().updatePhotoURLAnlik(url);
        await context.read<UserProvider>().fetchUserData(user.uid);
        _snack('Fotoğraf güncellendi');
      }
    } catch (e) {
      _snack('Fotoğraf yüklenemedi: $e', hata: true);
    } finally {
      if (mounted) setState(() => _fotYukleniyor = false);
    }
  }

  Future<void> _kaydetKullaniciBilgileri() async {
    if (!(_formKey.currentState?.saveAndValidate() ?? false)) return;
    final degerler = _formKey.currentState!.value;
    final provider = context.read<UserProvider>();
    setState(() => _kaydediliyor = true);
    try {
      final yeniUsername = (degerler['username'] as String?)?.trim().toLowerCase();
      if (yeniUsername != null && yeniUsername.isNotEmpty &&
          yeniUsername != provider.user?.username) {
        final hata = await provider.updateUsername(yeniUsername);
        if (hata != null) { _snack(hata, hata: true); return; }
      }
    } catch (e) {
      _snack('Hata: $e', hata: true);
    } finally {
      if (mounted) setState(() => _kaydediliyor = false);
    }
  }

  Future<void> _kaydetKimlikBilgileri() async {
    if (!(_formKey.currentState?.saveAndValidate() ?? false)) return;
    final degerler = _formKey.currentState!.value;
    final provider = context.read<UserProvider>();
    setState(() => _kaydediliyor = true);
    try {
      final tamIsim =
          '${(degerler['ad'] as String? ?? '').trim()} ${(degerler['soyad'] as String? ?? '').trim()}'.trim();
      final data = {
        'ad':          (degerler['ad']      as String? ?? '').trim(),
        'soyad':       (degerler['soyad']   as String? ?? '').trim(),
        'displayName': tamIsim,
        'telefon':     (degerler['telefon'] as String? ?? '').trim(),
        'meslek':      (degerler['meslek']  as String? ?? '').trim(),
        'adres':       (degerler['adres']   as String? ?? '').trim(),
        'ulke':  _seciliUlke ?? 'Türkiye',
        'il':    _seciliIl   ?? '',
        'ilce':  _seciliIlce ?? '',
      };
      final hata = await provider.updateProfile(data);
      if (hata != null) { _snack(hata, hata: true); return; }
      await FirebaseAuth.instance.currentUser?.updateDisplayName(tamIsim);
      _snack('Bilgiler kaydedildi');
    } finally {
      if (mounted) setState(() => _kaydediliyor = false);
    }
  }

  void _sifreBottomSheet(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final mevcutCtrl  = TextEditingController();
    final yeniCtrl    = TextEditingController();
    final tekrarCtrl  = TextEditingController();
    bool mevcutGizli  = true;
    bool yeniGizli    = true;
    bool tekrarGizli  = true;

    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (_) => StatefulBuilder(
        builder: (ctx, setModalState) => Padding(
          padding: EdgeInsets.fromLTRB(16, 20, 16,
              MediaQuery.of(ctx).viewInsets.bottom + 24),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Container(width: 40, height: 4,
                decoration: BoxDecoration(color: cs.outline.withValues(alpha: 0.4),
                    borderRadius: BorderRadius.circular(2))),
            const SizedBox(height: 16),
            Text('Şifre Değiştir',
                style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold, color: cs.onSurface)),
            const SizedBox(height: 16),
            TextField(
              controller: mevcutCtrl,
              obscureText: mevcutGizli,
              decoration: InputDecoration(
                hintText: 'Mevcut Şifre',
                hintStyle: TextStyle(color: cs.onSurface.withValues(alpha: 0.38)),
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
                filled: true, fillColor: cs.surface,
                suffixIcon: IconButton(
                  icon: Icon(mevcutGizli ? Icons.visibility_outlined : Icons.visibility_off_outlined),
                  onPressed: () => setModalState(() => mevcutGizli = !mevcutGizli),
                ),
              ),
            ),
            const SizedBox(height: 10),
            TextField(
              controller: yeniCtrl,
              obscureText: yeniGizli,
              decoration: InputDecoration(
                hintText: 'Yeni Şifre',
                hintStyle: TextStyle(color: cs.onSurface.withValues(alpha: 0.38)),
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
                filled: true, fillColor: cs.surface,
                suffixIcon: IconButton(
                  icon: Icon(yeniGizli ? Icons.visibility_outlined : Icons.visibility_off_outlined),
                  onPressed: () => setModalState(() => yeniGizli = !yeniGizli),
                ),
              ),
            ),
            const SizedBox(height: 10),
            TextField(
              controller: tekrarCtrl,
              obscureText: tekrarGizli,
              decoration: InputDecoration(
                hintText: 'Yeni Şifre (Tekrar)',
                hintStyle: TextStyle(color: cs.onSurface.withValues(alpha: 0.38)),
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
                filled: true, fillColor: cs.surface,
                suffixIcon: IconButton(
                  icon: Icon(tekrarGizli ? Icons.visibility_outlined : Icons.visibility_off_outlined),
                  onPressed: () => setModalState(() => tekrarGizli = !tekrarGizli),
                ),
              ),
            ),
            const SizedBox(height: 20),
            SizedBox(
              width: double.infinity,
              child: ElevatedButton(
                onPressed: () async {
                  if (yeniCtrl.text != tekrarCtrl.text) {
                    _snack('Şifreler eşleşmiyor', hata: true); return;
                  }
                  if (yeniCtrl.text.length < 6) {
                    _snack('Şifre en az 6 karakter olmalı', hata: true); return;
                  }
                  if (mevcutCtrl.text.isEmpty) {
                    _snack('Mevcut şifre gerekli', hata: true); return;
                  }
                  try {
                    final u = FirebaseAuth.instance.currentUser!;
                    final nav = Navigator.of(context);
                    final cred = EmailAuthProvider.credential(
                        email: u.email ?? '', password: mevcutCtrl.text);
                    await u.reauthenticateWithCredential(cred);
                    await u.updatePassword(yeniCtrl.text);
                    if (mounted) nav.pop();
                    _snack('Şifre başarıyla güncellendi');
                  } catch (e) {
                    _snack('Hata: $e', hata: true);
                  }
                },
                style: ElevatedButton.styleFrom(
                  backgroundColor: cs.primary,
                  padding: const EdgeInsets.symmetric(vertical: 14),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                ),
                child: Text('Güncelle', style: TextStyle(color: cs.onPrimary, fontWeight: FontWeight.bold)),
              ),
            ),
          ]),
        ),
      ),
    );
  }

  void _hesapSilDialog() {
    final onayCtrl = TextEditingController();
    final cs = Theme.of(context).colorScheme;
    showDialog(
      context: context,
      builder: (_) => AlertDialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: Row(children: [
          Icon(Icons.warning_amber_rounded, color: cs.error, size: 22),
          const SizedBox(width: 8),
          Text('Hesabı Sil', style: TextStyle(color: cs.error, fontWeight: FontWeight.bold, fontSize: 16)),
        ]),
        content: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Text('Bu işlem geri alınamaz. Tüm verileriniz kalıcı olarak silinir.',
              style: TextStyle(fontSize: 13, height: 1.4)),
          const SizedBox(height: 16),
          Text('Onaylamak için "HESABIMI SİL" yazın:',
              style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant)),
          const SizedBox(height: 8),
          TextField(controller: onayCtrl,
              decoration: const InputDecoration(hintText: 'HESABIMI SİL', border: OutlineInputBorder(),
                  contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 10))),
        ]),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('İptal')),
          ElevatedButton(
            onPressed: () async {
              if (onayCtrl.text.trim() != 'HESABIMI SİL') {
                _snack('Onay metni hatalı', hata: true);
                return;
              }
              final nav = Navigator.of(context);
              final provider = context.read<UserProvider>();
              try {
                final u = FirebaseAuth.instance.currentUser!;
                final uid = u.uid;

                // 1. Storage avatarı sil
                try {
                  await FirebaseStorage.instance
                      .ref().child('avatars/$uid.jpg').delete();
                } catch (_) {}

                // 2. usernames koleksiyonundan sil
                try {
                  final userDoc = await FirebaseFirestore.instance
                      .collection('users').doc(uid).get();
                  final username = userDoc.data()?['username'];
                  if (username != null && username.isNotEmpty) {
                    await FirebaseFirestore.instance
                        .collection('usernames').doc(username).delete();
                  }
                } catch (_) {}

                // 3. Firestore dökümanı sil
                await FirebaseFirestore.instance
                    .collection('users').doc(uid).delete();

                // 4. Provider temizle
                provider.clearUser();

                // 5. Google bağlantısını tamamen kopar
                try { await GoogleSignIn().disconnect(); } catch (_) {}
                await GoogleSignIn().signOut();

                // 6. Firebase Auth'tan sil
                await u.delete();

                // 7. Giriş ekranına yönlendir
                nav.pushAndRemoveUntil(
                  MaterialPageRoute(builder: (_) => const GirisScreen()),
                  (_) => false,
                );
              } on FirebaseAuthException catch (e) {
                if (e.code == 'requires-recent-login') {
                  // Yeniden giriş yaptır
                  if (mounted) Navigator.pop(context);
                  _snack('Güvenlik doğrulaması gerekiyor. Lütfen tekrar giriş yapın.');
                  await Future.delayed(const Duration(seconds: 2));
                  provider.clearUser();
                  try { await GoogleSignIn().disconnect(); } catch (_) {}
                  await GoogleSignIn().signOut();
                  await FirebaseAuth.instance.signOut();
                  nav.pushAndRemoveUntil(
                    MaterialPageRoute(builder: (_) => const GirisScreen()),
                    (_) => false,
                  );
                } else {
                  _snack('Hata: ${e.message}', hata: true);
                }
              } catch (e) {
                _snack('Hata: $e', hata: true);
              }
            },
            style: ElevatedButton.styleFrom(backgroundColor: cs.error),
            child: Text('Hesabı Sil', style: TextStyle(color: cs.onError)),
          ),
        ],
      ),
    );
  }

  void _snack(String mesaj, {bool hata = false}) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Text(mesaj),
      backgroundColor: hata
          ? Theme.of(context).colorScheme.error
          : Theme.of(context).colorScheme.primary,
      duration: const Duration(seconds: 2),
    ));
  }

  InputDecoration _inputDeco(String hint) {
    final cs = Theme.of(context).colorScheme;
    return InputDecoration(
      hintText: hint,
      hintStyle: TextStyle(color: cs.onSurface.withValues(alpha: 0.38), fontSize: 14),
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
        borderSide: BorderSide(color: cs.outline.withValues(alpha: 0.4)),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
        borderSide: BorderSide(color: cs.primary, width: 1.5),
      ),
      filled: true,
      fillColor: cs.surface,
      contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
    );
  }

  Widget _okumaSatiri(String baslik, String? deger) {
    if (deger == null || deger.isEmpty) return const SizedBox.shrink();
    final cs = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        SizedBox(width: 110,
            child: Text(baslik,
                style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant, fontWeight: FontWeight.w500))),
        Expanded(child: Text(deger, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w500))),
      ]),
    );
  }

  Widget _panel({
    required int index,
    required IconData ikon,
    required String baslik,
    required Widget icerik,
  }) {
    final cs   = Theme.of(context).colorScheme;
    final acik = _acikPanel == index;
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      decoration: BoxDecoration(
        color: cs.surface,
        borderRadius: BorderRadius.circular(14),
        boxShadow: [BoxShadow(color: cs.shadow.withValues(alpha: 0.04), blurRadius: 6, offset: const Offset(0, 2))],
      ),
      child: Column(children: [
        InkWell(
          onTap: () => setState(() => _acikPanel = acik ? -1 : index),
          borderRadius: BorderRadius.circular(14),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
            child: Row(children: [
              Container(
                width: 32, height: 32,
                decoration: BoxDecoration(color: cs.primaryContainer, borderRadius: BorderRadius.circular(8)),
                child: Icon(ikon, size: 17, color: cs.primary),
              ),
              const SizedBox(width: 12),
              Expanded(child: Text(baslik,
                  style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: cs.onSurface))),
              Icon(acik ? Icons.keyboard_arrow_up : Icons.keyboard_arrow_down,
                  color: cs.onSurfaceVariant),
            ]),
          ),
        ),
        if (acik) ...[
          Divider(height: 1, color: cs.outline.withValues(alpha: 0.2)),
          Padding(padding: const EdgeInsets.fromLTRB(16, 12, 16, 16), child: icerik),
        ],
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<UserProvider>();
    final user     = provider.user;
    final cs       = Theme.of(context).colorScheme;

    if (provider.yukleniyor && user == null) {
      return Scaffold(body: Center(child: CircularProgressIndicator(color: cs.primary)));
    }

    final ilceler = _seciliIl != null ? _lokasyon.ilceListesi(_seciliIl!) : <String>[];
    final displayParcalar = (user?.displayName ?? '').trim().split(' ');
    final ad    = displayParcalar.isNotEmpty ? displayParcalar.first : '';
    final soyad = displayParcalar.length > 1 ? displayParcalar.skip(1).join(' ') : '';
    final emailGiris = FirebaseAuth.instance.currentUser?.providerData
            .any((p) => p.providerId == 'password') ?? false;

    return Scaffold(
      backgroundColor: cs.surfaceContainerLowest,
      body: CustomScrollView(
        slivers: [
          SliverAppBar(
            expandedHeight: 200,
            pinned: true,
            backgroundColor: cs.primary,
            leading: IconButton(
              icon: Icon(Icons.arrow_back, color: cs.onPrimary),
              onPressed: () => Navigator.pop(context),
            ),
            title: Text('Profilim',
                style: TextStyle(color: cs.onPrimary, fontSize: 18, fontWeight: FontWeight.bold)),
            actions: [
              if (_kaydediliyor)
                Padding(
                  padding: const EdgeInsets.only(right: 16),
                  child: Center(child: SizedBox(width: 20, height: 20,
                      child: CircularProgressIndicator(strokeWidth: 2, color: cs.onPrimary))),
                ),
            ],
            flexibleSpace: FlexibleSpaceBar(
              background: Stack(fit: StackFit.expand, children: [
                Container(color: cs.primary),
                Center(
                  child: Padding(
                    padding: const EdgeInsets.only(top: 40),
                    child: GestureDetector(
                      onTap: _fotoDegistir,
                      child: Hero(
                        tag: 'profil_avatar',
                        child: Stack(clipBehavior: Clip.none, children: [
                          CircleAvatar(
                            radius: 46,
                            backgroundColor: cs.onPrimary.withValues(alpha: 0.25),
                            child: _fotYukleniyor
                                ? CircularProgressIndicator(color: cs.onPrimary)
                                : (user?.photoURL != null && user!.photoURL!.isNotEmpty)
                                    ? ClipOval(
                                        child: CachedNetworkImage(
                                          imageUrl: user.photoURL!,
                                          width: 92, height: 92, fit: BoxFit.cover,
                                          placeholder: (_, _) => CircularProgressIndicator(color: cs.onPrimary),
                                          errorWidget: (_, _, _) => _avatarHarf(user, cs),
                                        ),
                                      )
                                    : _avatarHarf(user, cs),
                          ),
                          Positioned(right: 0, bottom: 0,
                            child: Container(
                              width: 26, height: 26,
                              decoration: BoxDecoration(
                                color: cs.primary, shape: BoxShape.circle,
                                border: Border.all(color: cs.onPrimary, width: 2),
                              ),
                              child: Icon(Icons.camera_alt, size: 13, color: cs.onPrimary),
                            ),
                          ),
                        ]),
                      ),
                    ),
                  ),
                ),
              ]),
            ),
          ),

          SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 40),
              child: Column(children: [
                _doluluKarti(user),
                const SizedBox(height: 16),

                _panel(
                  index: 0,
                  ikon: Icons.manage_accounts_outlined,
                  baslik: 'Kullanıcı Bilgileri',
                  icerik: _kullaniciBilgileriPaneli(user, emailGiris),
                ),

                _panel(
                  index: 1,
                  ikon: Icons.badge_outlined,
                  baslik: 'Kimlik Bilgileri',
                  icerik: _kimlikBilgileriPaneli(user, ad, soyad, ilceler),
                ),

                _panel(
                  index: 2,
                  ikon: Icons.bar_chart_outlined,
                  baslik: 'Sistem Bilgileri',
                  icerik: _sistemBilgileriPaneli(user),
                ),

                const SizedBox(height: 8),
                OutlinedButton.icon(
                  onPressed: _hesapSilDialog,
                  icon: Icon(Icons.delete_forever_outlined, color: cs.error, size: 18),
                  label: Text('Hesabı Sil', style: TextStyle(color: cs.error, fontSize: 14)),
                  style: OutlinedButton.styleFrom(
                    side: BorderSide(color: cs.error),
                    padding: const EdgeInsets.symmetric(vertical: 14),
                    minimumSize: const Size(double.infinity, 0),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                  ),
                ),
              ]),
            ),
          ),
        ],
      ),
    );
  }

  Widget _avatarHarf(UserModel? user, ColorScheme cs) {
    final isim = user?.displayName ?? '';
    return Text(isim.isNotEmpty ? isim[0].toUpperCase() : '?',
        style: TextStyle(fontSize: 34, fontWeight: FontWeight.bold, color: cs.onPrimary));
  }

  Widget _doluluKarti(UserModel? user) {
    final cs    = Theme.of(context).colorScheme;
    final oran  = user?.completionRate ?? 0.0;
    final yuzde = (oran * 100).toInt();
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: cs.surface,
        borderRadius: BorderRadius.circular(14),
        boxShadow: [BoxShadow(color: cs.shadow.withValues(alpha: 0.04), blurRadius: 6, offset: const Offset(0, 2))],
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
          Text('Profil Doluluk Oranı',
              style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: cs.onSurface)),
          Text('%$yuzde',
              style: TextStyle(fontSize: 13, fontWeight: FontWeight.bold, color: cs.primary)),
        ]),
        const SizedBox(height: 10),
        LinearPercentIndicator(
          lineHeight: 8,
          percent: oran.clamp(0.0, 1.0),
          progressColor: cs.primary,
          backgroundColor: cs.primaryContainer,
          barRadius: const Radius.circular(4),
          padding: EdgeInsets.zero,
        ),
        if (yuzde == 100) ...[
          const SizedBox(height: 8),
          Row(children: [
            Icon(Icons.verified, size: 16, color: cs.primary),
            const SizedBox(width: 4),
            Text('Onaylı Hesap',
                style: TextStyle(fontSize: 12, color: cs.primary, fontWeight: FontWeight.w600)),
          ]),
        ],
      ]),
    );
  }

  Widget _kullaniciBilgileriPaneli(UserModel? user, bool emailGiris) {
    final cs = Theme.of(context).colorScheme;
    final usernameKilitli = user?.lastUsernameChange != null &&
        DateTime.now().difference(user!.lastUsernameChange!).inDays < 30;

    return FormBuilder(
      key: _formKey,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        FormBuilderTextField(
          name: 'username',
          initialValue: user?.username ?? '',
          enabled: !usernameKilitli,
          autocorrect: false,
          enableSuggestions: false,
          keyboardType: TextInputType.visiblePassword,
          decoration: _inputDeco(usernameKilitli ? 'Kullanıcı Adı (Kilitli)' : '@kullanici_adi'),
          validator: FormBuilderValidators.match(
            RegExp(r'^[a-z0-9._]{3,15}$'),
            errorText: '3-15 karakter, küçük harf/rakam/nokta/alt çizgi',
          ),
        ),
        if (usernameKilitli) ...[
          const SizedBox(height: 4),
          Text(
            '${DateFormat('dd.MM.yyyy').format(user.lastUsernameChange!.add(const Duration(days: 14)))} tarihine kadar değiştirilemez',
            style: TextStyle(fontSize: 11, color: cs.onSurfaceVariant),
          ),
        ],

        if (emailGiris) ...[
          const SizedBox(height: 16),
          Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
            Text('Şifre', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w500, color: cs.onSurface)),
            TextButton.icon(
              onPressed: () => _sifreBottomSheet(context),
              icon: Icon(Icons.key_outlined, size: 15, color: cs.primary),
              label: Text('Değiştir', style: TextStyle(fontSize: 12, color: cs.primary)),
              style: TextButton.styleFrom(padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4)),
            ),
          ]),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
            decoration: BoxDecoration(
              color: cs.surface,
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: cs.outline.withValues(alpha: 0.4)),
            ),
            child: Text('••••••••', style: TextStyle(fontSize: 14, color: cs.onSurfaceVariant, letterSpacing: 2)),
          ),
        ],

        const SizedBox(height: 16),
        SizedBox(
          width: double.infinity,
          child: ElevatedButton(
            onPressed: _kaydediliyor ? null : _kaydetKullaniciBilgileri,
            style: ElevatedButton.styleFrom(
              backgroundColor: cs.primary,
              padding: const EdgeInsets.symmetric(vertical: 12),
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
            ),
            child: Text('Kaydet', style: TextStyle(color: cs.onPrimary, fontWeight: FontWeight.bold)),
          ),
        ),
      ]),
    );
  }

  Widget _kimlikBilgileriPaneli(UserModel? user, String ad, String soyad, List<String> ilceler) {
    final cs = Theme.of(context).colorScheme;
    return FormBuilder(
      key: _formKey,
      child: Column(children: [
        Row(children: [
          Expanded(child: FormBuilderTextField(name: 'ad', initialValue: ad,
              decoration: _inputDeco('Ad *'),
              validator: FormBuilderValidators.required(errorText: 'Zorunlu'))),
          const SizedBox(width: 10),
          Expanded(child: FormBuilderTextField(name: 'soyad', initialValue: soyad,
              decoration: _inputDeco('Soyad *'),
              validator: FormBuilderValidators.required(errorText: 'Zorunlu'))),
        ]),
        const SizedBox(height: 10),
        FormBuilderTextField(name: 'telefon', initialValue: user?.phoneNumber ?? '',
            keyboardType: TextInputType.phone, decoration: _inputDeco('Telefon *'),
            validator: FormBuilderValidators.required(errorText: 'Zorunlu')),
        const SizedBox(height: 10),
        FormBuilderTextField(name: 'meslek', initialValue: user?.profession ?? '',
            decoration: _inputDeco('Meslek')),
        const SizedBox(height: 10),
        DropdownButtonFormField<String>(
          initialValue: _seciliUlke,
          decoration: _inputDeco('Ülke'),
          isExpanded: true,
          items: _ulkeler.map((e) => DropdownMenuItem(value: e, child: Text(e))).toList(),
          onChanged: (v) => setState(() { _seciliUlke = v; _seciliIl = null; _seciliIlce = null; }),
        ),
        if (_seciliUlke == 'Türkiye') ...[
          const SizedBox(height: 10),
          _lokasyonYukleniyor
              ? Center(child: CircularProgressIndicator(color: cs.primary))
              : DropdownButtonFormField<String>(
                  initialValue: _seciliIl,
                  decoration: _inputDeco('İl'),
                  isExpanded: true,
                  hint: Text('İl seçin', style: TextStyle(color: cs.onSurface.withValues(alpha: 0.38))),
                  items: _lokasyon.ilAdlari.map((e) => DropdownMenuItem(value: e, child: Text(e))).toList(),
                  onChanged: (v) => setState(() { _seciliIl = v; _seciliIlce = null; }),
                ),
          if (_seciliIl != null) ...[
            const SizedBox(height: 10),
            DropdownButtonFormField<String>(
              initialValue: _seciliIlce,
              decoration: _inputDeco('İlçe'),
              isExpanded: true,
              hint: Text('İlçe seçin', style: TextStyle(color: cs.onSurface.withValues(alpha: 0.38))),
              items: ilceler.map((e) => DropdownMenuItem(value: e, child: Text(e))).toList(),
              onChanged: (v) => setState(() => _seciliIlce = v),
            ),
          ],
        ],
        const SizedBox(height: 10),
        FormBuilderTextField(name: 'adres', initialValue: user?.address ?? '',
            decoration: _inputDeco('Açık Adres')),
        const SizedBox(height: 16),
        SizedBox(
          width: double.infinity,
          child: ElevatedButton(
            onPressed: _kaydediliyor ? null : _kaydetKimlikBilgileri,
            style: ElevatedButton.styleFrom(
              backgroundColor: cs.primary,
              padding: const EdgeInsets.symmetric(vertical: 12),
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
            ),
            child: Text('Kaydet', style: TextStyle(color: cs.onPrimary, fontWeight: FontWeight.bold)),
          ),
        ),
      ]),
    );
  }

  Widget _sistemBilgileriPaneli(UserModel? user) {
    final cs = Theme.of(context).colorScheme;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      _istatistikSatiri(cs, Icons.rate_review_outlined, 'Toplam Yorum',
          user?.totalComments == null || user!.totalComments == 0
              ? '—'
              : '${user.totalComments}'),
      _istatistikSatiri(cs, Icons.star_outline, 'Verilen Puan Ortalaması',
          user?.averageRating == null || user!.averageRating == 0
              ? '—'
              : '${user.averageRating.toStringAsFixed(1)} / 5'),
      _istatistikSatiri(cs, Icons.verified_user_outlined, 'Güven Skoru',
          user?.trustScore == null || user!.trustScore == 0
              ? '—'
              : '${user.trustScore.toStringAsFixed(1)} / 10'),
      const SizedBox(height: 12),
      _okumaSatiri('Üyelik Tarihi',
          user?.createdAt != null
              ? DateFormat('dd MMMM yyyy', 'tr_TR').format(user!.createdAt!)
              : null),
      _okumaSatiri('Son Giriş',
          user?.lastLogin != null
              ? DateFormat('dd MMMM yyyy HH:mm', 'tr_TR').format(user!.lastLogin!)
              : null),
    ]);
  }

  Widget _istatistikSatiri(ColorScheme cs, IconData ikon, String baslik, String deger) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(children: [
        Icon(ikon, size: 18, color: cs.primary),
        const SizedBox(width: 10),
        Expanded(child: Text(baslik,
            style: TextStyle(fontSize: 13, color: cs.onSurfaceVariant))),
        Text(deger,
            style: TextStyle(fontSize: 13, fontWeight: FontWeight.bold, color: cs.onSurface)),
      ]),
    );
  }
}
