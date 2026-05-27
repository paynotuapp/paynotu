class UserModel {
  final String uid;
  final String? username;
  final String? displayName;
  final String? email;
  final String? photoURL;
  final String? phoneNumber;
  final String? profession;
  final String? address;
  final String? city;
  final String? district;
  final String? country;
  final DateTime? createdAt;
  final DateTime? lastLogin;
  final DateTime? lastUsernameChange;
  final double completionRate;

  // İstatistikler (Duygusal Akıl + yorum migration)
  final int totalComments;
  final double averageRating;
  final double trustScore;

  const UserModel({
    required this.uid,
    this.username,
    this.displayName,
    this.email,
    this.photoURL,
    this.phoneNumber,
    this.profession,
    this.address,
    this.city,
    this.district,
    this.country,
    this.createdAt,
    this.lastLogin,
    this.lastUsernameChange,
    this.completionRate = 0.0,
    this.totalComments = 0,
    this.averageRating = 0.0,
    this.trustScore = 0.0,
  });

  factory UserModel.fromMap(String uid, Map<String, dynamic> map) {
    return UserModel(
      uid: uid,
      username: map['username'],
      displayName: map['displayName'],
      email: map['email'],
      photoURL: map['photoURL'],
      phoneNumber: map['telefon'],
      profession: map['meslek'],
      address: map['adres'],
      city: map['il'],
      district: map['ilce'],
      country: map['ulke'],
      createdAt: map['createdAt'] != null
          ? (map['createdAt'] as dynamic).toDate()
          : null,
      lastLogin: map['lastLogin'] != null
          ? (map['lastLogin'] as dynamic).toDate()
          : null,
      lastUsernameChange: map['lastUsernameChange'] != null
          ? (map['lastUsernameChange'] as dynamic).toDate()
          : null,
      completionRate: (map['completionRate'] ?? 0.0).toDouble(),
      totalComments:  (map['toplam_yorum']  as int?) ?? 0,
      averageRating:  (map['ortalama_puan'] as num?)?.toDouble() ?? 0.0,
      trustScore:     (map['guven_skoru']   as num?)?.toDouble() ?? 0.0,
    );
  }

  Map<String, dynamic> toMap() {
    return {
      'username': username,
      'displayName': displayName,
      'email': email,
      'photoURL': photoURL,
      'telefon': phoneNumber,
      'meslek': profession,
      'adres': address,
      'il': city,
      'ilce': district,
      'ulke': country,
      'lastUsernameChange': lastUsernameChange,
      'completionRate': completionRate,
    };
  }

  UserModel copyWith({
    String? username,
    String? displayName,
    String? email,
    String? photoURL,
    String? phoneNumber,
    String? profession,
    String? address,
    String? city,
    String? district,
    String? country,
    DateTime? lastUsernameChange,
    double? completionRate,
    int? totalComments,
    double? averageRating,
    double? trustScore,
  }) {
    return UserModel(
      uid: uid,
      username: username ?? this.username,
      displayName: displayName ?? this.displayName,
      email: email ?? this.email,
      photoURL: photoURL ?? this.photoURL,
      phoneNumber: phoneNumber ?? this.phoneNumber,
      profession: profession ?? this.profession,
      address: address ?? this.address,
      city: city ?? this.city,
      district: district ?? this.district,
      country: country ?? this.country,
      createdAt: createdAt,
      lastLogin: lastLogin,
      lastUsernameChange: lastUsernameChange ?? this.lastUsernameChange,
      completionRate: completionRate ?? this.completionRate,
      totalComments:  totalComments  ?? this.totalComments,
      averageRating:  averageRating  ?? this.averageRating,
      trustScore:     trustScore     ?? this.trustScore,
    );
  }
}
