import firebase_admin
from firebase_admin import credentials, firestore, storage
from datetime import datetime, timezone

CREDENTIALS_PATH = r"C:\pay\pay-defteri-firebase-adminsdk-fbsvc-58f68bd69c.json"
BUCKET_NAME = "pay-defteri.firebasestorage.app"

cred = credentials.Certificate(CREDENTIALS_PATH)
firebase_admin.initialize_app(cred, {"storageBucket": BUCKET_NAME})

db = firestore.client()
bucket = storage.bucket()

pdf_files = [
    "01_Kullanim_Sartlari_KVKK_v2.pdf",
    "02_Fikri_Mulkiyet_Beyani_v2.pdf",
    "03_Topluluk_Kurallari_v2.pdf",
    "04_Hizmet_Sartlari_v2.pdf",
    "05_Gizlilik_Politikasi_v2.pdf",
]

print("Storage'dan download URL'leri alınıyor...")
urls = {}
for filename in pdf_files:
    blob = bucket.blob(filename)
    # Make the blob publicly accessible and get its public URL
    blob.make_public()
    url = blob.public_url
    urls[filename] = url
    print(f"  {filename}: {url}")

now = datetime.now(timezone.utc)

documents = {
    "kvkk": {
        "baslik": "KVKK Aydınlatma Metni",
        "versiyon": "v2.0",
        "yayinTarihi": now,
        "icerikUrl": urls["01_Kullanim_Sartlari_KVKK_v2.pdf"],
        "zorunlu": True,
        "aktif": True,
        "sira": 1,
    },
    "kullanim_sartlari": {
        "baslik": "Kullanım Şartları",
        "versiyon": "v2.0",
        "yayinTarihi": now,
        "icerikUrl": urls["01_Kullanim_Sartlari_KVKK_v2.pdf"],
        "zorunlu": True,
        "aktif": True,
        "sira": 2,
    },
    "fikri_mulkiyet": {
        "baslik": "Fikri Mülkiyet Beyanı",
        "versiyon": "v2.0",
        "yayinTarihi": now,
        "icerikUrl": urls["02_Fikri_Mulkiyet_Beyani_v2.pdf"],
        "zorunlu": True,
        "aktif": True,
        "sira": 3,
    },
    "topluluk_kurallari": {
        "baslik": "Topluluk Kuralları",
        "versiyon": "v2.0",
        "yayinTarihi": now,
        "icerikUrl": urls["03_Topluluk_Kurallari_v2.pdf"],
        "zorunlu": True,
        "aktif": True,
        "sira": 4,
    },
    "hizmet_sartlari": {
        "baslik": "Hizmet Şartları",
        "versiyon": "v2.1",
        "yayinTarihi": now,
        "icerikUrl": urls["04_Hizmet_Sartlari_v2.pdf"],
        "zorunlu": True,
        "aktif": True,
        "sira": 5,
    },
    "gizlilik_politikasi": {
        "baslik": "Gizlilik Politikası",
        "versiyon": "v2.0",
        "yayinTarihi": now,
        "icerikUrl": urls["05_Gizlilik_Politikasi_v2.pdf"],
        "zorunlu": True,
        "aktif": True,
        "sira": 6,
    },
}

print("\nFirestore'a sozlesmeler koleksiyonu yazılıyor...")
collection_ref = db.collection("sozlesmeler")
for doc_id, data in documents.items():
    collection_ref.document(doc_id).set(data)
    print(f"  Yazıldı: {doc_id} (sira={data['sira']}, baslik={data['baslik']})")

print("\nDogrulama: Firestore'daki belgeler okunuyor...")
docs = collection_ref.stream()
count = 0
for doc in docs:
    d = doc.to_dict()
    print(f"  [{doc.id}] baslik={d.get('baslik')}, versiyon={d.get('versiyon')}, sira={d.get('sira')}")
    count += 1

print(f"\nToplam {count} belge dogrulandi.")
if count == 6:
    print("BASARILI: sozlesmeler koleksiyonunda 6 belge mevcut.")
else:
    print(f"UYARI: Beklenen 6 belge yerine {count} belge bulundu.")
