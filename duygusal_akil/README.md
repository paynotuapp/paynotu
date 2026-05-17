# Duygusal Akıl v1 — Kurulum ve Kullanım

## Proje Yapısı

```
duygusal_akil/
├── main.py                        → FastAPI ana uygulama
├── requirements.txt               → Python bağımlılıkları
├── duygusal_akil_service.dart     → Flutter entegrasyon servisi
└── motor/
    ├── __init__.py
    ├── nlp_katmani.py             → Türkçe NLP (BERT)
    ├── anomali_tespiti.py         → Z-score anomali
    ├── fuzzy_motor.py             → Geçmiş güven skoru
    ├── bayesian_motor.py          → Canlı itibar skoru
    ├── zaman_agirlik.py           → Zaman ağırlıklı skor
    ├── icerik_kalkani.py          → Gerçek zamanlı içerik kalkanı
    └── hakem.py                   → Ensemble / çatışma çözümü
```

---

## Kurulum

```bash
# 1. Klasöre gir
cd duygusal_akil

# 2. Sanal ortam oluştur
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. Bağımlılıkları yükle
pip install -r requirements.txt

# 4. Çalıştır
uvicorn main:app --reload --port 8000
```

Tarayıcıda aç: http://localhost:8000/docs

---

## API Endpointleri

### İçerik Kontrolü (Gerçek zamanlı)
```
POST /icerik-kontrol
Body: { "metin": "yorum metni" }
```

### Yorum Skorlama
```
POST /yorumu-skorla
Body: {
  "yorum_metni": "...",
  "puan": 4.0,
  "kullanici_id": "uid_123",
  "hesap_yas_gun": 180,
  "toplam_yorum_sayisi": 12,
  "yorum_cesitliligi": 0.6,
  "yorum_timestamp": 1714000000,
  "faydali_oy": 8,
  "faydali_olmayan_oy": 1,
  "hisse_kodu": "THYAO"
}
```

---

## Flutter Entegrasyonu

### 1. Servis dosyasını kopyala
`duygusal_akil_service.dart` → `lib/services/` klasörüne kopyala

### 2. http paketi ekle (pubspec.yaml)
```yaml
dependencies:
  http: ^1.2.0
```

### 3. İçerik kalkanını TextField'a bağla
```dart
TextField(
  onChanged: (metin) async {
    if (metin.length > 5) {
      final sonuc = await DuygusalAkilService.icerikKontrol(metin);
      setState(() {
        _gonderButonuAktif = sonuc.gonderilebildi;
        _uyariMesaji = sonuc.durum == 'engellendi' ? sonuc.aciklama : null;
      });
    }
  },
)
```

### 4. Yorum gönderiminde skoru hesapla
```dart
onPressed: () async {
  try {
    final skor = await DuygusalAkilService.yorumuSkorla(
      yorumMetni: _yorumController.text,
      puan: _secilenPuan,
      kullaniciId: FirebaseAuth.instance.currentUser!.uid,
      hesapYasGun: _kullaniciProfilinden(),
      // ... diğer parametreler
    );

    if (skor != null) {
      // Firebase'e kaydet + skoru göster
      await _yorumuFirestoreKaydet(skor);
    }
  } catch (e) {
    // İçerik engellendi mesajını göster
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(e.toString())),
    );
  }
}
```

---

## Railway'e Deploy

```bash
# 1. GitHub'a push et
git init
git add .
git commit -m "Duygusal Akıl v1"
git push origin main

# 2. railway.app'te yeni proje oluştur
# 3. GitHub repo'yu bağla
# 4. Deploy — otomatik başlar
```

---

## Notlar

- İlk çalıştırmada BERT modeli indirilir (~500MB), sabır gerekir
- BERT yoksa sistem otomatik kural tabanlı moda geçer
- Production'da Redis kullanımı önerilir (anomali tespiti için)
- `_baseUrl` değişkenini Railway URL'i ile güncelle
