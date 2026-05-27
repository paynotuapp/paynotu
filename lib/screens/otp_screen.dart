import 'package:flutter/material.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:google_sign_in/google_sign_in.dart';
import '../main.dart';
import 'giris_screen.dart';

class OtpScreen extends StatefulWidget {
  final bool googleGiris;
  final String? atanenKullaniciAdi;
  const OtpScreen({super.key, this.googleGiris = false, this.atanenKullaniciAdi});

  @override
  State<OtpScreen> createState() => _OtpScreenState();
}

class _OtpScreenState extends State<OtpScreen> {
  bool _gonderiliyor = false;
  bool _kodGonderildi = false;

  Future<void> _dogrulamaGonder() async {
    final user = FirebaseAuth.instance.currentUser;
    if (user == null) return;
    final email = user.email ?? '';
    if (email.isEmpty) { _snack('E-posta adresi bulunamadı', hata: true); return; }
    if (user.emailVerified) { await _yonlendir(); return; }
    setState(() => _gonderiliyor = true);
    try {
      await user.sendEmailVerification();
      setState(() => _kodGonderildi = true);
      _snack('Doğrulama bağlantısı $email adresine gönderildi');
    } catch (e) {
      _snack('Gönderilemedi: $e', hata: true);
    } finally {
      if (mounted) setState(() => _gonderiliyor = false);
    }
  }

  Future<void> _dogrulamaKontrol() async {
    setState(() => _gonderiliyor = true);
    try {
      await FirebaseAuth.instance.currentUser?.reload();
      final user = FirebaseAuth.instance.currentUser;
      if (user?.emailVerified == true) {
        await _yonlendir();
      } else {
        _snack('E-posta henüz doğrulanmadı. Lütfen gelen kutunuzu kontrol edin.', hata: true);
      }
    } catch (e) {
      _snack('Hata: $e', hata: true);
    } finally {
      if (mounted) setState(() => _gonderiliyor = false);
    }
  }

  Future<void> _yonlendir() async {
    if (!mounted) return;
    Navigator.pushReplacement(
      context,
      MaterialPageRoute(builder: (_) => const AnaSayfa()),
    );
  }

  void _snack(String mesaj, {bool hata = false}) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Text(mesaj),
      backgroundColor: hata
          ? Theme.of(context).colorScheme.error
          : Theme.of(context).colorScheme.primary,
      duration: const Duration(seconds: 3),
    ));
  }

  @override
  Widget build(BuildContext context) {
    final cs   = Theme.of(context).colorScheme;
    final user = FirebaseAuth.instance.currentUser;
    final email = user?.email ?? '';

    return Scaffold(
      backgroundColor: cs.surface,
      appBar: AppBar(
        backgroundColor: cs.primary,
        title: Text('E-posta Doğrulama',
            style: TextStyle(color: cs.onPrimary, fontWeight: FontWeight.bold)),
        leading: IconButton(
          icon: Icon(Icons.arrow_back, color: cs.onPrimary),
          onPressed: () async {
            final nav = Navigator.of(context);
            await GoogleSignIn().signOut();
            await FirebaseAuth.instance.signOut();
            nav.pushAndRemoveUntil(
              MaterialPageRoute(builder: (_) => const GirisScreen()),
              (_) => false,
            );
          },
        ),
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const SizedBox(height: 16),
          Center(
            child: Icon(Icons.mark_email_unread_outlined, size: 72, color: cs.primary),
          ),
          const SizedBox(height: 24),
          Center(
            child: Text('E-postanızı Doğrulayın',
                style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold, color: cs.onSurface)),
          ),
          const SizedBox(height: 8),
          Center(
            child: Text(email,
                style: TextStyle(fontSize: 14, color: cs.primary, fontWeight: FontWeight.w500)),
          ),
          const SizedBox(height: 32),

          if (!_kodGonderildi) ...[
            if (widget.atanenKullaniciAdi != null) ...[
              Container(
                padding: const EdgeInsets.all(14),
                decoration: BoxDecoration(
                  color: cs.primaryContainer,
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Row(children: [
                  Icon(Icons.badge_outlined, color: cs.primary, size: 20),
                  const SizedBox(width: 10),
                  Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text('Kullanıcı Adınız',
                        style: TextStyle(fontSize: 11, color: cs.onPrimaryContainer,
                            fontWeight: FontWeight.w600)),
                    const SizedBox(height: 2),
                    Text(widget.atanenKullaniciAdi!,
                        style: TextStyle(fontSize: 15, fontWeight: FontWeight.bold,
                            color: cs.primary)),
                    const SizedBox(height: 2),
                    Text('Profil sayfanızdan değiştirebilirsiniz.',
                        style: TextStyle(fontSize: 11, color: cs.onPrimaryContainer)),
                  ])),
                ]),
              ),
              const SizedBox(height: 16),
            ],
            Text(
              'Hesabınızı aktifleştirmek için e-posta adresinize bir doğrulama bağlantısı göndereceğiz.',
              style: TextStyle(fontSize: 14, color: cs.onSurfaceVariant, height: 1.5),
            ),
            const SizedBox(height: 24),
            SizedBox(
              width: double.infinity,
              child: ElevatedButton(
                onPressed: _gonderiliyor ? null : _dogrulamaGonder,
                style: ElevatedButton.styleFrom(
                  backgroundColor: cs.primary,
                  padding: const EdgeInsets.symmetric(vertical: 16),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                ),
                child: _gonderiliyor
                    ? SizedBox(width: 20, height: 20,
                        child: CircularProgressIndicator(color: cs.onPrimary, strokeWidth: 2))
                    : Text('Doğrulama Gönder',
                        style: TextStyle(color: cs.onPrimary, fontSize: 16, fontWeight: FontWeight.bold)),
              ),
            ),
          ] else ...[
            Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: cs.primaryContainer,
                borderRadius: BorderRadius.circular(12),
              ),
              child: Row(children: [
                Icon(Icons.check_circle_outline, color: cs.primary),
                const SizedBox(width: 12),
                Expanded(
                  child: Text(
                    'Doğrulama bağlantısı gönderildi. E-postanızdaki bağlantıya tıkladıktan sonra aşağıdaki butona basın.',
                    style: TextStyle(fontSize: 13, color: cs.onPrimaryContainer, height: 1.4),
                  ),
                ),
              ]),
            ),
            const SizedBox(height: 24),
            SizedBox(
              width: double.infinity,
              child: ElevatedButton(
                onPressed: _gonderiliyor ? null : _dogrulamaKontrol,
                style: ElevatedButton.styleFrom(
                  backgroundColor: cs.primary,
                  padding: const EdgeInsets.symmetric(vertical: 16),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                ),
                child: _gonderiliyor
                    ? SizedBox(width: 20, height: 20,
                        child: CircularProgressIndicator(color: cs.onPrimary, strokeWidth: 2))
                    : Text('Doğrulamayı Tamamladım',
                        style: TextStyle(color: cs.onPrimary, fontSize: 16, fontWeight: FontWeight.bold)),
              ),
            ),
            const SizedBox(height: 16),
            Center(
              child: TextButton(
                onPressed: _gonderiliyor ? null : _dogrulamaGonder,
                child: Text('Tekrar Gönder',
                    style: TextStyle(color: cs.primary, fontSize: 14)),
              ),
            ),
          ],
        ]),
      ),
    );
  }
}
