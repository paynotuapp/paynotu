# -*- coding: utf-8 -*-
"""
PayNotu — Sektör Haritasını Firestore'a Yaz
============================================
Kullanım:
  python scripts/write_sector_map_to_firestore.py --dry-run   (varsayılan)
  python scripts/write_sector_map_to_firestore.py --commit    (gerçek yazım)

Güvenlik kuralları:
  - hisseler/{symbol} için yalnızca update() kullanılır.
  - Mevcut olmayan hisse dokümanı OLUŞTURULMAZ.
  - paynotu_skoru, anomali_skoru, finansal_skor, topsis_score,
    has_paynotu alanlarına kesinlikle dokunulmaz.
  - sector_map/{symbol} için set(..., merge=True) kullanılabilir.
  - system_config/sector_map_meta için set(..., merge=True) kullanılabilir.
"""

from __future__ import annotations
import argparse, json, os, sys, time
from typing import Any

# Build_sector_routing modülünü import et
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_SCRIPTS_DIR)
sys.path.insert(0, _BACKEND_DIR)
sys.path.insert(0, _SCRIPTS_DIR)

from scripts.build_sector_routing import build_routing, normalize_tr

# ── Korunan alanlar (HİÇBİR KOŞULDA dokunulmasın) ────────────────────────────
PROTECTED_FIELDS = {
    "paynotu_skoru",
    "anomali_skoru",
    "finansal_skor",
    "topsis_score",
    "has_paynotu",
    "yorum",
    "fiyat",
    "gunluk_degisim",
    "hacim",
    "piyasa_degeri",
}

VERSION = "kap_sektor_map_2026_05"

# ── Firestore payload builder ──────────────────────────────────────────────────

def _build_hisse_payload(row: dict) -> dict:
    """hisseler/{symbol} için update payload."""
    payload = {
        "kap_ana_sektor":             row["kap_ana_sektor"],
        "kap_alt_sektor":             row["kap_alt_sektor"],
        "paynotu_sector_group":       row["paynotu_sector_group"],
        "financial_model":            row["financial_model"],
        "sector_profile":             row["sector_profile"],
        "primary_source":             row["primary_source"],
        "fallback_sources":           row.get("fallback_sources", []),
        "sector_source":              "KAP",
        "sector_source_file":         "sektorler.pdf",
        "sector_source_version":      VERSION,
        "sector_verified":            True,
        "manual_review_required":     row["manual_review_required"],
        "sector_routing_note":        row.get("routing_note", ""),
        "financial_source_priority":  row.get("financial_source_priority", []),
    }
    # Güvenlik: korunan alan yoksa yazma
    for pf in PROTECTED_FIELDS:
        if pf in payload:
            raise RuntimeError(f"KORUMA İHLALİ: {pf} payload'a girdi!")
    return payload


def _build_sector_map_payload(row: dict) -> dict:
    """sector_map/{symbol} için tam kayıt."""
    return {
        "symbol":                    row["symbol"],
        "company_name":              row["company_name"],
        "kap_ana_sektor":            row["kap_ana_sektor"],
        "kap_alt_sektor":            row["kap_alt_sektor"],
        "paynotu_sector_group":      row["paynotu_sector_group"],
        "financial_model":           row["financial_model"],
        "sector_profile":            row["sector_profile"],
        "primary_source":            row["primary_source"],
        "fallback_sources":          row.get("fallback_sources", []),
        "financial_source_priority": row.get("financial_source_priority", []),
        "sector_source":             "KAP",
        "sector_source_version":     VERSION,
        "sector_verified":           True,
        "manual_review_required":    row["manual_review_required"],
        "routing_note":              row.get("routing_note", ""),
        "match_level":               row.get("match_level", ""),
    }


# ── Firestore bağlantısı ───────────────────────────────────────────────────────

def _get_db():
    """Firebase Admin SDK ile Firestore client döndür."""
    from dotenv import load_dotenv
    load_dotenv()
    import firebase_admin
    from firebase_admin import credentials, firestore as fb_firestore
    import base64, json as _json

    if not firebase_admin._apps:
        cred_b64 = (os.getenv("FIREBASE_CREDENTIALS_BASE64") or
                    os.getenv("FIREBASE_CREDENTIALS_JSON"))
        if cred_b64:
            cred_b64 += "=" * (-len(cred_b64) % 4)
            cred_dict = _json.loads(base64.b64decode(cred_b64).decode())
            cred = credentials.Certificate(cred_dict)
        else:
            cred_path = os.path.join(
                _BACKEND_DIR,
                "pay-defteri-firebase-adminsdk-fbsvc-58f68bd69c.json",
            )
            cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
    return fb_firestore.client()


# ── Dry-run: Firestore doküman kontrolü ───────────────────────────────────────

def run_dry_run(rows: list[dict], stats: dict) -> dict:
    """Firestore'a yazmadan rapor üretir."""
    print("\n" + "="*60)
    print("DRY-RUN MODU — Firestore'a yazım yapılmayacak")
    print("="*60)

    db = _get_db()
    hisseler_col = db.collection("hisseler")

    existing_docs:  list[str] = []
    missing_docs:   list[str] = []
    unknown_rows:   list[dict] = []
    manual_review:  list[str] = []

    BATCH_SIZE = 30
    all_symbols = [r["symbol"] for r in rows if r["symbol"]]

    print(f"\nFirestore doküman kontrolü ({len(all_symbols)} sembol)...")
    for i in range(0, len(all_symbols), BATCH_SIZE):
        batch_syms = all_symbols[i:i+BATCH_SIZE]
        for sym in batch_syms:
            doc = hisseler_col.document(sym).get()
            if doc.exists:
                existing_docs.append(sym)
            else:
                missing_docs.append(sym)
        # Rate limit önlemi
        if i + BATCH_SIZE < len(all_symbols):
            time.sleep(0.5)

    sym_map = {r["symbol"]: r for r in rows}
    for r in rows:
        if r["paynotu_sector_group"] == "unknown":
            unknown_rows.append(r)
        if r["manual_review_required"]:
            manual_review.append(r["symbol"])

    # Duplicate
    seen = {}
    duplicates = []
    for r in rows:
        s = r["symbol"]
        if s in seen:
            duplicates.append(s)
        seen[s] = True

    print(f"\nDRY-RUN ÖZETİ:")
    print(f"  CSV satiri:                    {stats['total_csv']}")
    print(f"  Duplicate symbol:              {len(duplicates)}")
    print(f"  Bos symbol:                    {stats['empty_symbol']}")
    print(f"  Bos main_sector:               {stats['empty_main_sector']}")
    print(f"  Bos sub_sector:                {stats['empty_sub_sector']}")
    print(f"  Unknown sector_group:          {stats['unknown_sector_group']}")
    print(f"  Manual review gereken:         {len(manual_review)}")
    print(f"  Firestore'da bulunan:          {len(existing_docs)}")
    print(f"  Firestore'da bulunamayan:      {len(missing_docs)}")

    print(f"\nGROUP DAĞILIMI:")
    for g, c in sorted(stats["by_group"].items()):
        print(f"  {g:35s} {c}")

    # financial_special alt profil kırılımı
    fs_rows = [r for r in rows if r["paynotu_sector_group"] == "financial_special"]
    if fs_rows:
        print(f"\nFINANCIAL_SPECIAL ALT PROFİL DAĞILIMI ({len(fs_rows)} sembol):")
        profiles: dict[str, list] = {}
        for r in fs_rows:
            p = r.get("sector_profile", "?")
            profiles.setdefault(p, []).append(r["symbol"])
        for p, syms in sorted(profiles.items()):
            print(f"  {p:30s} {len(syms):3d}  {syms[:8]}")

        # primary_source kırılımı
        print(f"\n  primary_source dağılımı:")
        ps_map: dict[str, list] = {}
        for r in fs_rows:
            ps = r.get("primary_source", "?")
            ps_map.setdefault(ps, []).append(r["symbol"])
        for ps, syms in sorted(ps_map.items()):
            print(f"    {ps:30s} {len(syms):3d}  {syms[:6]}")

        # Kontrol sembolleri
        fs_checks = [
            "A1CAP","GEDIK","ISMEN","INFO","TERA","GLBMD","SKYMD",
            "SMRVA","BRKVY","GLCVY","GARFA","VAKFA","VAKFN","ISFIN","KTLEV",
        ]
        print(f"\n  Kontrol sembolleri:")
        for sym in fs_checks:
            r = sym_map.get(sym)
            if r:
                print(f"    {sym:8s} profile={r.get('sector_profile','?'):30s} "
                      f"primary={r.get('primary_source','?')}")
            else:
                print(f"    {sym:8s} CSV'de yok")

    if missing_docs:
        print(f"\nFirestore'da bulunamayan semboller ({len(missing_docs)}):")
        for s in missing_docs[:30]:
            print(f"  {s}")
        if len(missing_docs) > 30:
            print(f"  ... ve {len(missing_docs)-30} daha")

    if unknown_rows:
        print(f"\nUnknown sektör grubu ({len(unknown_rows)}):")
        for r in unknown_rows[:10]:
            print(f"  {r['symbol']:10s}  {r['kap_ana_sektor']} / {r['kap_alt_sektor']}")

    if duplicates:
        print(f"\nDuplicate semboller: {duplicates}")

    # Örnek payload
    print(f"\nÖRNEK PAYLOAD (AKBNK):")
    akbnk = sym_map.get("AKBNK")
    if akbnk:
        payload = _build_hisse_payload(akbnk)
        for k, v in payload.items():
            print(f"  {k}: {v}")

    print(f"\nDRY RUN: Firestore'a yazim yapilmadi.")

    return {
        "existing_docs":    existing_docs,
        "missing_docs":     missing_docs,
        "unknown_rows":     unknown_rows,
        "manual_review":    manual_review,
        "duplicates":       duplicates,
    }


# ── Commit: gerçek yazım ───────────────────────────────────────────────────────

def run_commit(rows: list[dict], stats: dict, dry_run_result: dict) -> dict:
    """Firestore'a sektör verilerini yazar."""
    print("\n" + "="*60)
    print("COMMIT MODU — Firestore'a yazım başlıyor")
    print("="*60)

    from google.cloud import firestore as gc_firestore
    db = _get_db()

    hisseler_col   = db.collection("hisseler")
    sector_map_col = db.collection("sector_map")
    system_cfg_col = db.collection("system_config")

    existing_set = set(dry_run_result["existing_docs"])

    updated_hisse     = 0
    updated_sector_map = 0
    skipped_missing   = 0
    errors            = []

    BATCH_SIZE = 400   # Firestore batch limit 500
    batch_hisse      = db.batch()
    batch_sector_map = db.batch()
    hisse_batch_count = 0
    sm_batch_count    = 0

    def _flush_hisse():
        nonlocal hisse_batch_count
        if hisse_batch_count > 0:
            batch_hisse.commit()
            hisse_batch_count = 0

    def _flush_sm():
        nonlocal sm_batch_count
        if sm_batch_count > 0:
            batch_sector_map.commit()
            sm_batch_count = 0

    for row in rows:
        symbol = row["symbol"]
        if not symbol:
            continue

        # sector_map → her sembol için yaz (doküman yoksa oluştur)
        try:
            sm_ref = sector_map_col.document(symbol)
            sm_payload = _build_sector_map_payload(row)
            sm_payload["updated_at"] = gc_firestore.SERVER_TIMESTAMP
            batch_sector_map.set(sm_ref, sm_payload, merge=True)
            sm_batch_count += 1
            updated_sector_map += 1
            if sm_batch_count >= BATCH_SIZE:
                _flush_sm()
        except Exception as e:
            errors.append(f"sector_map/{symbol}: {e}")

        # hisseler → sadece mevcut dokümanlar için update
        if symbol in existing_set:
            try:
                h_ref = hisseler_col.document(symbol)
                payload = _build_hisse_payload(row)
                payload["sector_updated_at"] = gc_firestore.SERVER_TIMESTAMP
                batch_hisse.update(h_ref, payload)
                hisse_batch_count += 1
                updated_hisse += 1
                if hisse_batch_count >= BATCH_SIZE:
                    _flush_hisse()
            except Exception as e:
                errors.append(f"hisseler/{symbol}: {e}")
        else:
            skipped_missing += 1

    # Kalan batch'leri flush et
    _flush_hisse()
    _flush_sm()

    # Meta dokümanı güncelle
    meta_ref = system_cfg_col.document("sector_map_meta")
    meta_payload = {
        "source":                       "KAP",
        "source_file":                  "sektorler.pdf",
        "source_csv":                   "data/kap_sektor_map.csv",
        "version":                      VERSION,
        "total_rows":                   stats["total_csv"],
        "mapped_rows":                  stats["total_csv"] - stats["unknown_sector_group"],
        "unknown_count":                stats["unknown_sector_group"],
        "manual_review_count":          len(dry_run_result["manual_review"]),
        "missing_firestore_docs_count": len(dry_run_result["missing_docs"]),
        "updated_hisse_count":          updated_hisse,
        "updated_sector_map_count":     updated_sector_map,
        "updated_at":                   gc_firestore.SERVER_TIMESTAMP,
    }
    system_cfg_col.document("sector_map_meta").set(meta_payload, merge=True)

    print(f"  update edilen hisseler:   {updated_hisse}")
    print(f"  sector_map yazilan:       {updated_sector_map}")
    print(f"  atlanan (eksik doc):      {skipped_missing}")
    print(f"  meta guncellendi:         evet")
    if errors:
        print(f"  HATALAR ({len(errors)}):")
        for e in errors[:10]:
            print(f"    {e}")

    return {
        "updated_hisse":      updated_hisse,
        "updated_sector_map": updated_sector_map,
        "skipped_missing":    skipped_missing,
        "errors":             errors,
    }


# ── Doğrulama: commit sonrası kontrol ─────────────────────────────────────────

def run_verification(symbols: list[str]) -> None:
    """Commit sonrası Firestore'dan okuyup raporlar."""
    print(f"\n{'='*60}")
    print("DOĞRULAMA — Firestore'dan okuma")
    print("="*60)

    db = _get_db()
    hisseler_col = db.collection("hisseler")

    VERIFY_FIELDS = [
        "kap_alt_sektor", "paynotu_sector_group",
        "financial_model", "sector_profile",
        "primary_source", "fallback_sources", "financial_source_priority",
        "manual_review_required",
    ]

    for sym in symbols:
        doc = hisseler_col.document(sym).get()
        if not doc.exists:
            print(f"  {sym:10s} DOC BULUNAMADI")
            continue
        data = doc.to_dict()
        print(f"\n  {sym}:")
        for f in VERIFY_FIELDS:
            print(f"    {f}: {data.get(f, 'N/A')}")


# ── Ana akış ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="KAP sektör haritasını Firestore'a yaz."
    )
    parser.add_argument("--dry-run",  action="store_true", default=True,
                        help="Sadece rapor üret (varsayılan)")
    parser.add_argument("--commit",   action="store_true", default=False,
                        help="Firestore'a yaz")
    parser.add_argument("--yes",      action="store_true", default=False,
                        help="Onay promptunu atla (script/CI kullanımı için)")
    parser.add_argument("--verify",   action="store_true", default=False,
                        help="Commit sonrası doğrulama oku")
    parser.add_argument("--csv", default=None,
                        help="Farklı CSV dosyası kullan")
    args = parser.parse_args()

    # Routing tablosunu oluştur
    csv_path = args.csv or os.path.join(_BACKEND_DIR, "data", "kap_sektor_map.csv")
    print(f"CSV okunuyor: {csv_path}")
    rows, stats = build_routing(csv_path)
    print(f"  {stats['total_csv']} satir okundu.")

    # Dry-run her zaman çalışır
    dry_result = run_dry_run(rows, stats)

    if not args.commit:
        print(f"\nCommit modu aktif degil. --commit ile Firestore'a yaz.")
        return

    # Commit onayı
    print(f"\nDRY-RUN temiz. Commit moduna geciliyor...")
    if not args.yes:
        confirm = input("EMIN MISIN? (evet/hayir): ").strip().lower()
        if confirm != "evet":
            print("Iptal edildi.")
            return

    commit_result = run_commit(rows, stats, dry_result)

    if args.verify:
        VERIFY_SYMBOLS = [
            "A1CAP","GEDIK","ISMEN","INFO","TERA","GLBMD","SKYMD",
            "SMRVA","BRKVY","GLCVY",
            "GARFA","VAKFA","VAKFN","ISFIN","KTLEV",
        ]
        run_verification(VERIFY_SYMBOLS)


if __name__ == "__main__":
    main()
