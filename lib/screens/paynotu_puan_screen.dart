import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter_slidable/flutter_slidable.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:pay/screens/detay_screen.dart';
import 'package:pay/screens/hisse_filtre_sheet.dart';
import 'package:pay/screens/soz_hakki_screen.dart';
import 'package:pay/utils/paynotu_color.dart';
import 'package:pay/theme/paynotu_colors.dart';
import 'package:pay/services/hisse_cache_service.dart';

// Sıralama yönü menüsünde gösterilecek seçenekler
const _kSiralaYonSecenekler = [
  SiralaYon.artan,
  SiralaYon.azalan,
];

// Alfabetik hızlı geçiş harfleri
const _kHarfler = [
  'A','B','C','D','E','F','G','H','I','J','K','L',
  'M','N','O','P','R','S','T','U','V','Y','Z',
];

// ListView.builder'a itemExtent olarak verilir → scroll hesabı kesin olur
const double _kItemYuksekligi = 92.0;

// Side panel boyutları
const double _kPanelGenisligi = 200.0;
const double _kTabGenisligi   = 20.0;

// ── PayNotuPuanScreen ─────────────────────────────────────────────────────────

class PayNotuPuanScreen extends StatefulWidget {
  final String aramaMetni;
  const PayNotuPuanScreen({super.key, this.aramaMetni = ''});

  @override
  State<PayNotuPuanScreen> createState() => _PayNotuPuanScreenState();
}

class _PayNotuPuanScreenState extends State<PayNotuPuanScreen>
    with SingleTickerProviderStateMixin {
  late TabController _tabCtrl;

  // Arama sonuçları (filtre cache'ten)
  List<Map<String, dynamic>> _aramaListesi = [];

  // Filtre & sıralama
  HisseFiltreDurum _filtre = const HisseFiltreDurum();

  // Side panel durumu
  bool _panelAcik       = false;
  bool _suzPuanAcik     = false;
  bool _harfGrubuAktif  = false;

  bool get _temizleAktif => _filtre.aktif || _harfGrubuAktif;

  // Her tab için GlobalKey — Grupla butonu aktif tab'a scroll yollar
  late final List<GlobalKey<_HisseListesiState>> _hisseListesiKeys;

  static const _tabLabels = [
    'BİST TÜM', 'BİST 30', 'BİST 100', 'ALT PAZAR', 'YİP',
  ];

  static const _tabFiltre = <List<String?>>[
    [null,     null],
    ['endeks', 'BIST 30'],
    ['endeks', 'BIST 100'],
    ['pazar',  'ALT PAZAR'],
    ['pazar',  'YAKIN İZLEME PAZARI'],
  ];

  @override
  void initState() {
    super.initState();
    _tabCtrl = TabController(length: _tabLabels.length, vsync: this);
    _hisseListesiKeys = List.generate(
        _tabLabels.length, (_) => GlobalKey<_HisseListesiState>());
    _yuklePrefs();
    if (widget.aramaMetni.isNotEmpty) _aramaGuncelle(widget.aramaMetni);
  }

  @override
  void didUpdateWidget(PayNotuPuanScreen old) {
    super.didUpdateWidget(old);
    if (widget.aramaMetni != old.aramaMetni) _aramaGuncelle(widget.aramaMetni);
  }

  @override
  void dispose() {
    _tabCtrl.dispose();
    super.dispose();
  }

  Future<void> _yuklePrefs() async {
    final p = await SharedPreferences.getInstance();
    if (mounted) setState(() => _filtre = HisseFiltreDurum.fromPrefs(p));
  }

  Future<void> _kaydetPrefs(HisseFiltreDurum yeni) async {
    final p = await SharedPreferences.getInstance();
    await yeni.kaydet(p);
  }

  // ── Arama ─────────────────────────────────────────────────────────────────

  Future<void> _aramaGuncelle(String q) async {
    if (q.isEmpty) {
      if (mounted) setState(() => _aramaListesi = []);
      return;
    }
    if (mounted) {
      setState(() => _aramaListesi =
          _aramaFiltrele(q, HisseCacheService.instance.hisseler));
    }
  }

  List<Map<String, dynamic>> _aramaFiltrele(
      String q, List<Map<String, dynamic>> kaynak) {
    if (q.isEmpty || kaynak.isEmpty) return [];
    final ql = q.toLowerCase();
    final list = kaynak.where((d) {
      final sym = (d['symbol']   ?? '').toString().toLowerCase();
      final nam = (d['name']     ?? '').toString().toLowerCase();
      final sec = (d['sector']   ?? '').toString().toLowerCase();
      final ind = (d['industry'] ?? '').toString().toLowerCase();
      final end = ((d['endeksler'] ?? []) as List)
          .map((e) => e.toString().toLowerCase())
          .toList();
      return sym.contains(ql) ||
          nam.contains(ql) ||
          sec.contains(ql) ||
          ind.contains(ql) ||
          end.any((e) => e.contains(ql));
    }).toList();
    list.sort((a, b) {
      int r(Map<String, dynamic> d) {
        final s = (d['symbol'] ?? '').toString().toLowerCase();
        if (s == ql) return 0;
        if (s.startsWith(ql)) return 1;
        return 2;
      }
      return r(a).compareTo(r(b));
    });
    return list;
  }

  // ── Grupla — harfleri üstten açılan panel ────────────────────────────────

  Future<void> _gruplaMenuAc() async {
    if (!mounted) return;
    await showGeneralDialog<void>(
      context: context,
      barrierDismissible: true,
      barrierLabel: 'Kapat',
      barrierColor: Colors.black38,
      transitionDuration: const Duration(milliseconds: 220),
      pageBuilder: (ctx, _, _) {
        return Align(
          alignment: Alignment.topCenter,
          child: SafeArea(
            bottom: false,
            child: Material(
              color: Theme.of(ctx).colorScheme.surface,
              borderRadius: const BorderRadius.vertical(
                  bottom: Radius.circular(16)),
              elevation: 8,
              child: Padding(
                padding: const EdgeInsets.fromLTRB(16, 20, 16, 24),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'Harf Grubuna Git',
                      style: TextStyle(
                          fontSize: 15, fontWeight: FontWeight.w600),
                    ),
                    const SizedBox(height: 14),
                    Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: _kHarfler.map((harf) {
                        return GestureDetector(
                          onTap: () {
                            Navigator.pop(ctx);
                            final gitti = _hisseListesiKeys[_tabCtrl.index]
                                    .currentState
                                    ?.harfeGit(harf) ??
                                false;
                            if (gitti && mounted) {
                              setState(() => _harfGrubuAktif = true);
                            }
                          },
                          child: Container(
                            width: 46,
                            height: 46,
                            decoration: BoxDecoration(
                              color: Theme.of(ctx).colorScheme.primary.withValues(alpha: 0.08),
                              borderRadius: BorderRadius.circular(10),
                              border: Border.all(
                                  color: Theme.of(ctx).colorScheme.primary.withValues(alpha: 0.25)),
                            ),
                            child: Center(
                              child: Text(
                                harf,
                                style: TextStyle(
                                  fontSize: 17,
                                  fontWeight: FontWeight.bold,
                                  color: Theme.of(ctx).colorScheme.primary,
                                ),
                              ),
                            ),
                          ),
                        );
                      }).toList(),
                    ),
                  ],
                ),
              ),
            ),
          ),
        );
      },
      transitionBuilder: (ctx, anim, _, child) {
        final slide = Tween<Offset>(
          begin: const Offset(0, -1),
          end: Offset.zero,
        ).animate(CurvedAnimation(parent: anim, curve: Curves.easeOut));
        return SlideTransition(position: slide, child: child);
      },
    );
  }

  // ── Side panel widget'ları ────────────────────────────────────────────────

  Widget _tabButonu() {
    final renk = _temizleAktif
        ? Theme.of(context).colorScheme.primary
        : Colors.grey.shade400;
    return GestureDetector(
      onTap: () => setState(() => _panelAcik = !_panelAcik),
      child: Container(
        width: _kTabGenisligi,
        decoration: BoxDecoration(
          color: Theme.of(context).colorScheme.surface,
          borderRadius:
              const BorderRadius.horizontal(left: Radius.circular(10)),
          boxShadow: [
            BoxShadow(
              color: Colors.black.withValues(alpha: 0.14),
              blurRadius: 6,
              offset: const Offset(-2, 0),
            ),
          ],
        ),
        child: Center(
          child: Icon(
            _panelAcik ? Icons.chevron_right : Icons.chevron_left,
            size: 18,
            color: renk,
          ),
        ),
      ),
    );
  }

  Widget _bolumBaslik(IconData ikon, String baslik) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 14, 12, 4),
      child: Row(
        children: [
          Icon(ikon, size: 13, color: Theme.of(context).colorScheme.primary),
          const SizedBox(width: 6),
          Text(
            baslik,
            style: const TextStyle(
              fontSize: 11,
              fontWeight: FontWeight.bold,
              color: Colors.black54,
              letterSpacing: 0.5,
            ),
          ),
        ],
      ),
    );
  }

  Widget _siralaYonSatiri(SiralaYon yon) {
    final secili = _filtre.siralaYon == yon;
    return InkWell(
      onTap: () {
        final yeni = _filtre.copyWith(siralaYon: yon);
        setState(() => _filtre = yeni);
        _kaydetPrefs(yeni);
      },
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        child: Row(
          children: [
            Icon(
              secili ? Icons.radio_button_checked : Icons.radio_button_unchecked,
              size: 14,
              color: secili
                  ? Theme.of(context).colorScheme.primary
                  : Colors.grey.shade400,
            ),
            const SizedBox(width: 8),
            Icon(
              yon.ikon,
              size: 14,
              color: secili
                  ? Theme.of(context).colorScheme.primary
                  : Colors.grey.shade500,
            ),
            const SizedBox(width: 6),
            Expanded(
              child: Text(
                yon.label,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                  fontSize: 12,
                  color: secili
                      ? Theme.of(context).colorScheme.primary
                      : Theme.of(context).colorScheme.onSurface,
                  fontWeight: secili ? FontWeight.w600 : FontWeight.normal,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _suzAltBaslik({
    required String baslik,
    required bool acik,
    required bool aktif,
    required VoidCallback onToggle,
  }) {
    return InkWell(
      onTap: onToggle,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
        child: Row(
          children: [
            Expanded(
              child: Text(
                baslik,
                style: TextStyle(
                  fontSize: 12,
                  color: aktif
                      ? Theme.of(context).colorScheme.primary
                      : Theme.of(context).colorScheme.onSurface,
                  fontWeight: aktif ? FontWeight.w600 : FontWeight.normal,
                ),
              ),
            ),
            Icon(
              acik ? Icons.expand_less : Icons.expand_more,
              size: 16,
              color: aktif
                  ? Theme.of(context).colorScheme.primary
                  : Colors.grey.shade400,
            ),
          ],
        ),
      ),
    );
  }

  Widget _siralaAlanSatiri(SiralaAlan alan, {double left = 16}) {
    final secili = _filtre.siralaAlan == alan;
    return InkWell(
      onTap: () {
        final yeni = _filtre.copyWith(siralaAlan: alan);
        setState(() => _filtre = yeni);
        _kaydetPrefs(yeni);
      },
      child: Padding(
        padding: EdgeInsets.fromLTRB(left, 7, 12, 7),
        child: Row(
          children: [
            Icon(
              secili ? Icons.check_circle : Icons.circle_outlined,
              size: 13,
              color: secili
                  ? Theme.of(context).colorScheme.primary
                  : Colors.grey.shade400,
            ),
            const SizedBox(width: 7),
            Icon(
              alan.ikon,
              size: 14,
              color: secili
                  ? Theme.of(context).colorScheme.primary
                  : Colors.grey.shade500,
            ),
            const SizedBox(width: 7),
            Expanded(
              child: Text(
                alan.label,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                  fontSize: 12,
                  color: secili
                      ? Theme.of(context).colorScheme.primary
                      : Colors.black54,
                  fontWeight: secili ? FontWeight.w600 : FontWeight.normal,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _sidePanel() {
    return Material(
      color: Theme.of(context).colorScheme.surface,
      elevation: 8,
      borderRadius: const BorderRadius.only(
        topLeft: Radius.circular(10),
        bottomLeft: Radius.circular(10),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // ── Sırala ──────────────────────────────────────────────────
            _bolumBaslik(Icons.sort, 'SIRALA'),
            ..._kSiralaYonSecenekler.map(_siralaYonSatiri),
            const Divider(height: 1, indent: 12, endIndent: 12),

            // ── Süz ─────────────────────────────────────────────────────
            _bolumBaslik(Icons.tune, 'SÜZ'),
            _siralaAlanSatiri(SiralaAlan.adaGore),
            _suzAltBaslik(
              baslik: 'Puana Göre Sırala',
              acik: _suzPuanAcik,
              aktif: _filtre.siralaAlan != SiralaAlan.adaGore,
              onToggle: () => setState(() {
                _suzPuanAcik = !_suzPuanAcik;
              }),
            ),
            if (_suzPuanAcik)
              ...[
                SiralaAlan.halkSkoru,
                SiralaAlan.anomaliSkoru,
                SiralaAlan.paynotu,
              ].map((alan) => _siralaAlanSatiri(alan, left: 28)),
            const Divider(height: 1, indent: 12, endIndent: 12),

            // ── Grupla ───────────────────────────────────────────────────
            _bolumBaslik(Icons.segment, 'GRUPLA'),
            InkWell(
              onTap: () {
                setState(() => _panelAcik = false);
                Future.delayed(
                    const Duration(milliseconds: 280), _gruplaMenuAc);
              },
              child: Padding(
                padding:
                    const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                child: Row(
                  children: [
                    Expanded(
                      child: Text('Harf Grubuna Git',
                          style: TextStyle(fontSize: 12, color: Theme.of(context).colorScheme.onSurface)),
                    ),
                    Icon(Icons.arrow_forward_ios,
                        size: 11, color: Colors.grey.shade400),
                  ],
                ),
              ),
            ),
            const Divider(height: 1, indent: 12, endIndent: 12),

            // ── Temizle ──────────────────────────────────────────────────
            _bolumBaslik(Icons.refresh, 'TEMİZLE'),
            InkWell(
              onTap: _temizleAktif
                  ? () {
                      final yeni = const HisseFiltreDurum();
                      setState(() {
                        _filtre = yeni;
                        _suzPuanAcik = false;
                        _harfGrubuAktif = false;
                      });
                      _hisseListesiKeys[_tabCtrl.index]
                          .currentState
                          ?.listeBasaDon();
                      _kaydetPrefs(yeni);
                    }
                  : null,
              child: Padding(
                padding:
                    const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                child: Row(
                  children: [
                    Icon(
                      Icons.clear_all,
                      size: 15,
                      color: _temizleAktif
                          ? Colors.red.shade400
                          : Colors.grey.shade300,
                    ),
                    const SizedBox(width: 8),
                    Text(
                      'Tüm seçimleri sıfırla',
                      style: TextStyle(
                        fontSize: 12,
                        color: _temizleAktif
                            ? Colors.red.shade600
                            : Colors.grey.shade400,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
      );
  }

  // ── Build ─────────────────────────────────────────────────────────────────


  @override
  Widget build(BuildContext context) {
    if (widget.aramaMetni.isNotEmpty) return _aramaModuBuild();
    return _normalModuBuild();
  }

  Widget _normalModuBuild() {
    return Stack(
      children: [
        // Ana içerik
        Column(
          children: [
            Container(
              color: Theme.of(context).colorScheme.surface,
              child: TabBar(
                controller: _tabCtrl,
                isScrollable: true,
                tabAlignment: TabAlignment.start,
                labelColor: Theme.of(context).colorScheme.primary,
                unselectedLabelColor: Theme.of(context).colorScheme.onSurfaceVariant,
                indicatorColor: Theme.of(context).colorScheme.primary,
                indicatorWeight: 3,
                labelStyle: const TextStyle(
                    fontWeight: FontWeight.bold, fontSize: 13),
                tabs: _tabLabels.map((l) => Tab(text: l)).toList(),
              ),
            ),
            Expanded(
              child: TabBarView(
                controller: _tabCtrl,
                children: List.generate(
                  _tabLabels.length,
                  (i) => HisseListesi(
                    key: _hisseListesiKeys[i],
                    filtreTip:   _tabFiltre[i][0],
                    filtreDeger: _tabFiltre[i][1],
                    filtre:      _filtre,
                  ),
                ),
              ),
            ),
          ],
        ),

        // Panel açıkken dışarıya tıklayınca kapanır
        if (_panelAcik)
          Positioned.fill(
            child: GestureDetector(
              onTap: () => setState(() => _panelAcik = false),
              behavior: HitTestBehavior.opaque,
              child: Container(color: Colors.black26),
            ),
          ),

        // Tab butonu + panel — içeriğe göre boyutlanır, dikey ortada
        Positioned.fill(
          child: Align(
            alignment: Alignment.centerRight,
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 260),
              curve: Curves.easeOut,
              transform: Matrix4.translationValues(
                _panelAcik ? 0 : _kPanelGenisligi,
                0, 0,
              ),
              child: IntrinsicHeight(
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    _tabButonu(),
                    SizedBox(width: _kPanelGenisligi, child: _sidePanel()),
                  ],
                ),
              ),
            ),
          ),
        ),
      ],
    );
  }

  Widget _aramaModuBuild() {
    if (!HisseCacheService.instance.yuklendi) {
      return Center(
          child: CircularProgressIndicator(
              color: Theme.of(context).colorScheme.primary));
    }
    if (_aramaListesi.isEmpty) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.search_off, size: 64, color: Colors.grey.shade300),
            const SizedBox(height: 12),
            Text('"${widget.aramaMetni}" için sonuç bulunamadı.',
                style:
                    TextStyle(color: Colors.grey.shade500, fontSize: 14)),
          ],
        ),
      );
    }
    return ListView.builder(
      padding: const EdgeInsets.symmetric(vertical: 8),
      itemCount: _aramaListesi.length,
      itemBuilder: (ctx, i) => HisseKarti(data: _aramaListesi[i]),
    );
  }
}

// ── HisseListesi ──────────────────────────────────────────────────────────────

class HisseListesi extends StatefulWidget {
  final String?          filtreTip;
  final String?          filtreDeger;
  final HisseFiltreDurum filtre;

  const HisseListesi({
    super.key,
    this.filtreTip,
    this.filtreDeger,
    required this.filtre,
  });

  @override
  State<HisseListesi> createState() => _HisseListesiState();
}

class _HisseListesiState extends State<HisseListesi> {
  final _scrollCtrl = ScrollController();
  List<Map<String, dynamic>> _docs = [];
  Map<String, int> _harfIndexMap = {};

  @override
  void initState() {
    super.initState();
    // dinleyiciEkle içinde zaten başarı/hata kontrolü var — ekstra kontrol gerekmez
    HisseCacheService.instance.dinleyiciEkle(_cacheGuncellendi);
  }

  @override
  void didUpdateWidget(HisseListesi old) {
    super.didUpdateWidget(old);
    if (widget.filtre != old.filtre) _cacheGuncellendi();
  }

  @override
  void dispose() {
    HisseCacheService.instance.dinleyiciKaldir(_cacheGuncellendi);
    _scrollCtrl.dispose();
    super.dispose();
  }

  // Cache yenilendiğinde veya filtre değiştiğinde çağrılır
  void _cacheGuncellendi() {
    if (!mounted) return;
    final filtreli = _tabFiltrele(HisseCacheService.instance.hisseler);
    final sirali   = _uygula(filtreli);
    setState(() {
      _docs        = sirali;
      _harfIndexMap = _harfIndexHesapla(sirali);
    });
  }

  // Tab'a göre in-memory filtre (Firestore query yerine)
  List<Map<String, dynamic>> _tabFiltrele(List<Map<String, dynamic>> list) {
    if (widget.filtreTip == 'endeks' && widget.filtreDeger != null) {
      return list.where((d) {
        final e = (d['endeksler'] as List?)?.cast<Object?>() ?? [];
        return e.contains(widget.filtreDeger);
      }).toList();
    }
    if (widget.filtreTip == 'pazar' && widget.filtreDeger != null) {
      return list.where((d) => d['pazar'] == widget.filtreDeger).toList();
    }
    return List.of(list);
  }

  // Kullanıcı sıralaması (Map tabanlı)
  List<Map<String, dynamic>> _uygula(List<Map<String, dynamic>> docs) {
    final liste = List<Map<String, dynamic>>.of(docs);

    switch (widget.filtre.siralaAlan) {
      case SiralaAlan.adaGore:
        liste.sort((a, b) => _metinKarsilastir(a, b, 'symbol'));
        break;
      case SiralaAlan.halkSkoru:
        liste.sort((a, b) => _sayiKarsilastir(a, b, 'ortalamaPuan'));
        break;
      case SiralaAlan.anomaliSkoru:
        liste.sort((a, b) => _sayiKarsilastir(a, b, 'paynotu_skoru'));
        break;
      case SiralaAlan.paynotu:
        liste.sort((a, b) => _sayiKarsilastir(a, b, 'paynotu_skoru'));
        break;
    }

    return liste;
  }

  int _metinKarsilastir(
    Map<String, dynamic> a,
    Map<String, dynamic> b,
    String key,
  ) {
    final av = (a[key] ?? '').toString().toUpperCase();
    final bv = (b[key] ?? '').toString().toUpperCase();
    return widget.filtre.siralaYon == SiralaYon.artan
        ? av.compareTo(bv)
        : bv.compareTo(av);
  }

  int _sayiKarsilastir(
    Map<String, dynamic> a,
    Map<String, dynamic> b,
    String key,
  ) {
    final av = _sayiDeger(a, key);
    final bv = _sayiDeger(b, key);

    // Skoru olmayan hisseler her iki yönde de listenin sonunda kalsın.
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;

    return widget.filtre.siralaYon == SiralaYon.artan
        ? av.compareTo(bv)
        : bv.compareTo(av);
  }

  num? _sayiDeger(Map<String, dynamic> d, String key) {
    final v = d[key];
    return v is num ? v : null;
  }

  Map<String, int> _harfIndexHesapla(List<Map<String, dynamic>> docs) {
    final map = <String, int>{};
    for (int i = 0; i < docs.length; i++) {
      final sym = (docs[i]['symbol'] ?? '').toString().toUpperCase();
      if (sym.isNotEmpty) map.putIfAbsent(sym[0], () => i);
    }
    return map;
  }

  // Dışarıdan çağrılır (PayNotuPuanScreen → GlobalKey)
  bool harfeGit(String harf) {
    final idx = _harfIndexMap[harf];
    if (idx == null) return false;
    _harfeGit(idx);
    return true;
  }

  void listeBasaDon() {
    if (_scrollCtrl.hasClients) {
      _scrollCtrl.animateTo(
        0,
        duration: const Duration(milliseconds: 300),
        curve: Curves.easeOut,
      );
    } else {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted && _scrollCtrl.hasClients) {
          _scrollCtrl.animateTo(
            0,
            duration: const Duration(milliseconds: 300),
            curve: Curves.easeOut,
          );
        }
      });
    }
  }

  void _harfeGit(int index) {
    final hedef = index * _kItemYuksekligi;
    if (_scrollCtrl.hasClients) {
      _scrollCtrl.animateTo(hedef,
          duration: const Duration(milliseconds: 300), curve: Curves.easeOut);
    } else {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted && _scrollCtrl.hasClients) {
          _scrollCtrl.animateTo(hedef,
              duration: const Duration(milliseconds: 300), curve: Curves.easeOut);
        }
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    // Hata durumu
    if (!HisseCacheService.instance.yuklendi &&
        HisseCacheService.instance.hata != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.cloud_off, size: 56,
                  color: Theme.of(context).colorScheme.onSurfaceVariant),
              const SizedBox(height: 12),
              const Text(
                'Hisseler yüklenemedi.',
                style:
                    TextStyle(fontWeight: FontWeight.bold, fontSize: 15),
              ),
              const SizedBox(height: 6),
              Text(
                HisseCacheService.instance.hata ?? '',
                style: TextStyle(
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                    fontSize: 11),
                textAlign: TextAlign.center,
                maxLines: 4,
                overflow: TextOverflow.ellipsis,
              ),
              const SizedBox(height: 16),
              ElevatedButton.icon(
                onPressed: () async {
                  await HisseCacheService.instance.yenidenDene();
                },
                icon: const Icon(Icons.refresh, size: 16),
                label: const Text('Tekrar Dene'),
                style: ElevatedButton.styleFrom(
                  backgroundColor: Theme.of(context).colorScheme.primary,
                  foregroundColor: Colors.white,
                ),
              ),
            ],
          ),
        ),
      );
    }

    // Sadece ilk yüklemede spinner — sonrasında asla
    if (!HisseCacheService.instance.yuklendi) {
      return Center(
          child: CircularProgressIndicator(
              color: Theme.of(context).colorScheme.primary));
    }

    if (_docs.isEmpty) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.inbox, size: 64, color: Colors.grey.shade300),
            const SizedBox(height: 12),
            Text('Hisse bulunamadı.',
                style: TextStyle(color: Colors.grey.shade500, fontSize: 15)),
            if (widget.filtre.aktif) ...[
              const SizedBox(height: 6),
              Text('Filtreleri değiştirmeyi deneyin.',
                  style: TextStyle(color: Colors.grey.shade400, fontSize: 13)),
            ],
          ],
        ),
      );
    }

    return ListView.builder(
      controller: _scrollCtrl,
      itemExtent: _kItemYuksekligi,
      padding: const EdgeInsets.only(bottom: 88),
      itemCount: _docs.length,
      itemBuilder: (context, i) => HisseKarti(data: _docs[i]),
    );
  }
}

// ── HisseKarti ────────────────────────────────────────────────────────────────

class HisseKarti extends StatefulWidget {
  final Map<String, dynamic> data;
  const HisseKarti({super.key, required this.data});

  @override
  State<HisseKarti> createState() => _HisseKartiState();
}

class _HisseKartiState extends State<HisseKarti> {
  bool _takipte = false;

  @override
  void initState() {
    super.initState();
    _takipKontrol();
  }

  Future<void> _takipKontrol() async {
    final uid = FirebaseAuth.instance.currentUser?.uid;
    if (uid == null) return;
    final symbol = widget.data['symbol'] ?? '';
    try {
      final doc = await FirebaseFirestore.instance
          .collection('users')
          .doc(uid)
          .collection('takip')
          .doc(symbol)
          .get();
      if (mounted) setState(() => _takipte = doc.exists);
    } catch (_) {}
  }

  Future<void> _takipToggle() async {
    final uid = FirebaseAuth.instance.currentUser?.uid;
    if (uid == null) return;
    final symbol = widget.data['symbol'] ?? '';
    final ref = FirebaseFirestore.instance
        .collection('users')
        .doc(uid)
        .collection('takip')
        .doc(symbol);

    if (_takipte) {
      await ref.delete();
      if (mounted) setState(() => _takipte = false);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text('$symbol takipten çıkarıldı.'),
          duration: const Duration(seconds: 1),
        ));
      }
    } else {
      await ref.set({'eklenmeTarihi': FieldValue.serverTimestamp()});
      if (mounted) setState(() => _takipte = true);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text('$symbol takibe alındı! 👁'),
          backgroundColor: Theme.of(context).colorScheme.primary,
          duration: const Duration(seconds: 1),
        ));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final symbol   = widget.data['symbol']          ?? '';
    final name     = widget.data['name']            ?? '';
    final industry = widget.data['industry']        ?? '';
    final sector   = widget.data['sector']          ?? '';
    final logo     = widget.data['logo']            ?? '';
    final wr           = (widget.data['weightedRating'] ?? 0.0).toDouble();
    final yildiz       = (wr / 2).clamp(0.0, 5.0);
    final paynotuRaw      = widget.data['paynotu_skoru'];
    final double? paynotu = paynotuRaw == null ? null : (paynotuRaw as num).toDouble();
    final bool hasPaynotu = widget.data['has_paynotu'] == true;
    final bool skorVar    = hasPaynotu && paynotu != null;

    return Slidable(
      key: ValueKey(symbol),
      dragStartBehavior: DragStartBehavior.start,
      startActionPane: ActionPane(
        motion: const DrawerMotion(),
        extentRatio: 0.25,
        children: [
          CustomSlidableAction(
            onPressed: (_) => Navigator.push(
              context,
              MaterialPageRoute(
                builder: (_) =>
                    SozHakkiScreen(symbol: symbol, hisseAdi: name),
              ),
            ),
            backgroundColor: Colors.transparent,
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: const [
                Icon(Icons.star, color: Color(0xFFFFC107), size: 28),
                SizedBox(height: 4),
                Text('Sözün\nKısası',
                    textAlign: TextAlign.center,
                    style: TextStyle(
                        fontSize: 10,
                        color: Colors.black54,
                        fontWeight: FontWeight.bold)),
              ],
            ),
          ),
        ],
      ),
      endActionPane: ActionPane(
        motion: const DrawerMotion(),
        extentRatio: 0.25,
        children: [
          CustomSlidableAction(
            onPressed: (_) => _takipToggle(),
            backgroundColor: Colors.transparent,
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(
                  _takipte
                      ? Icons.remove_red_eye
                      : Icons.remove_red_eye_outlined,
                  color: _takipte
                      ? Theme.of(context).colorScheme.primary
                      : Theme.of(context).colorScheme.onSurfaceVariant,
                  size: 28,
                ),
                const SizedBox(height: 4),
                Text(
                  _takipte ? 'Takipte' : 'Takip Et',
                  style: TextStyle(
                    fontSize: 10,
                    color: _takipte
                        ? Theme.of(context).colorScheme.primary
                        : Theme.of(context).colorScheme.onSurfaceVariant,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
      child: GestureDetector(
        onTap: () => Navigator.push(
          context,
          MaterialPageRoute(
            builder: (_) => DetayScreen(hisseData: widget.data),
          ),
        ),
        child: Container(
          margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
          decoration: BoxDecoration(
            color: skorVar
                ? Theme.of(context).colorScheme.surface
                : Theme.of(context).colorScheme.surfaceContainerHighest,
            borderRadius: BorderRadius.circular(12),
            boxShadow: [
              BoxShadow(
                color: Colors.black.withValues(alpha: 0.05),
                blurRadius: 4,
                offset: const Offset(0, 2),
              ),
            ],
          ),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            child: Row(
              children: [
                ClipRRect(
                  borderRadius: BorderRadius.circular(8),
                  child: logo.isNotEmpty
                      ? Image.network(
                          logo,
                          width: 42, height: 42,
                          fit: BoxFit.cover,
                          errorBuilder: (context, e, s) =>
                              _logoFallback(symbol, sector),
                        )
                      : _logoFallback(symbol, sector),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Row(
                        children: [
                          Text(symbol,
                              style: const TextStyle(
                                  fontWeight: FontWeight.bold,
                                  fontSize: 14)),
                          const SizedBox(width: 6),
                          Row(
                            mainAxisSize: MainAxisSize.min,
                            children: List.generate(5, (i) {
                              if (i < yildiz.floor()) {
                                return const Icon(Icons.star,
                                    size: 15,
                                    color: Color(0xFFFFC107));
                              } else if (i < yildiz) {
                                return const Icon(Icons.star_half,
                                    size: 15,
                                    color: Color(0xFFFFC107));
                              } else {
                                return const Icon(Icons.star_border,
                                    size: 15,
                                    color: Color(0xFFFFC107));
                              }
                            }),
                          ),
                        ],
                      ),
                      Text(name,
                          style: TextStyle(
                              fontSize: 11,
                              color: Theme.of(context).colorScheme.onSurface),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis),
                      Text(industry,
                          style: TextStyle(
                              fontSize: 11,
                              color: Theme.of(context).colorScheme.onSurfaceVariant),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis),
                    ],
                  ),
                ),
                const SizedBox(width: 8),
                Container(
                  width: 58,
                  padding: const EdgeInsets.symmetric(
                      vertical: 8, horizontal: 4),
                  decoration: BoxDecoration(
                    color: skorVar
                        ? PayNotuColors.forScore(paynotu)
                        : Theme.of(context).colorScheme.onSurface.withValues(alpha: 0.12),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(
                        skorVar ? paynotu.toStringAsFixed(2) : '—',
                        style: TextStyle(
                          fontWeight: FontWeight.bold,
                          fontSize: 14,
                          color: skorVar
                              ? Colors.white
                              : Theme.of(context).colorScheme.onSurfaceVariant,
                        ),
                      ),
                      Text(
                        'PayNotu',
                        style: TextStyle(
                            fontSize: 8,
                            color: skorVar
                                ? Colors.white.withValues(alpha: 0.85)
                                : Theme.of(context).colorScheme.onSurfaceVariant,
                            height: 1.1),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _logoFallback(String symbol, String sector) {
    final renk = sektorRenk(sector);
    return Container(
      width: 42, height: 42,
      decoration: BoxDecoration(
        color: renk.withValues(alpha: 0.15),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Center(
        child: Text(
          symbol.length >= 2 ? symbol.substring(0, 2) : symbol,
          style: TextStyle(
            fontWeight: FontWeight.bold,
            fontSize: 14,
            color: renk,
          ),
        ),
      ),
    );
  }
}
