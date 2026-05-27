import 'package:flutter/material.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:cloud_firestore/cloud_firestore.dart';

class GeriBildirimScreen extends StatefulWidget {
  const GeriBildirimScreen({super.key});

  @override
  State<GeriBildirimScreen> createState() => _GeriBildirimScreenState();
}

class _GeriBildirimScreenState extends State<GeriBildirimScreen> {
  static const _tipler = ['💡 Öneri', '🐛 Hata Bildirimi', '📢 Şikayet', '💬 Diğer'];

  String _seciliTip = '💡 Öneri';
  final _konuController = TextEditingController();
  final _mesajController = TextEditingController();
  bool _gonderiliyor = false;

  @override
  void dispose() {
    _konuController.dispose();
    _mesajController.dispose();
    super.dispose();
  }

  Future<void> _gonder() async {
    final konu = _konuController.text.trim();
    final mesaj = _mesajController.text.trim();

    if (konu.isEmpty) {
      _snack('Lütfen konu girin.', hata: true);
      return;
    }
    if (mesaj.isEmpty) {
      _snack('Lütfen mesajınızı girin.', hata: true);
      return;
    }

    setState(() => _gonderiliyor = true);

    try {
      final uid = FirebaseAuth.instance.currentUser?.uid ?? 'anonim';
      await FirebaseFirestore.instance.collection('geri_bildirimler').add({
        'tip': _seciliTip,
        'konu': konu,
        'mesaj': mesaj,
        'kullanici_uid': uid,
        'tarih': FieldValue.serverTimestamp(),
        'okundu': false,
      });

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: const Text('Teşekkürler, mesajınız iletildi 🙌'),
          backgroundColor: Theme.of(context).colorScheme.primary,
          duration: const Duration(seconds: 3),
        ));
        Navigator.pop(context);
      }
    } catch (e) {
      _snack('Gönderilirken hata oluştu: $e', hata: true);
      setState(() => _gonderiliyor = false);
    }
  }

  void _snack(String mesaj, {bool hata = false}) {
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Text(mesaj),
      backgroundColor: hata ? Colors.red : Theme.of(context).colorScheme.primary,
      duration: const Duration(seconds: 2),
    ));
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Theme.of(context).scaffoldBackgroundColor,
      appBar: AppBar(
        backgroundColor: Theme.of(context).colorScheme.primary,
        elevation: 0,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back, color: Colors.white),
          onPressed: () => Navigator.pop(context),
        ),
        title: const Text('📧 Geri Bildirim',
            style: TextStyle(
                color: Colors.white, fontWeight: FontWeight.bold)),
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Tip seçimi
            Text('Bildirim Türü',
                style: TextStyle(
                    fontWeight: FontWeight.bold,
                    fontSize: 13,
                    color: Theme.of(context).colorScheme.onSurface)),
            const SizedBox(height: 10),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: _tipler.map((tip) {
                final secili = tip == _seciliTip;
                return ChoiceChip(
                  label: Text(tip,
                      style: TextStyle(
                          fontSize: 13,
                          color: secili
                              ? Colors.white
                              : Theme.of(context).colorScheme.onSurface)),
                  selected: secili,
                  selectedColor: Theme.of(context).colorScheme.primary,
                  backgroundColor: Theme.of(context).colorScheme.surface,
                  side: BorderSide(
                      color: secili
                          ? Theme.of(context).colorScheme.primary
                          : Colors.grey.shade300),
                  onSelected: (_) =>
                      setState(() => _seciliTip = tip),
                );
              }).toList(),
            ),
            const SizedBox(height: 20),

            // Konu
            Text('Konu',
                style: TextStyle(
                    fontWeight: FontWeight.bold,
                    fontSize: 13,
                    color: Theme.of(context).colorScheme.onSurface)),
            const SizedBox(height: 8),
            TextField(
              controller: _konuController,
              textCapitalization: TextCapitalization.sentences,
              decoration: InputDecoration(
                hintText: 'Kısaca konuyu belirtin...',
                filled: true,
                fillColor: Theme.of(context).colorScheme.surface,
                border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(12),
                    borderSide: BorderSide(color: Colors.grey.shade300)),
                enabledBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(12),
                    borderSide: BorderSide(color: Colors.grey.shade300)),
                focusedBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(12),
                    borderSide: BorderSide(
                        color: Theme.of(context).colorScheme.primary, width: 1.5)),
              ),
            ),
            const SizedBox(height: 20),

            // Mesaj
            Text('Mesaj',
                style: TextStyle(
                    fontWeight: FontWeight.bold,
                    fontSize: 13,
                    color: Theme.of(context).colorScheme.onSurface)),
            const SizedBox(height: 8),
            TextField(
              controller: _mesajController,
              maxLines: 6,
              minLines: 4,
              textCapitalization: TextCapitalization.sentences,
              decoration: InputDecoration(
                hintText: 'Mesajınızı buraya yazın...',
                filled: true,
                fillColor: Theme.of(context).colorScheme.surface,
                border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(12),
                    borderSide: BorderSide(color: Colors.grey.shade300)),
                enabledBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(12),
                    borderSide: BorderSide(color: Colors.grey.shade300)),
                focusedBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(12),
                    borderSide: BorderSide(
                        color: Theme.of(context).colorScheme.primary, width: 1.5)),
                alignLabelWithHint: true,
              ),
            ),
            const SizedBox(height: 28),

            // Gönder
            SizedBox(
              width: double.infinity,
              height: 50,
              child: ElevatedButton(
                onPressed: _gonderiliyor ? null : _gonder,
                style: ElevatedButton.styleFrom(
                  backgroundColor: Theme.of(context).colorScheme.primary,
                  foregroundColor: Colors.white,
                  shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(12)),
                  disabledBackgroundColor:
                      Theme.of(context).colorScheme.primary.withValues(alpha: 0.5),
                ),
                child: _gonderiliyor
                    ? const SizedBox(
                        width: 22,
                        height: 22,
                        child: CircularProgressIndicator(
                            color: Colors.white, strokeWidth: 2.5))
                    : const Text('Gönder',
                        style: TextStyle(
                            fontSize: 15, fontWeight: FontWeight.bold)),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
