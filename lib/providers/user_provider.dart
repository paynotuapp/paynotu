import 'package:flutter/material.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_auth/firebase_auth.dart';
import '../models/user_model.dart';

class UserProvider extends ChangeNotifier {
  UserModel? _user;
  bool _yukleniyor = false;
  String? _hata;

  UserModel? get user => _user;
  bool get yukleniyor => _yukleniyor;
  String? get hata => _hata;

  // Küfür/yasaklı kelime listesi
  static const _blacklist = [
    'admin', 'paynotu', 'moderator', 'sistem',
    'sik', 'orospu', 'piç', 'göt', 'bok',
  ];

  Future<void> fetchUserData(String uid) async {
    _yukleniyor = true;
    _hata = null;
    notifyListeners();

    try {
      final doc = await FirebaseFirestore.instance
          .collection('users')
          .doc(uid)
          .get();

      if (doc.exists && doc.data() != null) {
        _user = UserModel.fromMap(uid, doc.data()!);
        _user = _user!.copyWith(
          completionRate: _calculateCompletion(_user!),
        );
      } else {
        // Yeni kullanıcı — Firebase Auth'tan temel bilgileri al
        final authUser = FirebaseAuth.instance.currentUser;
        _user = UserModel(
          uid: uid,
          displayName: authUser?.displayName,
          email: authUser?.email,
          photoURL: authUser?.photoURL,
        );
      }
    } catch (e) {
      _hata = 'Veriler yüklenemedi: $e';
      _user = null;
    } finally {
      _yukleniyor = false;
      notifyListeners();
    }
  }

  double _calculateCompletion(UserModel u) {
    int puan = 0;
    if (u.photoURL != null && u.photoURL!.isNotEmpty) puan++;
    if (u.phoneNumber != null && u.phoneNumber!.isNotEmpty) puan++;
    if (u.address != null && u.address!.isNotEmpty) puan++;
    if (u.profession != null && u.profession!.isNotEmpty) puan++;
    if (u.username != null && u.username!.isNotEmpty) puan++;
    return puan / 5.0;
  }

  Future<bool> checkUsernameAvailability(String username) async {
    try {
      final uid = FirebaseAuth.instance.currentUser?.uid;
      // usernames koleksiyonunu kontrol et — index gerektirmez
      final doc = await FirebaseFirestore.instance
          .collection('usernames')
          .doc(username)
          .get();
      if (!doc.exists) return true; // Hiç alınmamış
      return doc.data()?['uid'] == uid; // Kendi username'i
    } catch (e) {
      debugPrint('checkUsernameAvailability hata: $e');
      return true;
    }
  }

  Future<String?> updateUsername(String newUsername) async {
    if (_user == null) return 'Kullanıcı bulunamadı';

    // Regex kontrolü
    final regex = RegExp(r'^[a-z0-9._]{3,15}$');
    if (!regex.hasMatch(newUsername)) {
      return 'Kullanıcı adı 3-15 karakter, sadece küçük harf, rakam, nokta ve alt çizgi içerebilir';
    }

    // Blacklist kontrolü
    for (final kelime in _blacklist) {
      if (newUsername.contains(kelime)) {
        return 'Bu kullanıcı adı kullanılamaz';
      }
    }

    // 30 gün kontrolü
    if (_user!.lastUsernameChange != null) {
      final fark = DateTime.now().difference(_user!.lastUsernameChange!);
      if (fark.inDays < 14) {
        final sonrakiTarih = _user!.lastUsernameChange!
            .add(const Duration(days: 14));
        final gun = sonrakiTarih.day.toString().padLeft(2, '0');
        final ay = sonrakiTarih.month.toString().padLeft(2, '0');
        final yil = sonrakiTarih.year;
        return 'Bir sonraki değişim hakkın $gun.$ay.$yil tarihinde';
      }
    }

    // Benzersizlik kontrolü
    final musait = await checkUsernameAvailability(newUsername);
    if (!musait) return 'Bu kullanıcı adı zaten alınmış';

    // Firestore güncelle
    try {
      final simdi = DateTime.now();

      // Eski username'i usernames koleksiyonundan sil
      if (_user!.username != null && _user!.username!.isNotEmpty) {
        await FirebaseFirestore.instance
            .collection('usernames')
            .doc(_user!.username)
            .delete();
      }

      // Yeni username'i usernames koleksiyonuna yaz
      await FirebaseFirestore.instance
          .collection('usernames')
          .doc(newUsername)
          .set({'uid': _user!.uid});

      // users koleksiyonunu güncelle
      await FirebaseFirestore.instance
          .collection('users')
          .doc(_user!.uid)
          .update({
        'username': newUsername,
        'lastUsernameChange': Timestamp.fromDate(simdi),
      });

      _user = _user!.copyWith(
        username: newUsername,
        lastUsernameChange: simdi,
      );
      notifyListeners();
      return null;
    } catch (e) {
      return 'Güncelleme başarısız: $e';
    }
  }

  Future<String?> updateProfile(Map<String, dynamic> data) async {
    if (_user == null) return 'Kullanıcı bulunamadı';
    try {
      // Firestore'da sadece gelen alanları güncelle — username'e asla dokunma
      final gonderilecek = Map<String, dynamic>.from(data);
      gonderilecek.remove('username'); // username bu metotla asla değişmez

      await FirebaseFirestore.instance
          .collection('users')
          .doc(_user!.uid)
          .update(gonderilecek);

      // Lokal state — sadece gelen alanları copyWith ile güncelle
      _user = _user!.copyWith(
        displayName: data['displayName'] as String?,
        phoneNumber: data['telefon'] as String?,
        profession:  data['meslek']   as String?,
        address:     data['adres']    as String?,
        city:        data['il']       as String?,
        district:    data['ilce']     as String?,
        country:     data['ulke']     as String?,
      );

      _user = _user!.copyWith(
        completionRate: _calculateCompletion(_user!),
      );

      notifyListeners();
      return null;
    } catch (e) {
      return 'Güncelleme başarısız: $e';
    }
  }

  void updatePhotoURLAnlik(String url) {
    if (_user == null) return;
    _user = _user!.copyWith(photoURL: url);
    notifyListeners();
  }

  void clearUser() {
    _user = null;
    _hata = null;
    _yukleniyor = false;
    notifyListeners();
  }
}
