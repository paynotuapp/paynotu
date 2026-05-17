"""
Fintables symbols.js -> Firestore name + islem_saati guncelleme
- name        : Fintables title field'i (guncel sirket adi)
- islem_saati : session field'i "0955-1810" -> "09:55 - 18:10"
"""

import re
import json
import cloudscraper
import firebase_admin
from firebase_admin import credentials, firestore

# ── Firebase ──────────────────────────────────────────────────────────────────
cred = credentials.Certificate('pay-defteri-firebase-adminsdk-fbsvc-58f68bd69c.json')
firebase_admin.initialize_app(cred)
db = firestore.client()

# ── 1. Fintables fetch + parse ────────────────────────────────────────────────
print('Fintables verisi cekiliyor...', flush=True)
scraper = cloudscraper.create_scraper()
r = scraper.get('https://api.fintables.com/symbols.js/', timeout=30)
r.raise_for_status()
text = r.text
print(f'  Indirilen: {len(text):,} karakter')

es_val = re.search(r'const es\s*=\s*"([^"]+)"', text).group(1)

mgmt_start = text.index('const mgmt = ') + len('const mgmt = ')
mgmt_raw   = text[mgmt_start : text.index('const uwl = ')].strip().rstrip(';')
mgmt: dict = json.loads(mgmt_raw)

uwl_start = text.index('const uwl = ') + len('const uwl = ')
uwl_raw   = text[uwl_start : text.index('window.symbols', uwl_start)].strip().rstrip(';')
uwl: dict = json.loads(uwl_raw)

sym_start = text.index('window.symbols = ') + len('window.symbols = ')
sym_raw   = text[sym_start:].rstrip().rstrip(';')

ef_json = '{"decimals": 2, "thousand": true}'
ff_json = '{"decimals": 6, "thousand": true}'

sym_fixed = sym_raw
for var, val in [('ef', ef_json), ('ff', ff_json), ('es', f'"{es_val}"')]:
    sym_fixed = sym_fixed.replace(f': {var},', f': {val},').replace(f': {var}}}', f': {val}}}')

def _sub(d: dict, m: re.Match) -> str:
    v = d.get(m.group(1))
    return 'null' if v is None else '"' + v + '"'

sym_fixed = re.sub(r"mgmt\['([^']+)'\]", lambda m: _sub(mgmt, m), sym_fixed)
sym_fixed = re.sub(r"uwl\['([^']+)'\]",  lambda m: _sub(uwl,  m), sym_fixed)

symbols: dict = json.loads(sym_fixed)

equities: dict[str, dict] = {
    k: v for k, v in symbols.items()
    if isinstance(v, dict) and v.get('type') == 'equity'
}
print(f'  Equity hisse sayisi: {len(equities):,}')

# ── 2. Session formatlayici ───────────────────────────────────────────────────
def fmt_session(raw: str | None) -> str | None:
    """'0955-1810' -> '09:55 - 18:10'. None veya beklenmeyen formatta None doner."""
    if not raw:
        return None
    m = re.fullmatch(r'(\d{4})-(\d{4})', raw.strip())
    if not m:
        return None
    def ins(t: str) -> str:          # '0955' -> '09:55'
        return t[:2] + ':' + t[2:]
    return ins(m.group(1)) + ' - ' + ins(m.group(2))

# ── 3. Firestore hisselerini cek ──────────────────────────────────────────────
print('\nFirestore\'dan mevcut hisseler cekiliyor...')
fs_docs: dict[str, dict] = {
    doc.id: (doc.to_dict() or {})
    for doc in db.collection('hisseler').stream()
}
print(f'  Firestore\'da: {len(fs_docs):,} hisse')

# ── 4. Guncelleme ────────────────────────────────────────────────────────────
BATCH_SIZE = 400
guncellenen_name    = 0
guncellenen_session = 0
eslesmedi           = 0

batch     = db.batch()
batch_cnt = 0

def commit():
    global batch, batch_cnt
    if batch_cnt:
        batch.commit()
        batch     = db.batch()
        batch_cnt = 0

print('\nGuncelleniyor...')
for symbol, fs_data in fs_docs.items():
    eq = equities.get(symbol)
    if eq is None:
        eslesmedi += 1
        continue

    updates: dict = {}

    # name
    title = eq.get('title', '').strip()
    if title:
        updates['name'] = title
        guncellenen_name += 1

    # islem_saati — session field'i equity'de yoksa es_val kullan
    session_raw = eq.get('session') or es_val
    saati = fmt_session(session_raw)
    if saati:
        updates['islem_saati'] = saati
        guncellenen_session += 1

    if not updates:
        continue

    batch.update(db.collection('hisseler').document(symbol), updates)
    batch_cnt += 1

    if batch_cnt >= BATCH_SIZE:
        commit()
        print(f'  {guncellenen_name} isim, {guncellenen_session} saat yazildi...', flush=True)

commit()

# ── 5. Rapor ─────────────────────────────────────────────────────────────────
print('\n' + '='*48)
print('=== SONUC RAPORU ===')
print('='*48)
print(f'  Firestore toplam hisse        : {len(fs_docs):>6,}')
print(f'  Fintables\'ta eslesen          : {len(fs_docs) - eslesmedi:>6,}')
print(f'  Fintables\'ta eslesmeyen       : {eslesmedi:>6,}')
print(f'  -----------------------------------------')
print(f'  name guncellenen              : {guncellenen_name:>6,}')
print(f'  islem_saati guncellenen       : {guncellenen_session:>6,}')
print('='*48)
print('Tamamlandi.')
