import 'package:flutter/material.dart';
import 'package:firebase_core/firebase_core.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:provider/provider.dart';
import 'package:video_player/video_player.dart';
import 'models/firebase_options.dart';
import 'theme/app_theme.dart';
import 'providers/theme_provider.dart';
import 'providers/user_provider.dart';
import 'screens/paynotu_puan_screen.dart';
import 'screens/giris_screen.dart';
import 'screens/populer_screen.dart';
import 'screens/kritik_screen.dart';
import 'screens/takip_screen.dart';
import 'screens/ayarlar_screen.dart';
import 'screens/menu_screen.dart';
import 'services/hisse_cache_service.dart';
import 'services/sozlesme_service.dart';
import 'widgets/sozlesme_widgets.dart';

late VideoPlayerController globalSplashController;

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await initializeDateFormatting('tr_TR', null);
  await Firebase.initializeApp(
    options: DefaultFirebaseOptions.currentPlatform,
  );

  globalSplashController = VideoPlayerController.asset('assets/splash.mp4');
  await globalSplashController.initialize();
  globalSplashController.setLooping(false);

  runApp(
    MultiProvider(
      providers: [
        ChangeNotifierProvider(create: (_) => ThemeProvider()),
        ChangeNotifierProvider(create: (_) => UserProvider()),
      ],
      child: const PayDefteri(),
    ),
  );
}

class PayDefteri extends StatelessWidget {
  const PayDefteri({super.key});

  @override
  Widget build(BuildContext context) {
    final themeProvider = context.watch<ThemeProvider>();
    return MaterialApp(
      title: 'PayNotu',
      debugShowCheckedModeBanner: false,
      themeMode: themeProvider.themeMode,
      theme: AppTheme.light,
      darkTheme: AppTheme.dark,
      home: const SplashScreen(),
    );
  }
}

class SplashScreen extends StatefulWidget {
  const SplashScreen({super.key});

  @override
  State<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends State<SplashScreen> {
  bool _videoBitti = false;
  Widget? _sonrakiSayfa;

  @override
  void initState() {
    super.initState();
    
    globalSplashController.play();

    globalSplashController.addListener(() {
      if (globalSplashController.value.position == globalSplashController.value.duration) {
        if (mounted && !_videoBitti) {
          setState(() => _videoBitti = true);
          _sayfayaYonlendir();
        }
      }
    });

    _arkaPlanGecisKontrolu();
  }

  Future<void> _arkaPlanGecisKontrolu() async {
    final user = FirebaseAuth.instance.currentUser;

    if (user == null) {
      _sonrakiSayfa = const GirisScreen();
      _sayfayaYonlendir();
      return;
    }

    await SozlesmeService.instance.kullaniciDokumaniniHazirla();
    final bekleyenVar = await SozlesmeService.instance.bekleyenZorunluOnayVarMi();

    if (bekleyenVar) {
      _sonrakiSayfa = IlkOnayScreen(
        onTamamlandi: () {
          if (mounted) {
            Navigator.of(context).pushReplacement(
              MaterialPageRoute(builder: (_) => const AnaSayfa()),
            );
          }
        },
      );
    } else {
      _sonrakiSayfa = const AnaSayfa();
    }
    
    _sayfayaYonlendir();
  }

  void _sayfayaYonlendir() {
    if (_videoBitti && _sonrakiSayfa != null && mounted) {
      Navigator.pushReplacement(
        context,
        MaterialPageRoute(builder: (_) => _sonrakiSayfa!),
      );
    }
  }

  @override
  void dispose() {
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final renkSemasi = Theme.of(context).colorScheme;

    return Scaffold(
      backgroundColor: Colors.white, // Ekranın griliğini önlemek için beyaza eşitledik
      body: Center(
        child: globalSplashController.value.isInitialized
            ? FittedBox(
                fit: BoxFit.contain,
                child: SizedBox(
                  width: globalSplashController.value.size.width,
                  height: globalSplashController.value.size.height,
                  child: VideoPlayer(globalSplashController),
                ),
              )
            : CircularProgressIndicator(
                color: renkSemasi.primary,
              ), 
      ),
    );
  }
}

class AnaSayfa extends StatefulWidget {
  const AnaSayfa({super.key});

  @override
  State<AnaSayfa> createState() => _AnaSayfaState();
}

class _AnaSayfaState extends State<AnaSayfa> {
  int _secilenIndex = 2;
  bool _miniMenuAcik = false;

  bool _aramaAcik = false;
  final _aramaController = TextEditingController();
  String _aramaMetni = '';
  List<String> _sonAramalar = [];
  List<String> _sikArananlar = [];

  static const String _sonAramalarKey = 'son_aramalar';
  static const String _aramalarKoleksiyonu = 'aramalar';
  static const String _logoYolu = 'assets/logo.png';

  late final List<Widget> _sabitSayfalar = [
    const PopulerScreen(),
    const KritikScreen(),
    const SizedBox(),
    const TakipScreen(),
    const SizedBox(),
  ];

  @override
  void initState() {
    super.initState();
    HisseCacheService.instance.ilkYukle();
  }

  @override
  void dispose() {
    _aramaController.dispose();
    super.dispose();
  }

  void _aramaToggle() {
    if (_aramaAcik) {
      _aramaKapat();
    } else {
      _aramaAc();
    }
  }

  void _aramaAc() {
    setState(() {
      _secilenIndex = 2;
      _aramaAcik = true;
      _aramaMetni = '';
      _miniMenuAcik = false;
    });
    _aramaController.clear();
    _yukleSonAramalar();
    _yukleSikArananlar();
  }

  void _aramaKapat() {
    if (_aramaMetni.isNotEmpty) _secimiKaydet(_aramaMetni);
    setState(() {
      _aramaAcik = false;
      _aramaMetni = '';
    });
    _aramaController.clear();
  }

  Future<void> _yukleSonAramalar() async {
    final prefs = await SharedPreferences.getInstance();
    final liste = prefs.getStringList(_sonAramalarKey) ?? [];
    if (mounted) setState(() => _sonAramalar = liste);
  }

  Future<void> _yukleSikArananlar() async {
    try {
      final snap = await FirebaseFirestore.instance
          .collection(_aramalarKoleksiyonu)
          .orderBy('sayac', descending: true)
          .limit(5)
          .get();
      if (!mounted) return;
      setState(() {
        _sikArananlar = snap.docs
            .map((d) => (d.data()['terim'] ?? d.id).toString())
            .where((s) => s.isNotEmpty)
            .toList();
      });
    } catch (_) {}
  }

  Future<void> _secimiKaydet(String terim) async {
    if (terim.isEmpty) return;
    final prefs = await SharedPreferences.getInstance();
    final liste = prefs.getStringList(_sonAramalarKey) ?? [];
    liste.remove(terim);
    liste.insert(0, terim);
    if (liste.length > 5) liste.removeLast();
    await prefs.setStringList(_sonAramalarKey, liste);
    if (mounted) setState(() => _sonAramalar = liste);

    if (FirebaseAuth.instance.currentUser != null) {
      try {
        await FirebaseFirestore.instance
            .collection(_aramalarKoleksiyonu)
            .doc(terim.toLowerCase())
            .set(
          {'terim': terim, 'sayac': FieldValue.increment(1)},
          SetOptions(merge: true),
        );
      } catch (_) {}
    }
  }

  void _chipSec(String terim) {
    _secimiKaydet(terim);
    _aramaController.text = terim;
    setState(() => _aramaMetni = terim);
  }

  void _bagisDialog() {
    showDialog(
      context: context,
      builder: (_) => AlertDialog(
        title: const Row(
          children: [
            Icon(Icons.volunteer_activism, color: Color(0xFF00C853)),
            Spacer(),
            Text('Bağış Yap'),
          ],
        ),
        content: const Text(
          'PayNotu\'yu beğendiyseniz geliştirmeye devam etmemiz için bağış yapabilirsiniz. Desteğiniz için teşekkürler! 💚',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Kapat'),
          ),
          ElevatedButton(
            onPressed: () => Navigator.pop(context),
            style: ElevatedButton.styleFrom(
              backgroundColor: const Color(0xFF00C853),
            ),
            child: const Text('Bağış Yap',
                style: TextStyle(color: Colors.white)),
          ),
        ],
      ),
    );
  }

  void _menuAc() {
    Navigator.push(
      context,
      MaterialPageRoute(builder: (_) => const MenuScreen()),
    );
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(
        backgroundColor: cs.primary,
        elevation: 0,
        centerTitle: false,
        title: _aramaAcik
            ? TextField(
                controller: _aramaController,
                autofocus: true,
                onChanged: (v) => setState(() => _aramaMetni = v.trim()),
                style: const TextStyle(color: Colors.white, fontSize: 16),
                cursorColor: Colors.white,
                textCapitalization: TextCapitalization.characters,
                decoration: InputDecoration(
                  hintText: 'Hisse, şirket, sektör, endeks...',
                  hintStyle: TextStyle(
                      color: Colors.white.withValues(alpha: 0.65),
                      fontSize: 15),
                  border: InputBorder.none,
                ),
              )
            : const Text(
                'PayNotu',
                style: TextStyle(
                  color: Colors.white,
                  fontSize: 20,
                  fontWeight: FontWeight.w700,
                  letterSpacing: 0.4,
                ),
              ),
        actions: [
          IconButton(
            icon: Icon(
              _aramaAcik ? Icons.close : Icons.search,
              color: Colors.white,
            ),
            onPressed: _aramaToggle,
          ),
          if (!_aramaAcik) ...[
            IconButton(
              icon: const Icon(Icons.volunteer_activism, color: Colors.white),
              onPressed: _bagisDialog,
            ),
            IconButton(
              icon: const Icon(Icons.settings, color: Colors.white),
              onPressed: () => Navigator.push(
                context,
                MaterialPageRoute(builder: (_) => const AyarlarScreen()),
              ),
            ),
          ],
        ],
      ),
      body: GestureDetector(
        onTap: () {
          if (_miniMenuAcik) setState(() => _miniMenuAcik = false);
        },
        child: Column(
          children: [
            if (_aramaAcik &&
                _aramaMetni.isEmpty &&
                (_sonAramalar.isNotEmpty || _sikArananlar.isNotEmpty))
              _chipDropdown(),
            Expanded(
              child: _secilenIndex == 2
                  ? PayNotuPuanScreen(
                      aramaMetni: _aramaAcik ? _aramaMetni : '',
                    )
                  : _sabitSayfalar[_secilenIndex],
            ),
          ],
        ),
      ),
      bottomNavigationBar: Container(
        height: 75,
        decoration: BoxDecoration(
          color: cs.primary,
          boxShadow: const [
            BoxShadow(
              color: Colors.black12,
              blurRadius: 8,
              offset: Offset(0, -2),
            ),
          ],
        ),
        child: Stack(
          clipBehavior: Clip.none,
          children: [
            Row(
              children: [
                Expanded(child: _altBarIkon(ikon: Icons.trending_up, etiket: 'Popüler', index: 0)),
                Expanded(child: _altBarIkon(ikon: Icons.trending_down, etiket: 'Kritik', index: 1)),
                const Expanded(child: SizedBox()),
                Expanded(child: _altBarIkon(ikon: Icons.remove_red_eye, etiket: 'Takip', index: 3)),
                Expanded(child: _altBarIkonOnTap(ikon: Icons.menu, etiket: 'Menü', onTap: _menuAc, secili: _secilenIndex == 4)),
              ],
            ),
            Positioned(
              top: -28,
              left: 0,
              right: 0,
              child: Center(
                child: GestureDetector(
                  onTap: () {
                    setState(() {
                      _secilenIndex = 2;
                      _miniMenuAcik = false;
                      if (_aramaAcik) _aramaKapat();
                    });
                  },
                  child: Container(
                    width: 70,
                    height: 70,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      boxShadow: [
                        BoxShadow(
                          color: _secilenIndex == 2
                              ? cs.primary.withValues(alpha: 0.5)
                              : Colors.black26,
                          blurRadius: 12,
                          offset: const Offset(0, 4),
                        ),
                      ],
                    ),
                    child: ClipOval(
                      child: Image.asset(_logoYolu, fit: BoxFit.cover),
                    ),
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _chipDropdown() {
    return Container(
      width: double.infinity,
      color: Theme.of(context).colorScheme.surface,
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (_sonAramalar.isNotEmpty) ...[
            _chipBaslik('SON ARAMALAR', Icons.history),
            const SizedBox(height: 6),
            _chipSatiri(_sonAramalar, Colors.grey.shade700),
          ],
          if (_sonAramalar.isNotEmpty && _sikArananlar.isNotEmpty)
            const SizedBox(height: 10),
          if (_sikArananlar.isNotEmpty) ...[
            _chipBaslik('SIK ARANANLAR', Icons.trending_up),
            const SizedBox(height: 6),
            _chipSatiri(_sikArananlar, Theme.of(context).colorScheme.primary),
          ],
        ],
      ),
    );
  }

  Widget _chipBaslik(String baslik, IconData ikon) {
    return Row(
      children: [
        Icon(ikon, size: 13, color: Colors.grey.shade500),
        const SizedBox(width: 5),
        Text(baslik,
            style: TextStyle(
                fontSize: 10,
                fontWeight: FontWeight.w700,
                color: Colors.grey.shade500,
                letterSpacing: 0.5)),
      ],
    );
  }

  Widget _chipSatiri(List<String> terimler, Color renk) {
    return Wrap(
      spacing: 7,
      runSpacing: 4,
      children: terimler.map((t) {
        return ActionChip(
          label: Text(t, style: TextStyle(color: renk, fontSize: 12)),
          backgroundColor: renk.withValues(alpha: 0.08),
          side: BorderSide(color: renk.withValues(alpha: 0.18)),
          padding: const EdgeInsets.symmetric(horizontal: 2),
          visualDensity: VisualDensity.compact,
          onPressed: () => _chipSec(t),
        );
      }).toList(),
    );
  }

  Widget _altBarIkon({required IconData ikon, required String etiket, required int index}) {
    final secili = _secilenIndex == index;
    return GestureDetector(
      onTap: () {
        setState(() {
          _secilenIndex = index;
          _miniMenuAcik = false;
          if (_aramaAcik) _aramaKapat();
        });
      },
      child: Container(
        color: Colors.transparent,
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(ikon, size: 26, color: secili ? Colors.white : Colors.white60),
            const SizedBox(height: 2),
            Text(etiket,
                style: TextStyle(
                    fontSize: 11,
                    fontWeight: secili ? FontWeight.bold : FontWeight.normal,
                    color: secili ? Colors.white : Colors.white60)),
          ],
        ),
      ),
    );
  }

  Widget _altBarIkonOnTap({required IconData ikon, required String etiket, required VoidCallback onTap, required bool secili}) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        color: Colors.transparent,
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(ikon, size: 26, color: secili ? Colors.white : Colors.white60),
            const SizedBox(height: 2),
            Text(etiket,
                style: TextStyle(
                    fontSize: 11,
                    fontWeight: secili ? FontWeight.bold : FontWeight.normal,
                    color: secili ? Colors.white : Colors.white60)),
          ],
        ),
      ),
    );
  }
}