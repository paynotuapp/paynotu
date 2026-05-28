"""
KAP Tedbir Karari PDF parser.

Reads all PDFs from C:/pay/tedbir_karar/ and extracts:
- Bildirim ID
- Yayınlanma tarihi
- İlgili ticker(lar)
- Tedbir tipi (GEÇICI_6AY / KESIN_2YIL)
- İşlem başlangıç tarihi (varsa)
- SPK bülten numarası
- Karar metni (raw)

Output:
- backend/spk_belgeleri/vakalar_kap.csv (kalibrasyon için)
- backend/spk_belgeleri/tedbirler_meta.json (tam metadata, bildirim sayfası için)
"""
import re
import csv
import json
from pathlib import Path
from datetime import datetime, timedelta
from collections import Counter, OrderedDict

import pdfplumber


# Konfigürasyon
PDF_DIR = Path("C:/pay/tedbir_karar")
SPK_DIR = Path(__file__).resolve().parent.parent.parent / "spk_belgeleri"
OUTPUT_CSV = SPK_DIR / "vakalar_kap.csv"
OUTPUT_JSON = SPK_DIR / "tedbirler_meta.json"

PRE_KARAR_DAYS = 90
GAP_DAYS = 1

PATTERNS = {
    "bildirim_id": re.compile(r'Bildirim/(\d+)'),
    "sirketler": re.compile(r'İlgili Şirketler\s*\[([^\]]*)\]'),
    "bulten": re.compile(r'(\d{4}/\d{1,3})\s+sayılı SPK'),
    "islem_bas": re.compile(r'(\d{2}\.\d{2}\.\d{4})\s+tarihli işlemlerden başlamak üzere'),
}

TEDBIR_TIPLERI = {
    "GEÇICI_6AY": [
        "6 ay süreyle geçici işlem yasağı",
        "6 ay geçici işlem yapma yasağı",
        "6 ay süreli geçici işlem",
    ],
    "KESIN_2YIL": [
        "2 yıl işlem yapma yasağı",
        "2 yıl süreli işlem yapma",
        "2 yıllığına borsalarda işlem",
        "2 yıllık süreden",
    ],
}


def parse_tarih(tarih_str):
    try:
        return datetime.strptime(tarih_str, "%d.%m.%Y").date()
    except (ValueError, TypeError):
        return None


def detect_tedbir_tipi(blok_metin):
    for tipi, kelimeler in TEDBIR_TIPLERI.items():
        for k in kelimeler:
            if k in blok_metin:
                return tipi
    return "BILINMIYOR"


def parse_blok(blok_metin):
    result = {
        "bildirim_id": None,
        "yayinlanma_tarihi": None,
        "tickers": [],
        "tedbir_tipi": "BILINMIYOR",
        "islem_bas_tarihi": None,
        "spk_bulten": None,
        "raw_text_excerpt": blok_metin[:500].strip(),
    }

    m = PATTERNS["bildirim_id"].search(blok_metin)
    if m:
        result["bildirim_id"] = m.group(1)

    m = re.search(r"^\s*(\d{2}\.\d{2}\.\d{4})", blok_metin)
    if m:
        result["yayinlanma_tarihi"] = m.group(1)

    m = PATTERNS["sirketler"].search(blok_metin)
    if m:
        sirket_str = m.group(1).strip()
        if sirket_str:
            result["tickers"] = [t.strip() for t in sirket_str.split(",") if t.strip()]

    m = PATTERNS["bulten"].search(blok_metin)
    if m:
        result["spk_bulten"] = m.group(1)

    m = PATTERNS["islem_bas"].search(blok_metin)
    if m:
        result["islem_bas_tarihi"] = m.group(1)

    result["tedbir_tipi"] = detect_tedbir_tipi(blok_metin)
    return result


def parse_pdf_new_format(full_text, pdf_path):
    """Yeni format (2022+): 'KAP'ta yayınlanma tarihi ve saati:' ayracı."""
    bloklar = re.split(r"KAP’ta yayınlanma tarihi ve saati:|KAP'ta yayınlanma tarihi ve saati:", full_text)
    tedbirler = []
    for i, blok in enumerate(bloklar[1:], 1):
        parsed = parse_blok(blok)
        parsed["pdf_kaynak"] = pdf_path.name
        parsed["blok_no"] = i
        parsed["format"] = "new"
        tedbirler.append(parsed)
    return tedbirler


def parse_pdf_old_format(full_text, pdf_path):
    """Eski format (2019-2021): 'İlgili Şirketler [' ayracı, tarih blok içinde."""
    chunks = re.split(r"İlgili Şirketler\s*\[", full_text)
    tedbirler = []
    for i, chunk in enumerate(chunks[1:], 1):
        m_ticker = re.match(r"([^\]]*)\]", chunk)
        tickers = []
        if m_ticker:
            raw = m_ticker.group(1).strip()
            if raw:
                tickers = [t.strip() for t in raw.split(",") if t.strip()]

        dates_in_block = re.findall(r"\b(\d{2}\.\d{2}\.\d{4})\b", chunk)
        yayinlanma = dates_in_block[0] if dates_in_block else None

        m_bulten = PATTERNS["bulten"].search(chunk)
        m_bulten_old = re.search(r"Karar\s+(\d{4}/\d{1,3})\s+sayılı", chunk)
        m_islem = PATTERNS["islem_bas"].search(chunk)

        result = {
            "bildirim_id": None,
            "yayinlanma_tarihi": yayinlanma,
            "tickers": tickers,
            "tedbir_tipi": detect_tedbir_tipi(chunk),
            "islem_bas_tarihi": m_islem.group(1) if m_islem else None,
            "spk_bulten": (m_bulten.group(1) if m_bulten else None)
                          or (m_bulten_old.group(1) if m_bulten_old else None),
            "raw_text_excerpt": chunk[:500].strip(),
            "pdf_kaynak": pdf_path.name,
            "blok_no": i,
            "format": "old",
        }
        tedbirler.append(result)
    return tedbirler


def parse_pdf(pdf_path):
    """Tek bir PDF'i parse et; format otomatik algılanır."""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            full_text = "\n".join(p.extract_text() or "" for p in pdf.pages)
    except Exception as e:
        print(f"  ✗ PDF okuma hatası: {e}")
        return []

    if "KAP" in full_text and "yayınlanma tarihi ve saati:" in full_text:
        return parse_pdf_new_format(full_text, pdf_path)
    else:
        return parse_pdf_old_format(full_text, pdf_path)


def main():
    print("=" * 70)
    print("KAP Tedbir Kararı PDF Parser")
    print("=" * 70)

    if not PDF_DIR.exists():
        print(f"\n✗ Klasör bulunamadı: {PDF_DIR}")
        return

    pdf_files = sorted(PDF_DIR.glob("*.pdf"))
    print(f"\nPDF sayısı: {len(pdf_files)}")

    if not pdf_files:
        print(f"✗ {PDF_DIR} altında PDF yok")
        return

    all_tedbirler = []

    for i, pdf_path in enumerate(pdf_files, 1):
        print(f"\n[{i}/{len(pdf_files)}] {pdf_path.name}")
        tedbirler = parse_pdf(pdf_path)
        print(f"  → {len(tedbirler)} tedbir bloğu")

        no_ticker = [t for t in tedbirler if not t["tickers"]]
        if no_ticker:
            print(f"  ⚠ Ticker'sız {len(no_ticker)} blok")

        all_tedbirler.extend(tedbirler)

    print(f"\n{'=' * 70}")
    print(f"Toplam tedbir bloğu: {len(all_tedbirler)}")

    with_ticker = [t for t in all_tedbirler if t["tickers"]]
    print(f"Ticker'lı blok: {len(with_ticker)}")

    tipi_dist = Counter(t["tedbir_tipi"] for t in with_ticker)
    print(f"\nTedbir tipi dağılımı:")
    for tipi, cnt in tipi_dist.most_common():
        print(f"  {tipi}: {cnt}")

    all_tickers = []
    for t in with_ticker:
        all_tickers.extend(t["tickers"])
    unique_tickers = sorted(set(all_tickers))
    print(f"\nUnique ticker: {len(unique_tickers)}")

    ticker_freq = Counter(all_tickers)
    print(f"En sık ticker (top 15):")
    for tk, cnt in ticker_freq.most_common(15):
        print(f"  {tk}: {cnt}")

    # BILINMIYOR oranı uyarısı
    bilinmiyor_cnt = tipi_dist.get("BILINMIYOR", 0)
    if with_ticker and bilinmiyor_cnt / len(with_ticker) > 0.20:
        print(f"\n⚠ UYARI: BILINMIYOR oranı %{bilinmiyor_cnt/len(with_ticker)*100:.1f} — format varyasyonu olabilir")

    # CSV üret
    csv_rows = []
    for t in with_ticker:
        karar_tarihi = parse_tarih(t["yayinlanma_tarihi"])
        if not karar_tarihi:
            continue
        baslangic = (karar_tarihi - timedelta(days=PRE_KARAR_DAYS)).strftime("%Y-%m-%d")
        bitis = (karar_tarihi - timedelta(days=GAP_DAYS)).strftime("%Y-%m-%d")
        for ticker in t["tickers"]:
            csv_rows.append({
                "ticker": ticker,
                "baslangic": baslangic,
                "bitis": bitis,
                "source": "kap_tedbir",
                "referans": t["bildirim_id"] or t["spk_bulten"] or "",
                "tedbir_tipi": t["tedbir_tipi"],
            })

    print(f"\n→ CSV satır (multi-ticker açılmış): {len(csv_rows)}")

    seen = OrderedDict()
    for r in csv_rows:
        key = (r["ticker"], r["baslangic"], r["bitis"])
        if key not in seen:
            seen[key] = r
    csv_rows_dedup = list(seen.values())
    print(f"→ Dedup sonrası: {len(csv_rows_dedup)} satır")

    SPK_DIR.mkdir(exist_ok=True)
    with OUTPUT_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["ticker", "baslangic", "bitis", "source", "referans", "tedbir_tipi"],
        )
        writer.writeheader()
        writer.writerows(csv_rows_dedup)
    print(f"\n✓ Yazıldı: {OUTPUT_CSV}")

    json_data = {
        "meta": {
            "generated_at": datetime.now().isoformat(),
            "n_pdfs": len(pdf_files),
            "n_tedbir_bloklari": len(all_tedbirler),
            "n_with_ticker": len(with_ticker),
            "n_unique_tickers": len(unique_tickers),
            "tedbir_tipi_distribution": dict(tipi_dist),
        },
        "tedbirler": with_ticker,
    }
    with OUTPUT_JSON.open("w", encoding="utf-8") as f:
        json.dump(json_data, f, indent=2, ensure_ascii=False)
    print(f"✓ Yazıldı: {OUTPUT_JSON}")

    print(f"\n=== Tarih Aralığı ===")
    tarihler = [parse_tarih(t["yayinlanma_tarihi"]) for t in with_ticker if t["yayinlanma_tarihi"]]
    tarihler = [t for t in tarihler if t]
    if tarihler:
        print(f"  En eski: {min(tarihler)}")
        print(f"  En yeni: {max(tarihler)}")

    yil_dist = Counter(t.year for t in tarihler)
    print(f"\nYıl bazlı dağılım:")
    for yil in sorted(yil_dist.keys()):
        print(f"  {yil}: {yil_dist[yil]} tedbir")


if __name__ == "__main__":
    main()
