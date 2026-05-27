import 'package:cloud_firestore/cloud_firestore.dart';

enum OnayKanali {
  mobil,
  web;

  String get label {
    switch (this) {
      case OnayKanali.mobil:
        return 'Mobil Uygulama';
      case OnayKanali.web:
        return 'Web';
    }
  }

  String get firestoreKey {
    switch (this) {
      case OnayKanali.mobil:
        return 'mobil';
      case OnayKanali.web:
        return 'web';
    }
  }

  static OnayKanali fromString(String value) {
    switch (value) {
      case 'web':
        return OnayKanali.web;
      default:
        return OnayKanali.mobil;
    }
  }
}

final class SozlesmeDefinition {
  final String id;
  final String baslik;
  final String versiyon;
  final DateTime yayinTarihi;
  final String icerikUrl;
  final bool zorunlu;
  final String? guncellemeNotu;

  const SozlesmeDefinition({
    required this.id,
    required this.baslik,
    required this.versiyon,
    required this.yayinTarihi,
    required this.icerikUrl,
    required this.zorunlu,
    this.guncellemeNotu,
  });

  SozlesmeDefinition copyWith({
    String? id,
    String? baslik,
    String? versiyon,
    DateTime? yayinTarihi,
    String? icerikUrl,
    bool? zorunlu,
    String? guncellemeNotu,
  }) {
    return SozlesmeDefinition(
      id: id ?? this.id,
      baslik: baslik ?? this.baslik,
      versiyon: versiyon ?? this.versiyon,
      yayinTarihi: yayinTarihi ?? this.yayinTarihi,
      icerikUrl: icerikUrl ?? this.icerikUrl,
      zorunlu: zorunlu ?? this.zorunlu,
      guncellemeNotu: guncellemeNotu ?? this.guncellemeNotu,
    );
  }

  factory SozlesmeDefinition.fromMap(Map<String, dynamic> map) {
    return SozlesmeDefinition(
      id: map['id'] as String,
      baslik: map['baslik'] as String,
      versiyon: map['versiyon'] as String,
      yayinTarihi: (map['yayinTarihi'] as Timestamp).toDate(),
      icerikUrl: map['icerikUrl'] as String,
      zorunlu: map['zorunlu'] as bool? ?? true,
      guncellemeNotu: map['guncellemeNotu'] as String?,
    );
  }

  Map<String, dynamic> toMap() {
    return {
      'id': id,
      'baslik': baslik,
      'versiyon': versiyon,
      'yayinTarihi': Timestamp.fromDate(yayinTarihi),
      'icerikUrl': icerikUrl,
      'zorunlu': zorunlu,
      if (guncellemeNotu != null) 'guncellemeNotu': guncellemeNotu,
    };
  }
}

final class SozlesmeOnayKaydi {
  final String sozlesmeId;
  final String versiyon;
  final DateTime onayTarihi;
  final OnayKanali kanal;

  const SozlesmeOnayKaydi({
    required this.sozlesmeId,
    required this.versiyon,
    required this.onayTarihi,
    required this.kanal,
  });

  SozlesmeOnayKaydi copyWith({
    String? sozlesmeId,
    String? versiyon,
    DateTime? onayTarihi,
    OnayKanali? kanal,
  }) {
    return SozlesmeOnayKaydi(
      sozlesmeId: sozlesmeId ?? this.sozlesmeId,
      versiyon: versiyon ?? this.versiyon,
      onayTarihi: onayTarihi ?? this.onayTarihi,
      kanal: kanal ?? this.kanal,
    );
  }

  factory SozlesmeOnayKaydi.fromMap(
      String sozlesmeId, Map<String, dynamic> map) {
    return SozlesmeOnayKaydi(
      sozlesmeId: sozlesmeId,
      versiyon: map['versiyon'] as String,
      onayTarihi: (map['onayTarihi'] as Timestamp).toDate(),
      kanal: OnayKanali.fromString(map['kanal'] as String? ?? 'mobil'),
    );
  }

  Map<String, dynamic> toMap() {
    return {
      'versiyon': versiyon,
      'onayTarihi': Timestamp.fromDate(onayTarihi),
      'kanal': kanal.firestoreKey,
    };
  }
}

final class SozlesmeUiModel {
  final SozlesmeDefinition definition;
  final SozlesmeOnayKaydi? onayKaydi;
  final bool okundu;

  const SozlesmeUiModel({
    required this.definition,
    this.onayKaydi,
    this.okundu = false,
  });

  bool get onaylandi =>
      onayKaydi != null && onayKaydi!.versiyon == definition.versiyon;

  bool get bekleyenOnay => !onaylandi && definition.zorunlu;

  bool get checkboxAktif => okundu && !onaylandi;

  SozlesmeUiModel copyWith({
    SozlesmeDefinition? definition,
    SozlesmeOnayKaydi? onayKaydi,
    bool? okundu,
  }) {
    return SozlesmeUiModel(
      definition: definition ?? this.definition,
      onayKaydi: onayKaydi ?? this.onayKaydi,
      okundu: okundu ?? this.okundu,
    );
  }
}