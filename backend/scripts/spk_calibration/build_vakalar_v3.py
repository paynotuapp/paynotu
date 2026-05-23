"""
vakalar_v3.csv builder — 3 kaynak birleştirme.

Kaynaklar:
  1. vakalar.csv (mevcut docx parse, 2017-2024) — DD.MM.YYYY, ticker noktalı virgülle
  2. SPK IslemYasaklari API (2022-09 → 2026)
  3. vakalar_kap.csv (KAP PDFs, 2019-2026 + bazı eski)

Çıktı: vakalar_v3.csv
Dedup: (ticker, baslangic) çiftine göre, öncelik sırası: vakalar.csv > kap_tedbir > spk_api
Şüpheli vakalar (2019 öncesi KAP kaynaklı) ayrı raporlanır.
"""
import csv
import requests
import urllib3
urllib3.disable_warnings()
from datetime import datetime, timedelta
from pathlib import Path
from collections import OrderedDict, Counter


SCRIPT_DIR = Path(__file__).resolve().parent
SPK_DIR = SCRIPT_DIR.parent.parent / "spk_belgeleri"
VAKALAR_CSV = SPK_DIR / "vakalar.csv"
VAKALAR_KAP_CSV = SPK_DIR / "vakalar_kap.csv"
OUTPUT_CSV = SPK_DIR / "vakalar_v3.csv"
SUSPICIOUS_CSV = SPK_DIR / "vakalar_v3_suspicious.csv"
SPK_API = "https://ws.spk.gov.tr/IdariYaptirimlar/api/IslemYasaklari"

PRE_KARAR_DAYS = 90
GAP_DAYS = 1
SUSPICIOUS_BEFORE_YEAR = 2019


def parse_date_flexible(s):
    """DD.MM.YYYY veya YYYY-MM-DD kabul et, her zaman YYYY-MM-DD döndür."""
    s = s.strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def load_vakalar_csv():
    """vakalar.csv: dosya,ticker,baslangic,bitis,karar_tarihi
    ticker noktalı virgülle ayrılabilir, tarihler DD.MM.YYYY.
    """
    rows = []
    with VAKALAR_CSV.open(encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for r in reader:
            raw_ticker = r.get("ticker", "").strip()
            bas_raw = r.get("baslangic", "").strip()
            bit_raw = r.get("bitis", "").strip()
            dosya = r.get("dosya", "").strip()

            bas = parse_date_flexible(bas_raw)
            bit = parse_date_flexible(bit_raw)
            if not bas or not bit:
                continue

            tickers = [t.strip() for t in raw_ticker.replace(";", ",").split(",") if t.strip()]
            for ticker in tickers:
                rows.append({
                    "ticker": ticker,
                    "baslangic": bas,
                    "bitis": bit,
                    "source": "vakalar.csv",
                    "referans": dosya,
                })
    return rows


def load_vakalar_kap_csv():
    """vakalar_kap.csv: ticker,baslangic,bitis,source,referans,tedbir_tipi
    Tarihler zaten YYYY-MM-DD.
    """
    rows = []
    with VAKALAR_KAP_CSV.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            ticker = r.get("ticker", "").strip()
            bas = r.get("baslangic", "").strip()
            bit = r.get("bitis", "").strip()
            if ticker and bas and bit:
                rows.append({
                    "ticker": ticker,
                    "baslangic": bas,
                    "bitis": bit,
                    "source": "kap_tedbir",
                    "referans": r.get("referans", ""),
                })
    return rows


def fetch_spk_api():
    print(f"  → API: {SPK_API}")
    r = requests.get(SPK_API, headers={"Accept": "application/json"}, timeout=30, verify=False)
    r.raise_for_status()
    data = r.json()
    print(f"  → {len(data)} ham kayıt")

    seen = set()
    rows = []
    for d in data:
        ticker = (d.get("payKodu") or "").strip()
        karar_tarihi_iso = (d.get("kurulKararTarihi") or "").strip()
        karar_no = (d.get("kurulKararNo") or "").strip()

        if not ticker or not karar_tarihi_iso:
            continue

        key = (ticker, karar_no)
        if key in seen:
            continue
        seen.add(key)

        try:
            karar_dt = datetime.strptime(karar_tarihi_iso[:10], "%Y-%m-%d")
        except ValueError:
            continue

        baslangic = (karar_dt - timedelta(days=PRE_KARAR_DAYS)).strftime("%Y-%m-%d")
        bitis = (karar_dt - timedelta(days=GAP_DAYS)).strftime("%Y-%m-%d")

        rows.append({
            "ticker": ticker,
            "baslangic": baslangic,
            "bitis": bitis,
            "source": "spk_api",
            "referans": karar_no,
        })

    return rows


def validate(row):
    try:
        bas = datetime.strptime(row["baslangic"], "%Y-%m-%d")
        bit = datetime.strptime(row["bitis"], "%Y-%m-%d")
        if bas >= bit:
            return False, "baslangic >= bitis"
        if not row["ticker"] or len(row["ticker"]) > 10:
            return False, "invalid_ticker"
        return True, "ok"
    except ValueError as e:
        return False, f"date_parse_error: {e}"


def is_suspicious(row):
    """2019 öncesi KAP kaynaklı vakalar şüpheli (eski format tarih işlem tarihi olabilir)."""
    if row["source"] != "kap_tedbir":
        return False
    try:
        bas = datetime.strptime(row["baslangic"], "%Y-%m-%d")
        return bas.year < SUSPICIOUS_BEFORE_YEAR
    except ValueError:
        return True


def main():
    print("=" * 70)
    print("vakalar_v3.csv builder -- 3 kaynak")
    print("=" * 70)

    print("\n[1/3] vakalar.csv")
    v1 = load_vakalar_csv()
    print(f"  {len(v1)} satir (ticker genisletilmis)")

    print("\n[2/3] vakalar_kap.csv")
    v2 = load_vakalar_kap_csv()
    print(f"  {len(v2)} satir")

    print("\n[3/3] SPK IslemYasaklari API")
    v3 = fetch_spk_api()
    print(f"  {len(v3)} satir (dedup karar_no ile)")

    combined = v1 + v2 + v3
    print(f"\nToplam (dedup oncesi): {len(combined)}")

    # Validation
    valid = []
    invalid = []
    for r in combined:
        ok, reason = validate(r)
        if ok:
            valid.append(r)
        else:
            invalid.append((r, reason))

    print(f"\nValidation:")
    print(f"  Valid:   {len(valid)}")
    print(f"  Invalid: {len(invalid)}")
    if invalid:
        invalid_reasons = Counter(reason for _, reason in invalid)
        for reason, cnt in invalid_reasons.most_common():
            print(f"    {reason}: {cnt}")
        for r, reason in invalid[:5]:
            print(f"    ornek -> {r['ticker']} {r['baslangic']} ({reason})")

    # Suspicious ayir
    suspicious = [r for r in valid if is_suspicious(r)]
    clean = [r for r in valid if not is_suspicious(r)]
    print(f"\nSupheli (2019 oncesi KAP): {len(suspicious)}")
    print(f"Temiz: {len(clean)}")

    # Dedup: (ticker, baslangic) -> ilk kayit korunur
    # Oncelik: vakalar.csv > kap_tedbir > spk_api
    PRIORITY = {"vakalar.csv": 0, "kap_tedbir": 1, "spk_api": 2}

    seen_keys = OrderedDict()
    for r in sorted(clean, key=lambda x: PRIORITY.get(x["source"], 99)):
        key = (r["ticker"], r["baslangic"])
        if key not in seen_keys:
            seen_keys[key] = r

    deduped = list(seen_keys.values())
    print(f"\nDedup sonrasi: {len(deduped)} satir")

    # Kaynak dagilimi
    src_dist = Counter(r["source"] for r in deduped)
    print(f"\nKaynak dagilimi (dedup sonrasi):")
    for s, c in src_dist.most_common():
        print(f"  {s}: {c}")

    # Unique ticker
    unique_tickers = sorted(set(r["ticker"] for r in deduped))
    print(f"\nUnique ticker: {len(unique_tickers)}")

    # Yil dagilimi (baslangic)
    yil_dist = Counter()
    for r in deduped:
        try:
            yil_dist[datetime.strptime(r["baslangic"], "%Y-%m-%d").year] += 1
        except ValueError:
            pass
    print(f"\nYil dagilimi (baslangic):")
    for yil in sorted(yil_dist.keys()):
        print(f"  {yil}: {yil_dist[yil]}")

    # Yaz
    fieldnames = ["ticker", "baslangic", "bitis", "source", "referans"]

    with OUTPUT_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(deduped)
    print(f"\n[OK] Yazildi: {OUTPUT_CSV}")

    if suspicious:
        with SUSPICIOUS_CSV.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(suspicious)
        print(f"[OK] Supheli (manuel inceleme): {SUSPICIOUS_CSV} ({len(suspicious)} satir)")


if __name__ == "__main__":
    main()
