import 'package:flutter/material.dart';

class SssMenuScreen extends StatelessWidget {
  const SssMenuScreen({super.key});

  static const _sorular = [
    (
      'PayNotu skoru nasıl hesaplanıyor?',
      'PayNotu skoru; finansal analiz (%60), kullanıcı yorumları (%25) ve makroekonomik düzeltme (%15) kombinasyonuyla hesaplanır. Her kullanıcının yorumu ağırlıklı puan sistemine dahil edilir.'
    ),
    (
      'Güven skoru nedir?',
      'Güven skoru, kullanıcının platformdaki aktifliğine, yorumlarının kalitesine ve topluluk tarafından beğenilme oranına göre hesaplanan bir itibar puanıdır. 0-10 arasında değer alır.'
    ),
    (
      'Yorum nasıl yapılır?',
      'Hisse kartını sola kaydırarak "Sözün Kısası" butonuna tıklayın ya da hisse detay ekranından yorum yazabilirsiniz. Her kullanıcı hisse başına 1 yorum yapabilir; 24 saatte bir güncelleyebilir.'
    ),
    (
      'Veriler ne kadar güncel?',
      'Fiyat verileri Yahoo Finance üzerinden çekilir. PayNotu skorları yorum yapıldıkça güncellenir ve ayrıca günlük toplu güncelleme ile yenilenir. KAP haberleri anlık olarak KAP\'ın kendi API\'sinden alınır.'
    ),
  ];

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
        title: const Text('❓ Sık Sorulan Sorular',
            style: TextStyle(
                color: Colors.white, fontWeight: FontWeight.bold)),
      ),
      body: ListView.builder(
        padding: const EdgeInsets.all(16),
        itemCount: _sorular.length,
        itemBuilder: (ctx, i) {
          final (soru, cevap) = _sorular[i];
          return Container(
            margin: const EdgeInsets.only(bottom: 10),
            decoration: BoxDecoration(
                color: Theme.of(ctx).colorScheme.surface,
                borderRadius: BorderRadius.circular(12),
                boxShadow: [
                  BoxShadow(
                      color: Colors.black.withValues(alpha: 0.04),
                      blurRadius: 4)
                ]),
            child: ExpansionTile(
              tilePadding:
                  const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
              iconColor: Theme.of(ctx).colorScheme.primary,
              collapsedIconColor: Theme.of(ctx).colorScheme.onSurfaceVariant,
              title: Text(soru,
                  style: const TextStyle(
                      fontSize: 13, fontWeight: FontWeight.w600)),
              children: [
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
                  child: Text(cevap,
                      style: TextStyle(
                          fontSize: 13,
                          color: Theme.of(ctx).colorScheme.onSurface,
                          height: 1.5)),
                ),
              ],
            ),
          );
        },
      ),
    );
  }
}
