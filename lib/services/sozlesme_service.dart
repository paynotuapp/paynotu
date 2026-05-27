import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_auth/firebase_auth.dart';
import '../models/sozlesme_model.dart';

class SozlesmeService {
  SozlesmeService._();
  static final SozlesmeService instance = SozlesmeService._();

  final FirebaseFirestore _db = FirebaseFirestore.instance;
  final FirebaseAuth _auth = FirebaseAuth.instance;

  final Set<String> _okunduIds = {};

  CollectionReference<Map<String, dynamic>> get _sozlesmelerCol =>
      _db.collection('sozlesmeler');

  DocumentReference<Map<String, dynamic>> get _kullaniciDoc =>
      _db.collection('users').doc(_auth.currentUser!.uid);

  Future<List<SozlesmeDefinition>> aktifSozlesmeleriGetir() async {
    final snapshot = await _sozlesmelerCol
        .where('aktif', isEqualTo: true)
        .orderBy('sira')
        .get();

    return snapshot.docs
        .map((doc) =>
            SozlesmeDefinition.fromMap({...doc.data(), 'id': doc.id}))
        .toList();
  }

  Future<Map<String, SozlesmeOnayKaydi>> kullaniciOnaylariGetir() async {
    final doc = await _kullaniciDoc.get();
    if (!doc.exists) return {};

    final data = doc.data();
    if (data == null) return {};

    final onaylarRaw =
        data['sozlesmeOnaylari'] as Map<String, dynamic>? ?? {};

    final Map<String, SozlesmeOnayKaydi> result = {};
    for (final entry in onaylarRaw.entries) {
      result[entry.key] = SozlesmeOnayKaydi.fromMap(
        entry.key,
        entry.value as Map<String, dynamic>,
      );
    }
    return result;
  }

  Future<List<SozlesmeUiModel>> sozlesmeUiModelleriniGetir() async {
    final definitions = await aktifSozlesmeleriGetir();
    final onaylar = await kullaniciOnaylariGetir();

    return definitions.map((def) {
      return SozlesmeUiModel(
        definition: def,
        onayKaydi: onaylar[def.id],
        okundu: _okunduIds.contains(def.id),
      );
    }).toList();
  }

  void sozlesmeOkunduIsaretle(String sozlesmeId) {
    _okunduIds.add(sozlesmeId);
  }

  bool sozlesmeOkunduMu(String sozlesmeId) {
    return _okunduIds.contains(sozlesmeId);
  }

  Future<void> sozlesmeOnayla({
    required SozlesmeDefinition definition,
    OnayKanali kanal = OnayKanali.mobil,
  }) async {
    final onayKaydi = SozlesmeOnayKaydi(
      sozlesmeId: definition.id,
      versiyon: definition.versiyon,
      onayTarihi: DateTime.now(),
      kanal: kanal,
    );

    await _kullaniciDoc.update({
      'sozlesmeOnaylari.${definition.id}': onayKaydi.toMap(),
      'sozlesmeOnaylariGuncellemeTarihi': FieldValue.serverTimestamp(),
    });
  }

  Future<void> topluOnayla({
    required List<SozlesmeDefinition> definitions,
    OnayKanali kanal = OnayKanali.mobil,
  }) async {
    final Map<String, dynamic> updates = {};
    final now = DateTime.now();

    for (final def in definitions) {
      final onayKaydi = SozlesmeOnayKaydi(
        sozlesmeId: def.id,
        versiyon: def.versiyon,
        onayTarihi: now,
        kanal: kanal,
      );
      updates['sozlesmeOnaylari.${def.id}'] = onayKaydi.toMap();
    }

    updates['sozlesmeOnaylariGuncellemeTarihi'] =
        FieldValue.serverTimestamp();

    await _kullaniciDoc.update(updates);
  }

  Future<bool> bekleyenZorunluOnayVarMi() async {
    final models = await sozlesmeUiModelleriniGetir();
    return models.any((m) => m.bekleyenOnay);
  }

  Future<void> kullaniciDokumaniniHazirla() async {
    final doc = await _kullaniciDoc.get();
    if (!doc.exists ||
        (doc.data() ?? {})['sozlesmeOnaylari'] == null) {
      await _kullaniciDoc.set(
        {'sozlesmeOnaylari': {}},
        SetOptions(merge: true),
      );
    }
  }

  void sessionSifirla() {
    _okunduIds.clear();
  }
}