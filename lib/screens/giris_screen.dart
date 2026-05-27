import 'package:flutter/material.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:google_sign_in/google_sign_in.dart';
import '../main.dart';
import '../services/sozlesme_service.dart';
import '../widgets/sozlesme_widgets.dart';
import 'otp_screen.dart';

class GirisScreen extends StatefulWidget {
  const GirisScreen({super.key});

  @override
  State<GirisScreen> createState() => _GirisScreenState();
}

class _GirisScreenState extends State<GirisScreen> {
  final _formKey = GlobalKey<FormState>();
  final _emailController = TextEditingController();
  final _sifreController = TextEditingController();
  final _adSoyadController = TextEditingController();
  bool _yukleniyor = false;
  bool _kayitModu = false;
  bool _sifreGizli = true;

  @override
  void dispose() {
    _emailController.dispose();
    _sifreController.dispose();
    _adSoyadController.dispose();
    super.dispose();
  }

  static String _otomatikKullaniciAdi(String tamIsim) {
    final temiz = tamIsim.toLowerCase()
        .replaceAll('ş', 's').replaceAll('ç', 'c')
        .replaceAll('ğ', 'g').replaceAll('ü', 'u')
        .replaceAll('ö', 'o').replaceAll('ı', 'i')
        .replaceAll(' ', '.');
    final temizlenmis = temiz.replaceAll(RegExp(r'[^a-z0-9.]'), '');
    final rast = (100000 + DateTime.now().millisecondsSinceEpoch % 900000).toString();
    final base = temizlenmis.length > 8 ? temizlenmis.substring(0, 8) : temizlenmis;
    return '$base$rast';
  }

  Future<void> _yonlendir() async {
    if (!mounted) return;
    final nav = Navigator.of(context);

    await SozlesmeService.instance.kullaniciDokumaniniHazirla();

    await Future.delayed(const Duration(milliseconds: 500));

    final bekleyenVar = await SozlesmeService.instance
        .bekleyenZorunluOnayVarMi();

    if (bekleyenVar) {
      nav.pushReplacement(
        MaterialPageRoute(
          builder: (_) => IlkOnayScreen(
            onTamamlandi: () => nav.pushReplacement(
              MaterialPageRoute(builder: (_) => const AnaSayfa()),
            ),
          ),
        ),
      );
    } else {
      nav.pushReplacement(
        MaterialPageRoute(builder: (_) => const AnaSayfa()),
      );
    }
  }

  Future<void> _girisYap() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() => _yukleniyor = true);

    try {
      await FirebaseAuth.instance.signInWithEmailAndPassword(
        email: _emailController.text.trim(),
        password: _sifreController.text.trim(),
      );
      await SozlesmeService.instance.kullaniciDokumaniniHazirla();
      await _yonlendir();
    } on FirebaseAuthException catch (e) {
      String mesaj = 'Bir hata oluştu';
      if (e.code == 'user-not-found') mesaj = 'Kullanıcı bulunamadı';
      if (e.code == 'wrong-password') mesaj = 'Şifre yanlış';
      if (e.code == 'invalid-email') mesaj = 'Geçersiz e-posta';
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(mesaj)),
        );
      }
    } finally {
      setState(() => _yukleniyor = false);
    }
  }

  Future<void> _kayitOl() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() => _yukleniyor = true);
    try {
      final sonuc = await FirebaseAuth.instance.createUserWithEmailAndPassword(
        email: _emailController.text.trim(),
        password: _sifreController.text.trim(),
      );
      final user = sonuc.user;
      if (user == null) return;
      final adSoyad = _adSoyadController.text.trim();
      await user.updateDisplayName(adSoyad);
      final username = _otomatikKullaniciAdi(adSoyad);
      await FirebaseFirestore.instance.collection('users').doc(user.uid).set({
        'displayName': adSoyad,
        'email': user.email ?? '',
        'username': username,
        'createdAt': FieldValue.serverTimestamp(),
        'lastLogin': FieldValue.serverTimestamp(),
      }, SetOptions(merge: true));
      if (mounted) {
        Navigator.pushReplacement(context,
            MaterialPageRoute(builder: (_) => OtpScreen(
              googleGiris: false,
              atanenKullaniciAdi: username,
            )));
      }
    } on FirebaseAuthException catch (e) {
      String mesaj = 'Bir hata oluştu';
      if (e.code == 'email-already-in-use') mesaj = 'Bu e-posta zaten kayıtlı';
      if (e.code == 'weak-password') mesaj = 'Şifre çok zayıf';
      if (e.code == 'invalid-email') mesaj = 'Geçersiz e-posta';
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(mesaj)));
    } finally {
      if (mounted) setState(() => _yukleniyor = false);
    }
  }

  Future<void> _googleIleGiris() async {
    setState(() => _yukleniyor = true);
    try {
      final GoogleSignIn googleSignIn = GoogleSignIn();
      await googleSignIn.signOut();
      final GoogleSignInAccount? googleUser = await googleSignIn.signIn();
      if (googleUser == null) { setState(() => _yukleniyor = false); return; }
      final GoogleSignInAuthentication googleAuth = await googleUser.authentication;
      final credential = GoogleAuthProvider.credential(
        accessToken: googleAuth.accessToken,
        idToken: googleAuth.idToken,
      );
      final sonuc = await FirebaseAuth.instance.signInWithCredential(credential);
      final user = sonuc.user;
      if (user == null) return;
      final displayName = user.displayName ?? '';
      final username = _otomatikKullaniciAdi(displayName);
      final doc = await FirebaseFirestore.instance.collection('users').doc(user.uid).get();
      final mevcutUsername = doc.data()?['username'];
      await FirebaseFirestore.instance.collection('users').doc(user.uid).set({
        'displayName': displayName,
        'email': user.email ?? '',
        'photoURL': user.photoURL ?? '',
        'username': mevcutUsername ?? username,
        'createdAt': FieldValue.serverTimestamp(),
        'lastLogin': FieldValue.serverTimestamp(),
      }, SetOptions(merge: true));
      await SozlesmeService.instance.kullaniciDokumaniniHazirla();
      await _yonlendir();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Google ile giriş başarısız: $e')));
      }
    } finally {
      if (mounted) setState(() => _yukleniyor = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Scaffold(
      backgroundColor: cs.surface,
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Form(
            key: _formKey,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const SizedBox(height: 40),

                Center(
                  child: Column(
                    children: [
                      Image.asset('assets/logo.png', height: 80),
                      const SizedBox(height: 16),
                      Text(
                        'PayNotu',
                        style: TextStyle(
                          color: cs.primary,
                          fontSize: 32,
                          fontWeight: FontWeight.bold,
                          letterSpacing: 0.5,
                        ),
                      ),
                      const SizedBox(height: 8),
                      Text(
                        _kayitModu ? 'Hesap Oluştur' : 'Hoş Geldiniz',
                        style: TextStyle(
                          color: cs.onSurfaceVariant,
                          fontSize: 16,
                        ),
                      ),
                    ],
                  ),
                ),

                const SizedBox(height: 48),

                if (_kayitModu) ...[
                  TextFormField(
                    controller: _adSoyadController,
                    decoration: InputDecoration(
                      labelText: 'Ad Soyad',
                      prefixIcon: const Icon(Icons.person),
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(12),
                      ),
                      focusedBorder: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(12),
                        borderSide: BorderSide(color: cs.primary, width: 2),
                      ),
                    ),
                    validator: (v) => v!.isEmpty ? 'Ad Soyad gerekli' : null,
                  ),
                  const SizedBox(height: 16),
                ],

                TextFormField(
                  controller: _emailController,
                  keyboardType: TextInputType.emailAddress,
                  decoration: InputDecoration(
                    labelText: 'E-posta',
                    prefixIcon: const Icon(Icons.email),
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(12),
                    ),
                    focusedBorder: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(12),
                      borderSide: BorderSide(color: cs.primary, width: 2),
                    ),
                  ),
                  validator: (v) => v!.isEmpty ? 'E-posta gerekli' : null,
                ),
                const SizedBox(height: 16),

                TextFormField(
                  controller: _sifreController,
                  obscureText: _sifreGizli,
                  decoration: InputDecoration(
                    labelText: 'Şifre',
                    prefixIcon: const Icon(Icons.lock),
                    suffixIcon: IconButton(
                      icon: Icon(_sifreGizli
                          ? Icons.visibility_off
                          : Icons.visibility),
                      onPressed: () =>
                          setState(() => _sifreGizli = !_sifreGizli),
                    ),
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(12),
                    ),
                    focusedBorder: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(12),
                      borderSide: BorderSide(color: cs.primary, width: 2),
                    ),
                  ),
                  validator: (v) =>
                      v!.length < 6 ? 'Şifre en az 6 karakter olmalı' : null,
                ),

                const SizedBox(height: 32),

                SizedBox(
                  width: double.infinity,
                  child: ElevatedButton(
                    onPressed: _yukleniyor
                        ? null
                        : (_kayitModu ? _kayitOl : _girisYap),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: cs.primary,
                      padding: const EdgeInsets.symmetric(vertical: 16),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(12),
                      ),
                    ),
                    child: _yukleniyor
                        ? SizedBox(
                            height: 20,
                            width: 20,
                            child: CircularProgressIndicator(
                              color: cs.onPrimary,
                              strokeWidth: 2,
                            ),
                          )
                        : Text(
                            _kayitModu ? 'KAYIT OL' : 'GİRİŞ YAP',
                            style: TextStyle(
                              color: cs.onPrimary,
                              fontSize: 16,
                              fontWeight: FontWeight.bold,
                            ),
                          ),
                  ),
                ),

                const SizedBox(height: 16),

                Row(
                  children: [
                    Expanded(child: Divider(color: cs.outlineVariant)),
                    Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 12),
                      child: Text('veya',
                          style: TextStyle(color: cs.onSurfaceVariant)),
                    ),
                    Expanded(child: Divider(color: cs.outlineVariant)),
                  ],
                ),

                const SizedBox(height: 16),

                SizedBox(
                  width: double.infinity,
                  child: OutlinedButton.icon(
                    onPressed: _yukleniyor ? null : _googleIleGiris,
                    icon: Icon(
                      Icons.g_mobiledata,
                      color: cs.error,
                      size: 28,
                    ),
                    label: Text(
                      'Google ile Giriş Yap',
                      style: TextStyle(
                        color: cs.onSurface,
                        fontSize: 15,
                        fontWeight: FontWeight.w500,
                      ),
                    ),
                    style: OutlinedButton.styleFrom(
                      padding: const EdgeInsets.symmetric(vertical: 14),
                      side: BorderSide(color: cs.outlineVariant),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(12),
                      ),
                    ),
                  ),
                ),

                const SizedBox(height: 16),

                Center(
                  child: TextButton(
                    onPressed: () =>
                        setState(() => _kayitModu = !_kayitModu),
                    child: Text(
                      _kayitModu
                          ? 'Zaten hesabın var mı? Giriş Yap'
                          : 'Hesabın yok mu? Kayıt Ol',
                      style: TextStyle(color: cs.primary),
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
