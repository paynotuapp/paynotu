import 'dart:async';
import 'package:cloud_firestore/cloud_firestore.dart';

/// Tüm hisseleri bir kez çekip memory'de tutan singleton cache.
/// HisseListesi bu servisten okur — Firestore'a tekrar gitmez.
class HisseCacheService {
  HisseCacheService._();
  static final HisseCacheService instance = HisseCacheService._();

  List<Map<String, dynamic>> _hisseler = [];
  bool _yuklendi = false;
  bool _yukleniyor = false;
  String? _hata;
  Timer? _yenilemeTimer;

  final _dinleyiciler = <void Function()>[];

  bool get yuklendi   => _yuklendi;
  bool get yukleniyor => _yukleniyor;
  String? get hata    => _hata;

  /// Anlık snapshot — kopyasını döner, dışarıdan mutation olmaz.
  List<Map<String, dynamic>> get hisseler => List.unmodifiable(_hisseler);

  /// Listener ekler; sonuç zaten hazırsa (başarı veya hata) anında tetikler.
  void dinleyiciEkle(void Function() cb) {
    _dinleyiciler.add(cb);
    if (_yuklendi || _hata != null) cb();
  }

  void dinleyiciKaldir(void Function() cb) => _dinleyiciler.remove(cb);

  void _bildir() {
    for (final cb in List.of(_dinleyiciler)) {
      cb();
    }
  }

  /// AnaSayfa init'te bir kez çağrılır.
  /// İkinci çağrıda no-op; 5 dk'da bir arka planda yeniler.
  Future<void> ilkYukle() async {
    if (_yuklendi || _yukleniyor) return;
    await _yukle();
    _yenilemeTimer?.cancel();
    _yenilemeTimer = Timer.periodic(
      const Duration(minutes: 5),
      (_) => _yukle(),
    );
  }

  /// Hata sonrası kullanıcı "Tekrar Dene" butonuna bastığında.
  Future<void> yenidenDene() async {
    if (_yukleniyor) return;
    _yuklendi  = false;
    _hata      = null;
    _bildir(); // spinner'a geçmesi için
    await _yukle();
  }

  Future<void> _yukle() async {
    if (_yukleniyor) return;
    _yukleniyor = true;
    try {
      final snap = await FirebaseFirestore.instance
          .collection('hisseler')
          .where('kap_aktif', isEqualTo: true)
          .get()
          .timeout(const Duration(seconds: 20));

      _hisseler = snap.docs
          .map((d) => <String, dynamic>{'id': d.id, ...d.data()})
          .toList();
      _yuklendi = true;
      _hata     = null;
    } catch (e) {
      if (!_yuklendi) {
        _hata = e.toString();
      }
    } finally {
      _yukleniyor = false;
      _bildir();
    }
  }

  void dispose() {
    _yenilemeTimer?.cancel();
    _dinleyiciler.clear();
  }
}
