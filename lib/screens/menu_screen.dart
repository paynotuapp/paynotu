import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';
import 'haberler_screen.dart';
import 'egitimler_screen.dart';
import 'temettu_takvimi_screen.dart';
import 'tavan_serisi_screen.dart';
import 'bagis_screen.dart';
import 'sss_menu_screen.dart';
import 'geri_bildirim_screen.dart';
import 'onur_listesi_screen.dart';

class MenuScreen extends StatelessWidget {
  const MenuScreen({super.key});

  static const _playstoreUrl =
      'https://play.google.com/store/apps/details?id=com.paynotu.app';

  Future<void> _ac(BuildContext context, String url) async {
    final uri = Uri.parse(url);
    if (url.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
        content: Text('Bağlantı yakında eklenecek.'),
        backgroundColor: Colors.grey,
        duration: Duration(seconds: 2),
      ));
      return;
    }
    if (await canLaunchUrl(uri)) {
      await launchUrl(uri, mode: LaunchMode.externalApplication);
    }
  }

  void _git(BuildContext context, Widget screen) {
    Navigator.push(context, MaterialPageRoute(builder: (_) => screen));
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
        title: const Text('Menü',
            style: TextStyle(
                color: Colors.white,
                fontSize: 18,
                fontWeight: FontWeight.bold)),
      ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 16, 16, 32),
        children: [
          // 1. Haberler
          _kart(
            context: context,
            emoji: '📰',
            baslik: 'Haberler',
            altyazi: 'KAP son bildirimler',
            renk: Colors.blue,
            onTap: () => _git(context, const HaberlerScreen()),
          ),
          const SizedBox(height: 10),

          // 2. Eğitimler
          _kart(
            context: context,
            emoji: '🎓',
            baslik: 'Eğitimler',
            altyazi: 'Yatırım ve borsa rehberleri',
            renk: Colors.indigo,
            onTap: () => _git(context, const EgitimlerScreen()),
          ),
          const SizedBox(height: 10),

          // 3. Temettü Takvimi
          _kart(
            context: context,
            emoji: '📅',
            baslik: 'Temettü Takvimi',
            altyazi: 'Yaklaşan temettü ödemeleri',
            renk: Colors.green,
            onTap: () => _git(context, const TemettuTakvimiScreen()),
          ),
          const SizedBox(height: 10),

          // 4. Tavan Serisi
          _kart(
            context: context,
            emoji: '📈',
            baslik: 'Tavan Serisi Hesaplayıcı',
            altyazi: 'Ardışık tavan günleri',
            renk: Colors.orange,
            onTap: () => _git(context, const TavanSerisiScreen()),
          ),
          const SizedBox(height: 10),

          // 5. Bağış Yap
          _kart(
            context: context,
            emoji: '🎁',
            baslik: 'Bağış Yap',
            altyazi: 'Uygulamayı destekle',
            renk: Theme.of(context).colorScheme.primary,
            onTap: () => _git(context, const BagisScreen()),
          ),
          const SizedBox(height: 10),

          // 6. SSS
          _kart(
            context: context,
            emoji: '❓',
            baslik: 'Sık Sorulan Sorular',
            altyazi: 'PayNotu hakkında merak edilenler',
            renk: Colors.purple,
            onTap: () => _git(context, const SssMenuScreen()),
          ),
          const SizedBox(height: 10),

          // 7. Uygulamayı Değerlendir
          _kart(
            context: context,
            emoji: '⭐',
            baslik: 'Uygulamayı Değerlendir',
            altyazi: 'Play Store\'da puan ver',
            renk: Colors.amber,
            onTap: () => _ac(context, _playstoreUrl),
          ),
          const SizedBox(height: 10),

          // 8. Sosyal Medya
          _sosyalMedyaKart(context),
          const SizedBox(height: 10),

          // 9. Geri Bildirim
          _kart(
            context: context,
            emoji: '📧',
            baslik: 'Geri Bildirim',
            altyazi: 'Öneri, hata ve şikayetleriniz',
            renk: Colors.teal,
            onTap: () => _git(context, const GeriBildirimScreen()),
          ),
          const SizedBox(height: 10),

          // 10. Onur Listesi
          _kart(
            context: context,
            emoji: '🏆',
            baslik: 'Onur Listesi',
            altyazi: 'Bağış yapan destekçilerimiz',
            renk: const Color(0xFFB8860B),
            onTap: () => _git(context, const OnurListesiScreen()),
          ),
        ],
      ),
    );
  }

  Widget _kart({
    required BuildContext context,
    required String emoji,
    required String baslik,
    required String altyazi,
    required Color renk,
    required VoidCallback onTap,
  }) {
    return Material(
      color: Theme.of(context).colorScheme.surface,
      borderRadius: BorderRadius.circular(14),
      child: InkWell(
        borderRadius: BorderRadius.circular(14),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
          child: Row(
            children: [
              Container(
                width: 42,
                height: 42,
                decoration: BoxDecoration(
                  color: renk.withValues(alpha: 0.1),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Center(
                  child: Text(emoji, style: const TextStyle(fontSize: 20)),
                ),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(baslik,
                        style: const TextStyle(
                            fontSize: 14, fontWeight: FontWeight.w600)),
                    const SizedBox(height: 2),
                    Text(altyazi,
                        style: TextStyle(
                            fontSize: 12, color: Theme.of(context).colorScheme.onSurfaceVariant)),
                  ],
                ),
              ),
              Icon(Icons.arrow_forward_ios,
                  size: 14, color: Colors.grey.shade400),
            ],
          ),
        ),
      ),
    );
  }

  Widget _sosyalMedyaKart(BuildContext context) {
    return Material(
      color: Theme.of(context).colorScheme.surface,
      borderRadius: BorderRadius.circular(14),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  width: 42,
                  height: 42,
                  decoration: BoxDecoration(
                    color: Colors.pink.withValues(alpha: 0.1),
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: const Center(
                    child: Text('📱', style: TextStyle(fontSize: 20)),
                  ),
                ),
                const SizedBox(width: 14),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text('Sosyal Medya',
                          style: TextStyle(
                              fontSize: 14, fontWeight: FontWeight.w600)),
                      const SizedBox(height: 2),
                      Text('Bizi takip edin',
                          style: TextStyle(fontSize: 12, color: Theme.of(context).colorScheme.onSurfaceVariant)),
                    ],
                  ),
                ),
              ],
            ),
            const SizedBox(height: 14),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceEvenly,
              children: [
                _sosyalIkon(
                  context: context,
                  icon: Icons.camera_alt_outlined,
                  etiket: 'Instagram',
                  renk: const Color(0xFFE1306C),
                  url: '',
                ),
                _sosyalIkon(
                  context: context,
                  icon: Icons.alternate_email,
                  etiket: 'X (Twitter)',
                  renk: Colors.black87,
                  url: '',
                ),
                _sosyalIkon(
                  context: context,
                  icon: Icons.play_circle_outline,
                  etiket: 'YouTube',
                  renk: Colors.red,
                  url: '',
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _sosyalIkon({
    required BuildContext context,
    required IconData icon,
    required String etiket,
    required Color renk,
    required String url,
  }) {
    return InkWell(
      borderRadius: BorderRadius.circular(10),
      onTap: () => _ac(context, url),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
        child: Column(
          children: [
            Container(
              width: 44,
              height: 44,
              decoration: BoxDecoration(
                color: renk.withValues(alpha: 0.1),
                borderRadius: BorderRadius.circular(10),
              ),
              child: Icon(icon, color: renk, size: 22),
            ),
            const SizedBox(height: 4),
            Text(etiket,
                style: TextStyle(fontSize: 10, color: Colors.grey.shade600)),
          ],
        ),
      ),
    );
  }
}