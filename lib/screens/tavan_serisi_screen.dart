import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

class TavanSerisiScreen extends StatefulWidget {
  const TavanSerisiScreen({super.key});

  @override
  State<TavanSerisiScreen> createState() => _TavanSerisiScreenState();
}

class _TavanSerisiScreenState extends State<TavanSerisiScreen>
    with SingleTickerProviderStateMixin {
  final _fiyatController = TextEditingController();
  final _adetController = TextEditingController();

  List<_TavanSatir> _satirlar = [];
  bool _hesaplandi = false;
  double _bazFiyat = 0;
  int _adet = 0;

  late final AnimationController _animCtrl;
  late final Animation<Offset> _slideAnim;

  static const double _tavanOrani = 0.10;
  static const int _satirSayisi = 15;

  @override
  void initState() {
    super.initState();
    _animCtrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 450),
    );
    _slideAnim = Tween<Offset>(
      begin: const Offset(0, 1),
      end: Offset.zero,
    ).animate(CurvedAnimation(parent: _animCtrl, curve: Curves.easeOutCubic));
  }

  @override
  void dispose() {
    _fiyatController.dispose();
    _adetController.dispose();
    _animCtrl.dispose();
    super.dispose();
  }

  void _hesapla() {
    final fiyatText = _fiyatController.text.trim().replaceAll(',', '.');
    final fiyat = double.tryParse(fiyatText);

    if (fiyat == null || fiyat <= 0) {
      _snack('Geçerli bir hisse fiyatı girin.');
      return;
    }

    final adetText = _adetController.text.trim();
    final adet = adetText.isEmpty ? 0 : (int.tryParse(adetText) ?? 0);

    if (adetText.isNotEmpty && adet <= 0) {
      _snack('Adet 0\'dan büyük olmalı.');
      return;
    }

    final satirlar = <_TavanSatir>[];
    double gununFiyat = fiyat;
    for (int i = 1; i <= _satirSayisi; i++) {
      gununFiyat = gununFiyat * (1 + _tavanOrani);
      final hisseArtis = gununFiyat - fiyat;
      final artisYuzde = (hisseArtis / fiyat) * 100;
      satirlar.add(_TavanSatir(
        gun: i,
        fiyat: gununFiyat,
        hisseArtis: hisseArtis,
        artisYuzde: artisYuzde,
        portfoyDeger: adet > 0 ? gununFiyat * adet : null,
        portfoyKar: adet > 0 ? hisseArtis * adet : null,
      ));
    }

    FocusScope.of(context).unfocus();

    setState(() {
      _satirlar = satirlar;
      _bazFiyat = fiyat;
      _adet = adet;
      _hesaplandi = true;
    });

    // Her hesaplamada animasyonu sıfırlayıp tekrar oynat
    _animCtrl.forward(from: 0);
  }

  void _snack(String msg) {
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Text(msg),
      backgroundColor: Colors.red,
      duration: const Duration(seconds: 2),
    ));
  }

  String _fmtFiyat(double v) {
    if (v >= 10) return v.toStringAsFixed(2);
    if (v >= 1) return v.toStringAsFixed(3);
    return v.toStringAsFixed(4);
  }

  String _fmtTL(double v) {
    if (v >= 1000000) return '${(v / 1000000).toStringAsFixed(2)}M ₺';
    if (v >= 1000) return '${(v / 1000).toStringAsFixed(2)}K ₺';
    return '${v.toStringAsFixed(2)} ₺';
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
        title: const Text('📈 Tavan Serisi Hesaplayıcı',
            style: TextStyle(
                color: Colors.white, fontWeight: FontWeight.bold)),
      ),
      body: Column(
        children: [
          // ── Sonuç alanı (üst, genişleyen) ────────────────────────────
          Expanded(
            child: _hesaplandi ? _sonucListesi() : _bosEkran(),
          ),

          // ── Giriş + buton (alt, sabit) ────────────────────────────────
          _inputPanel(),
        ],
      ),
    );
  }

  // ── Boş ekran ──────────────────────────────────────────────────────────

  Widget _bosEkran() {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.trending_up, size: 80, color: Colors.grey.shade200),
          const SizedBox(height: 16),
          Text(
            'Fiyat gir, hesapla.',
            style: TextStyle(
                fontSize: 16,
                color: Colors.grey.shade500,
                fontWeight: FontWeight.w500),
          ),
          const SizedBox(height: 6),
          Text(
            'Adet girerek portföy değerini\nde hesaplayabilirsiniz.',
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: 12, color: Colors.grey.shade400),
          ),
        ],
      ),
    );
  }

  // ── Sonuç listesi (slide-up animasyonlu) ───────────────────────────────

  Widget _sonucListesi() {
    return SlideTransition(
      position: _slideAnim,
      child: Column(
        children: [
          // Özet şerit
          _ozetWidget(),
          // Liste
          Expanded(
            child: ListView.separated(
              padding: const EdgeInsets.fromLTRB(12, 8, 12, 12),
              itemCount: _satirlar.length,
              separatorBuilder: (_, i) => const SizedBox(height: 8),
              itemBuilder: (ctx, i) => _kartWidget(_satirlar[i], i),
            ),
          ),
        ],
      ),
    );
  }

  Widget _ozetWidget() {
    final ilkPortfoy = _adet > 0 ? _bazFiyat * _adet : null;
    return Container(
      width: double.infinity,
      color: Theme.of(context).colorScheme.primary.withValues(alpha: 0.08),
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 9),
      child: Row(
        children: [
          Icon(Icons.info_outline,
              size: 13, color: Theme.of(context).colorScheme.primary),
          const SizedBox(width: 6),
          Expanded(
            child: Text(
              ilkPortfoy != null
                  ? 'Baz: ${_fmtFiyat(_bazFiyat)} ₺  •  '
                      'Adet: $_adet  •  '
                      'Maliyet: ${_fmtTL(ilkPortfoy)}'
                  : 'Baz fiyat: ${_fmtFiyat(_bazFiyat)} ₺  •  Tavan: %10/gün',
              style: TextStyle(
                  fontSize: 11,
                  color: Theme.of(context).colorScheme.primary,
                  fontWeight: FontWeight.w500),
            ),
          ),
        ],
      ),
    );
  }

  Widget _kartWidget(_TavanSatir s, int index) {
    final renk = _renk(index);
    final adetVar = s.portfoyDeger != null;

    return Container(
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border(left: BorderSide(color: renk, width: 3)),
        boxShadow: [
          BoxShadow(
              color: Colors.black.withValues(alpha: 0.04),
              blurRadius: 4,
              offset: const Offset(0, 2)),
        ],
      ),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      child: Column(
        children: [
          // Üst: badge + yüzde
          Row(
            children: [
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  color: renk.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Text(
                  '${s.gun}. Tavan',
                  style: TextStyle(
                      fontWeight: FontWeight.bold,
                      fontSize: 12,
                      color: renk),
                ),
              ),
              const Spacer(),
              Text(
                '+${s.artisYuzde.toStringAsFixed(1)}%',
                style: TextStyle(
                    fontSize: 14,
                    fontWeight: FontWeight.bold,
                    color: renk),
              ),
            ],
          ),
          const SizedBox(height: 8),
          // Hisse satırı
          Row(
            children: [
              Icon(Icons.show_chart, size: 13, color: Theme.of(context).colorScheme.onSurfaceVariant),
              const SizedBox(width: 4),
              Text('Hisse:',
                  style: TextStyle(fontSize: 12, color: Theme.of(context).colorScheme.onSurfaceVariant)),
              const SizedBox(width: 6),
              Text(
                '${_fmtFiyat(s.fiyat)} ₺',
                style: const TextStyle(
                    fontSize: 13, fontWeight: FontWeight.w600),
              ),
              const SizedBox(width: 6),
              Text(
                '(+${_fmtFiyat(s.hisseArtis)} ₺)',
                style:
                    TextStyle(fontSize: 12, color: Colors.green.shade700),
              ),
            ],
          ),
          // Portföy satırı
          if (adetVar) ...[
            const SizedBox(height: 5),
            Row(
              children: [
                const Icon(Icons.account_balance_wallet,
                    size: 13, color: Colors.blueGrey),
                const SizedBox(width: 4),
                const Text('Portföy:',
                    style:
                        TextStyle(fontSize: 12, color: Colors.blueGrey)),
                const SizedBox(width: 6),
                Text(
                  _fmtTL(s.portfoyDeger!),
                  style: const TextStyle(
                      fontSize: 13, fontWeight: FontWeight.w600),
                ),
                const SizedBox(width: 6),
                Text(
                  '(+${_fmtTL(s.portfoyKar!)})',
                  style:
                      TextStyle(fontSize: 12, color: Colors.green.shade700),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }

  // ── Alt panel: inputlar + hesapla butonu ───────────────────────────────

  Widget _inputPanel() {
    return Container(
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surface,
        boxShadow: [
          BoxShadow(
              color: Colors.black.withValues(alpha: 0.08),
              blurRadius: 12,
              offset: const Offset(0, -3)),
        ],
        borderRadius: const BorderRadius.vertical(top: Radius.circular(20)),
      ),
      padding: EdgeInsets.fromLTRB(
        16,
        16,
        16,
        16 + MediaQuery.of(context).padding.bottom,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          // Tutamaç çizgisi
          Center(
            child: Container(
              width: 36,
              height: 4,
              margin: const EdgeInsets.only(bottom: 14),
              decoration: BoxDecoration(
                  color: Colors.grey.shade300,
                  borderRadius: BorderRadius.circular(2)),
            ),
          ),
          // Giriş alanları
          Row(
            children: [
              Expanded(
                flex: 5,
                child: TextField(
                  controller: _fiyatController,
                  keyboardType:
                      const TextInputType.numberWithOptions(decimal: true),
                  inputFormatters: [
                    FilteringTextInputFormatter.allow(RegExp(r'[\d,.]')),
                  ],
                  textInputAction: TextInputAction.next,
                  decoration: InputDecoration(
                    labelText: 'Hisse Fiyatı (₺)',
                    hintText: 'ör: 42.50',
                    prefixIcon: Icon(Icons.attach_money,
                        color: Theme.of(context).colorScheme.primary, size: 18),
                    border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(12)),
                    focusedBorder: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(12),
                        borderSide: BorderSide(
                            color: Theme.of(context).colorScheme.primary, width: 1.5)),
                    contentPadding: const EdgeInsets.symmetric(
                        horizontal: 12, vertical: 14),
                  ),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                flex: 4,
                child: TextField(
                  controller: _adetController,
                  keyboardType: TextInputType.number,
                  inputFormatters: [
                    FilteringTextInputFormatter.digitsOnly,
                  ],
                  textInputAction: TextInputAction.done,
                  onSubmitted: (_) => _hesapla(),
                  decoration: InputDecoration(
                    labelText: 'Adet',
                    hintText: 'ör: 100',
                    prefixIcon: const Icon(Icons.tag,
                        color: Colors.blueGrey, size: 18),
                    border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(12)),
                    focusedBorder: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(12),
                        borderSide: BorderSide(
                            color: Theme.of(context).colorScheme.primary, width: 1.5)),
                    contentPadding: const EdgeInsets.symmetric(
                        horizontal: 12, vertical: 14),
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          // Hesapla butonu
          SizedBox(
            width: double.infinity,
            height: 50,
            child: ElevatedButton(
              onPressed: _hesapla,
              style: ElevatedButton.styleFrom(
                backgroundColor: Theme.of(context).colorScheme.primary,
                foregroundColor: Colors.white,
                shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(14)),
                elevation: 0,
              ),
              child: const Text(
                'Hesapla',
                style: TextStyle(
                    fontSize: 15, fontWeight: FontWeight.bold),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Color _renk(int index) {
    if (index < 3) return Colors.green.shade700;
    if (index < 6) return Colors.orange.shade700;
    if (index < 10) return Colors.deepOrange.shade700;
    return Colors.red.shade700;
  }
}

class _TavanSatir {
  final int gun;
  final double fiyat;
  final double hisseArtis;
  final double artisYuzde;
  final double? portfoyDeger;
  final double? portfoyKar;

  const _TavanSatir({
    required this.gun,
    required this.fiyat,
    required this.hisseArtis,
    required this.artisYuzde,
    this.portfoyDeger,
    this.portfoyKar,
  });
}
