# -*- coding: utf-8 -*-
"""
PayNotu — KAP Sektör Routing Builder
=====================================
CSV'den sektör routing tablosu üretir.
Firestore'a yazmaz; sadece önizleme dosyaları üretir.

Çıktılar:
  data/kap_sector_routing_preview.csv
  data/kap_sector_routing_preview.json
"""

from __future__ import annotations
import csv, json, os, re
from typing import Optional

# ── Normalize helper ──────────────────────────────────────────────────────────

def normalize_tr(value) -> str:
    """Türkçe karakterleri ASCII'ye çevir, uppercase ve strip.

    None-safe. Satır sonlarını ve fazla boşlukları tek boşlukla değiştirir.
    """
    if value is None:
        return ""
    text = str(value).strip()
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    tr_map = {
        "İ": "I", "ı": "I", "Ş": "S", "ş": "S",
        "Ğ": "G", "ğ": "G", "Ü": "U", "ü": "U",
        "Ö": "O", "ö": "O", "Ç": "C", "ç": "C",
    }
    for tr_chr, en_chr in tr_map.items():
        text = text.replace(tr_chr, en_chr)
    return text.upper()


# ── Routing tablosu ───────────────────────────────────────────────────────────
# Anahtar: normalize_tr() uygulanmış alt sektör veya ana sektör adı
# Her routing kaydı namedtuple benzeri dict

def _route(
    sector_group: str,
    financial_model: str,
    sector_profile: str,
    primary_source: str,
    fallback_sources: list[str],
    routing_note: str = "",
    manual_review: bool = False,
) -> dict:
    return {
        "paynotu_sector_group":       sector_group,
        "financial_model":            financial_model,
        "sector_profile":             sector_profile,
        "primary_source":             primary_source,
        "fallback_sources":           fallback_sources,
        "financial_source_priority":  [primary_source] + fallback_sources,
        "routing_note":               routing_note,
        "manual_review_required":     manual_review,
    }

# Alt sektör bazında kesin eşleşme (öncelikli)
_SUB_ROUTING: dict[str, dict] = {

    # ── Banka ──────────────────────────────────────────────────────────────────
    normalize_tr("BANKALAR"): _route(
        "bank", "bank", "banking",
        "isyatirim_group_2",
        ["borsapy_banking", "yfinance_quarterly"],
    ),

    # ── Sigorta ────────────────────────────────────────────────────────────────
    normalize_tr("SİGORTA ŞİRKETLERİ"): _route(
        "insurance", "insurance", "insurance",
        "isyatirim_group_2",
        ["borsapy_yearly", "yfinance_quarterly"],
        routing_note="insurance model V2 mapping gerekebilir",
    ),

    # ── GYO ────────────────────────────────────────────────────────────────────
    normalize_tr("GAYRİMENKUL YATIRIM ORTAKLIKLARI"): _route(
        "gyo", "gyo", "gyo",
        "isyatirim_group_1",
        ["yfinance_quarterly", "borsapy_yearly"],
    ),

    # ── Holding ────────────────────────────────────────────────────────────────
    normalize_tr("HOLDİNGLER VE YATIRIM ŞİRKETLERİ"): _route(
        "holding", "holding", "holding",
        "isyatirim_group_1",
        ["yfinance_quarterly", "borsapy_yearly"],
    ),

    # ── Financial Special ──────────────────────────────────────────────────────
    normalize_tr("FİNANSAL KİRALAMA VE FAKTORİNG ŞİRKETLERİ"): _route(
        "financial_special", "financial_special", "financial_special",
        "isyatirim_group_2",
        ["borsapy_yearly"],
        routing_note="BDDK denetimli; banka modeli değil",
    ),
    normalize_tr("FİNANSMAN ŞİRKETLERİ"): _route(
        "financial_special", "financial_special", "financial_special",
        "isyatirim_group_2",
        ["borsapy_yearly"],
        routing_note="BDDK denetimli finansman şirketi",
    ),
    normalize_tr("VARLIK YÖNETİM ŞİRKETLERİ"): _route(
        "financial_special", "financial_special", "financial_special",
        "yfinance_quarterly",
        ["borsapy_yearly"],
        routing_note="isyatirimhisse kapsam dışı; yfinance primary",
    ),
    normalize_tr("ARACI KURUMLAR"): _route(
        "financial_special", "financial_special", "financial_special",
        "yfinance_quarterly",
        ["borsapy_yearly"],
        routing_note="SPK lisanslı aracı kurum; banka modeli değil",
    ),
    normalize_tr("DİĞER MALİ KURULUŞLAR"): _route(
        "financial_special", "financial_special", "financial_special",
        "yfinance_quarterly",
        ["borsapy_yearly"],
        routing_note="Diğer mali kuruluş; manual review önerilir",
        manual_review=True,
    ),

    # ── Investment Trust ───────────────────────────────────────────────────────
    normalize_tr("MENKUL KIYMET YATIRIM ORTAKLIKLARI"): _route(
        "investment_trust", "investment_trust", "investment_trust",
        "yfinance_quarterly",
        ["borsapy_yearly"],
        routing_note="NAV-bazlı değerleme; industrial model hatalı olur",
    ),
    normalize_tr("GİRİŞİM SERMAYESİ YATIRIM ORTAKLIKLARI"): _route(
        "investment_trust", "investment_trust", "investment_trust",
        "yfinance_quarterly",
        ["borsapy_yearly"],
        routing_note="VC portföyü; industrial model hatalı olur",
    ),

    # ── Energy Utility ─────────────────────────────────────────────────────────
    normalize_tr("ELEKTRİK GAZ VE BUHAR"): _route(
        "energy_utility", "energy_utility", "energy_utility",
        "isyatirim_group_1",
        ["yfinance_quarterly", "borsapy_yearly"],
        routing_note="Regüle enerji; borç toleransı industrial'dan yüksek",
    ),
    normalize_tr("HAM PETROL VE DOĞAL GAZ ÇIKARTILMASI"): _route(
        "energy_utility", "energy_utility", "energy_utility",
        "isyatirim_group_1",
        ["yfinance_quarterly", "borsapy_yearly"],
        routing_note="Rezerv-bazlı değerleme; energy_utility modeli",
    ),
    normalize_tr("HAM PETROL VE DOĞAL GAZ ÇIKARILMASI"): _route(
        "energy_utility", "energy_utility", "energy_utility",
        "isyatirim_group_1",
        ["yfinance_quarterly", "borsapy_yearly"],
        routing_note="Rezerv-bazlı değerleme; energy_utility modeli",
    ),

    # ── Technology Operational ─────────────────────────────────────────────────
    normalize_tr("BİLİŞİM"): _route(
        "technology_operational", "technology_operational", "technology",
        "isyatirim_group_1",
        ["yfinance_quarterly", "borsapy_yearly"],
        routing_note="F/K esnek esik (<=50); büyüme agirlikli",
    ),
    normalize_tr("SAVUNMA"): _route(
        "technology_operational", "technology_operational", "technology",
        "isyatirim_group_1",
        ["yfinance_quarterly", "borsapy_yearly"],
        routing_note="Kamu kontratli; savunma/teknoloji modeli",
    ),
    normalize_tr("BİLGİ HİZMET FAALİYETLERİ"): _route(
        "technology_operational", "technology_operational", "technology",
        "isyatirim_group_1",
        ["yfinance_quarterly", "borsapy_yearly"],
    ),
    normalize_tr("TELEKOMÜNİKASYON"): _route(
        "technology_operational", "technology_operational", "technology",
        "isyatirim_group_1",
        ["yfinance_quarterly", "borsapy_yearly"],
        routing_note="Altyapı yoğun telco; technology_operational modeli",
    ),
    normalize_tr("BİLİMSEL ARAŞTIRMA VE GELİŞTİRME FAALİYETLERİ"): _route(
        "technology_operational", "technology_operational", "technology",
        "isyatirim_group_1",
        ["yfinance_quarterly", "borsapy_yearly"],
    ),

    # ── Real Estate Operational ────────────────────────────────────────────────
    normalize_tr("GAYRİMENKUL FAALİYETLERİ"): _route(
        "real_estate_operational", "real_estate_operational",
        "real_estate_operational",
        "isyatirim_group_1",
        ["yfinance_quarterly", "borsapy_yearly"],
        routing_note="GYO değil; operasyonel gayrimenkul şirketi",
    ),

    # ── Service Operational ────────────────────────────────────────────────────
    normalize_tr("KONAKLAMA"): _route(
        "service_operational", "service_operational", "service",
        "isyatirim_group_1",
        ["yfinance_quarterly", "borsapy_yearly"],
    ),
    normalize_tr("YİYECEK VE İÇECEK HİZMETLERİ"): _route(
        "service_operational", "service_operational", "service",
        "isyatirim_group_1",
        ["yfinance_quarterly", "borsapy_yearly"],
    ),
    normalize_tr("YAYIMCILIK"): _route(
        "service_operational", "service_operational", "service",
        "isyatirim_group_1",
        ["yfinance_quarterly", "borsapy_yearly"],
    ),
    normalize_tr("İNSAN SAĞLIĞI VE SOSYAL HİZMETLER"): _route(
        "service_operational", "service_operational", "service",
        "isyatirim_group_1",
        ["yfinance_quarterly", "borsapy_yearly"],
    ),
    normalize_tr("SPOR FAALİYETLERİ EĞLENCE VE OYUN FAALİYETLERİ"): _route(
        "service_operational", "service_operational", "service",
        "isyatirim_group_1",
        ["yfinance_quarterly", "borsapy_yearly"],
    ),
    normalize_tr("SPOR EĞLENCE BOŞ ZAMANLARI DEĞERLENDİRME HİZMETLERİ"): _route(
        "service_operational", "service_operational", "service",
        "isyatirim_group_1",
        ["yfinance_quarterly", "borsapy_yearly"],
    ),
    normalize_tr("YARATICI SANATLAR GÖSTERİ SANATLARI VE EĞLENCE FAALİYETLERİ"): _route(
        "service_operational", "service_operational", "service",
        "isyatirim_group_1",
        ["yfinance_quarterly", "borsapy_yearly"],
    ),
    normalize_tr("REKLAMCILIK VE PAZAR ARAŞTIRMASI"): _route(
        "service_operational", "service_operational", "service",
        "isyatirim_group_1",
        ["yfinance_quarterly", "borsapy_yearly"],
    ),
    normalize_tr("HUKUK VE MUHASEBE FAALİYETLERİ"): _route(
        "service_operational", "service_operational", "service",
        "isyatirim_group_1",
        ["yfinance_quarterly", "borsapy_yearly"],
    ),
    normalize_tr("MİMARLIK VE MÜHENDİSLİK FAALİYETLERİ; TEKNİK MUAYENE VE ANALİZ"): _route(
        "service_operational", "service_operational", "service",
        "isyatirim_group_1",
        ["yfinance_quarterly", "borsapy_yearly"],
    ),
    normalize_tr("İDARE MERKEZİ FAALİYETLERİ; İDARİ DANIŞMANLIK FAALİYETLERİ"): _route(
        "service_operational", "service_operational", "service",
        "isyatirim_group_1",
        ["yfinance_quarterly", "borsapy_yearly"],
        routing_note="Holding benzeri yapı olabilir; manual_review önerilir",
        manual_review=True,
    ),
    normalize_tr("KİRALAMA VE LEASING FAALİYETLERİ"): _route(
        "service_operational", "service_operational", "service",
        "isyatirim_group_1",
        ["yfinance_quarterly", "borsapy_yearly"],
        routing_note="Operasyonel leasing → service; finansal leasing → financial_special",
        manual_review=True,
    ),
    normalize_tr("İSTİHDAM FAALİYETLERİ"): _route(
        "service_operational", "service_operational", "service",
        "isyatirim_group_1",
        ["yfinance_quarterly", "borsapy_yearly"],
    ),
    normalize_tr("SEYAHAT ACENTESI, TUR OPERATORU VE DIGER REZERVASYON HIZMETLERI ILE ILGILI FAALIYETLER"): _route(
        "service_operational", "service_operational", "service",
        "isyatirim_group_1",
        ["yfinance_quarterly", "borsapy_yearly"],
        routing_note="Mevsimsel turizm; stability skoru dalgalanabilir",
    ),
    normalize_tr("BÜRO YÖNETİMİ, BÜRO DESTEĞİ VE DİĞER ŞİRKET DESTEK FAALİYETLERİ"): _route(
        "service_operational", "service_operational", "service",
        "isyatirim_group_1",
        ["yfinance_quarterly", "borsapy_yearly"],
    ),
    normalize_tr("BİNALAR VE ÇEVRE DÜZENLEMESİ FAALİYETLERİ"): _route(
        "service_operational", "service_operational", "service",
        "isyatirim_group_1",
        ["yfinance_quarterly", "borsapy_yearly"],
    ),
    normalize_tr("GÜVENLİK VE SORUŞTURMA FAALİYETLERİ"): _route(
        "service_operational", "service_operational", "service",
        "isyatirim_group_1",
        ["yfinance_quarterly", "borsapy_yearly"],
    ),

    # ── Industrial General ─────────────────────────────────────────────────────
    normalize_tr("GIDA, İÇECEK VE TÜTÜN"): _route(
        "industrial", "industrial_general", "industrial_general",
        "isyatirim_group_1", ["yfinance_quarterly", "borsapy_yearly"],
    ),
    normalize_tr("TEKSTİL, GİYİM EŞYASI VE DERİ"): _route(
        "industrial", "industrial_general", "industrial_general",
        "isyatirim_group_1", ["yfinance_quarterly", "borsapy_yearly"],
    ),
    normalize_tr("ORMAN ÜRÜNLERİ VE MOBİLYA"): _route(
        "industrial", "industrial_general", "industrial_general",
        "isyatirim_group_1", ["yfinance_quarterly", "borsapy_yearly"],
    ),
    normalize_tr("KAĞIT VE KAĞIT ÜRÜNLERİ BASIM"): _route(
        "industrial", "industrial_general", "industrial_general",
        "isyatirim_group_1", ["yfinance_quarterly", "borsapy_yearly"],
    ),
    normalize_tr("KİMYA İLAÇ PETROL LASTİK VE PLASTİK ÜRÜNLER"): _route(
        "industrial", "industrial_general", "industrial_general",
        "isyatirim_group_1", ["yfinance_quarterly", "borsapy_yearly"],
        routing_note="Petrol rafinerisi (TUPRS) dahil; energy_utility değil",
    ),
    normalize_tr("TAŞ VE TOPRAĞA DAYALI"): _route(
        "industrial", "industrial_general", "industrial_general",
        "isyatirim_group_1", ["yfinance_quarterly", "borsapy_yearly"],
    ),
    normalize_tr("ANA METAL SANAYİ"): _route(
        "industrial", "industrial_general", "industrial_general",
        "isyatirim_group_1", ["yfinance_quarterly", "borsapy_yearly"],
    ),
    normalize_tr("METAL EŞYA MAKİNE ELEKTRİKLİ CİHAZLAR VE ULAŞIM ARAÇLARI"): _route(
        "industrial", "industrial_general", "industrial_general",
        "isyatirim_group_1", ["yfinance_quarterly", "borsapy_yearly"],
    ),
    normalize_tr("DİĞER İMALAT SANAYİİ"): _route(
        "industrial", "industrial_general", "industrial_general",
        "isyatirim_group_1", ["yfinance_quarterly", "borsapy_yearly"],
    ),
    normalize_tr("KÖMÜR VE LİNYİT MADENCİLİĞİ"): _route(
        "industrial", "industrial_general", "industrial_general",
        "isyatirim_group_1", ["yfinance_quarterly", "borsapy_yearly"],
    ),
    normalize_tr("METAL CEVHERİ MADENCİLİĞİ"): _route(
        "industrial", "industrial_general", "industrial_general",
        "isyatirim_group_1", ["yfinance_quarterly", "borsapy_yearly"],
    ),
    normalize_tr("DİĞER MADENCİLİK VE TAŞ OCAKÇILIĞI"): _route(
        "industrial", "industrial_general", "industrial_general",
        "isyatirim_group_1", ["yfinance_quarterly", "borsapy_yearly"],
    ),
    normalize_tr("İNŞAAT VE BAYINDIRLIK İŞLERİ"): _route(
        "industrial", "industrial_general", "industrial_general",
        "isyatirim_group_1", ["yfinance_quarterly", "borsapy_yearly"],
    ),
    normalize_tr("TOPTAN TİCARET"): _route(
        "industrial", "industrial_general", "industrial_general",
        "isyatirim_group_1", ["yfinance_quarterly", "borsapy_yearly"],
    ),
    normalize_tr("PERAKENDE TİCARET"): _route(
        "industrial", "industrial_general", "industrial_general",
        "isyatirim_group_1", ["yfinance_quarterly", "borsapy_yearly"],
    ),
    normalize_tr("ULAŞTIRMA VE DEPOLAMA"): _route(
        "industrial", "industrial_general", "industrial_general",
        "isyatirim_group_1", ["yfinance_quarterly", "borsapy_yearly"],
    ),
    normalize_tr("TARIM VE HAYVANCILIK AVCILIK VE İLGİLİ HİZMET FAALİYETLERİ"): _route(
        "industrial", "industrial_general", "industrial_general",
        "isyatirim_group_1", ["yfinance_quarterly", "borsapy_yearly"],
    ),
    normalize_tr("ORMANCILIK VE TOMRUKÇULUK"): _route(
        "industrial", "industrial_general", "industrial_general",
        "isyatirim_group_1", ["yfinance_quarterly", "borsapy_yearly"],
    ),
    normalize_tr("BALIKÇILIK VE SU ÜRÜNLERİ"): _route(
        "industrial", "industrial_general", "industrial_general",
        "isyatirim_group_1", ["yfinance_quarterly", "borsapy_yearly"],
    ),
}

# Ana sektör bazında fallback eşleme (alt sektör boş/bilinmez ise)
_MAIN_ROUTING: dict[str, dict] = {
    normalize_tr("TARIM, ORMANCILIK VE BALIKÇILIK"): _route(
        "industrial", "industrial_general", "industrial_general",
        "isyatirim_group_1", ["yfinance_quarterly", "borsapy_yearly"],
    ),
    normalize_tr("MADENCİLİK VE TAŞ OCAKÇILIĞI"): _route(
        "industrial", "industrial_general", "industrial_general",
        "isyatirim_group_1", ["yfinance_quarterly", "borsapy_yearly"],
    ),
    normalize_tr("İMALAT"): _route(
        "industrial", "industrial_general", "industrial_general",
        "isyatirim_group_1", ["yfinance_quarterly", "borsapy_yearly"],
    ),
    normalize_tr("ELEKTRİK GAZ VE SU"): _route(
        "energy_utility", "energy_utility", "energy_utility",
        "isyatirim_group_1", ["yfinance_quarterly", "borsapy_yearly"],
    ),
    normalize_tr("İNŞAAT VE BAYINDIRLIK"): _route(
        "industrial", "industrial_general", "industrial_general",
        "isyatirim_group_1", ["yfinance_quarterly", "borsapy_yearly"],
    ),
    normalize_tr("TOPTAN VE PERAKENDE TİCARET"): _route(
        "industrial", "industrial_general", "industrial_general",
        "isyatirim_group_1", ["yfinance_quarterly", "borsapy_yearly"],
    ),
    normalize_tr("ULAŞTIRMA VE DEPOLAMA"): _route(
        "industrial", "industrial_general", "industrial_general",
        "isyatirim_group_1", ["yfinance_quarterly", "borsapy_yearly"],
    ),
    normalize_tr("EĞİTİM SAĞLIK SPOR VE EĞLENCE HİZMETLERİ"): _route(
        "service_operational", "service_operational", "service",
        "isyatirim_group_1", ["yfinance_quarterly", "borsapy_yearly"],
    ),
    normalize_tr("TEKNOLOJİ"): _route(
        "technology_operational", "technology_operational", "technology",
        "isyatirim_group_1", ["yfinance_quarterly", "borsapy_yearly"],
    ),
    normalize_tr("MESLEKİ, BİLİMSEL VE TEKNİK FAALİYETLER"): _route(
        "service_operational", "service_operational", "service",
        "isyatirim_group_1", ["yfinance_quarterly", "borsapy_yearly"],
    ),
    normalize_tr("İDARİ VE DESTEK HİZMET FAALİYETLERİ"): _route(
        "service_operational", "service_operational", "service",
        "isyatirim_group_1", ["yfinance_quarterly", "borsapy_yearly"],
    ),
    normalize_tr("GAYRİMENKUL FAALİYETLERİ"): _route(
        "real_estate_operational", "real_estate_operational",
        "real_estate_operational",
        "isyatirim_group_1", ["yfinance_quarterly", "borsapy_yearly"],
    ),
    normalize_tr("OTELLER VE LOKANTALAR"): _route(
        "service_operational", "service_operational", "service",
        "isyatirim_group_1", ["yfinance_quarterly", "borsapy_yearly"],
    ),
    normalize_tr("BİLGİ VE İLETİŞİM"): _route(
        "technology_operational", "technology_operational", "technology",
        "isyatirim_group_1", ["yfinance_quarterly", "borsapy_yearly"],
    ),
}

_UNKNOWN_ROUTE = _route(
    "unknown", "unknown", "unknown",
    "yfinance_quarterly", ["borsapy_yearly"],
    routing_note="Sektör modeli otomatik belirlenemedi.",
    manual_review=True,
)


def resolve_routing(main_sector: str, sub_sector: str) -> dict:
    """Alt sektörden başla, bulamazsan ana sektörü dene, bulamazsan unknown."""
    sub_key  = normalize_tr(sub_sector)
    main_key = normalize_tr(main_sector)

    if sub_key and sub_key in _SUB_ROUTING:
        r = dict(_SUB_ROUTING[sub_key])
        r["match_level"] = "sub_sector"
        return r

    if main_key and main_key in _MAIN_ROUTING:
        r = dict(_MAIN_ROUTING[main_key])
        r["match_level"] = "main_sector"
        # Alt sektör yoksa not ekle
        if not sub_sector:
            r["routing_note"] = (r.get("routing_note") or "") + " [alt sektör yok]"
        return r

    r = dict(_UNKNOWN_ROUTE)
    r["match_level"] = "none"
    return r


# ── CSV → Routing ──────────────────────────────────────────────────────────────

CSV_PATH     = os.path.join(os.path.dirname(__file__), "..", "data", "kap_sektor_map.csv")
OUT_CSV_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "kap_sector_routing_preview.csv")
OUT_JSON_PATH= os.path.join(os.path.dirname(__file__), "..", "data", "kap_sector_routing_preview.json")


def build_routing(csv_path: str = CSV_PATH) -> tuple[list[dict], dict]:
    """CSV okuyup routing listesi döndürür.

    Returns:
        (rows, stats)
    """
    rows: list[dict] = []
    stats = {
        "total_csv": 0,
        "duplicates": [],
        "empty_symbol": 0,
        "empty_main_sector": 0,
        "empty_sub_sector": 0,
        "unknown_sector_group": 0,
        "manual_review": 0,
        "by_group": {},
        "by_main_sector": {},
    }

    seen_symbols: dict[str, int] = {}

    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            stats["total_csv"] += 1

            symbol      = (row.get("symbol") or "").strip()
            company     = (row.get("company_name") or "").strip()
            main_sector = (row.get("main_sector") or "").strip()
            sub_sector  = (row.get("sub_sector") or "").strip()

            if not symbol:
                stats["empty_symbol"] += 1
            if not main_sector:
                stats["empty_main_sector"] += 1
            if not sub_sector:
                stats["empty_sub_sector"] += 1

            # Duplicate kontrol
            if symbol in seen_symbols:
                stats["duplicates"].append(symbol)
            else:
                seen_symbols[symbol] = i

            # Routing
            routing = resolve_routing(main_sector, sub_sector)
            sg = routing["paynotu_sector_group"]

            if sg == "unknown":
                stats["unknown_sector_group"] += 1
            if routing["manual_review_required"]:
                stats["manual_review"] += 1

            stats["by_group"][sg] = stats["by_group"].get(sg, 0) + 1
            stats["by_main_sector"][main_sector] = (
                stats["by_main_sector"].get(main_sector, 0) + 1
            )

            rows.append({
                "symbol":                symbol,
                "company_name":          company,
                "kap_ana_sektor":        main_sector,
                "kap_alt_sektor":        sub_sector,
                **routing,
                "sector_source":         "KAP",
                "sector_source_file":    "sektorler.pdf",
                "sector_source_version": "kap_sektor_map_2026_05",
                "sector_verified":       True,
            })

    return rows, stats


def save_preview(rows: list[dict], stats: dict) -> None:
    """Preview CSV ve JSON dosyalarını yaz."""
    os.makedirs(os.path.dirname(OUT_CSV_PATH), exist_ok=True)

    csv_fields = [
        "symbol", "company_name", "kap_ana_sektor", "kap_alt_sektor",
        "paynotu_sector_group", "financial_model", "sector_profile",
        "primary_source", "fallback_sources", "financial_source_priority",
        "manual_review_required", "match_level", "routing_note",
        "sector_source", "sector_source_file", "sector_source_version",
        "sector_verified",
    ]
    with open(OUT_CSV_PATH, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            r = dict(row)
            # list → string for CSV
            r["fallback_sources"] = "|".join(r.get("fallback_sources") or [])
            r["financial_source_priority"] = "|".join(r.get("financial_source_priority") or [])
            writer.writerow(r)

    with open(OUT_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(
            {"meta": stats, "rows": rows},
            f, ensure_ascii=False, indent=2, default=str
        )


if __name__ == "__main__":
    import sys
    rows, stats = build_routing()
    save_preview(rows, stats)

    print(f"CSV satiri:            {stats['total_csv']}")
    print(f"Duplicate symbol:      {len(stats['duplicates'])}")
    print(f"Bos symbol:            {stats['empty_symbol']}")
    print(f"Bos main_sector:       {stats['empty_main_sector']}")
    print(f"Bos sub_sector:        {stats['empty_sub_sector']}")
    print(f"Unknown sector_group:  {stats['unknown_sector_group']}")
    print(f"Manual review:         {stats['manual_review']}")

    print(f"\nGroup dagilimi:")
    for g, c in sorted(stats["by_group"].items()):
        print(f"  {g:30s} {c}")

    print(f"\nOnizleme dosyalari kaydedildi:")
    print(f"  {OUT_CSV_PATH}")
    print(f"  {OUT_JSON_PATH}")

    if stats["duplicates"]:
        print(f"\nDuplicate semboller: {stats['duplicates'][:20]}")

    # Kontrol sembolleri
    checks = {
        "A1CAP": "financial_special", "A1YEN": "energy_utility",
        "AAGYO": "gyo",              "AKBNK": "bank",
        "AKGRT": "insurance",        "THYAO": "industrial",
        "TCELL": "technology_operational", "ASELS": "technology_operational",
        "FONET": "technology_operational", "SMRVA": "financial_special",
        "EREGL": "industrial",       "TUPRS": "industrial",
        "ISGYO": "gyo",              "KCHOL": "holding",
    }
    sym_map = {r["symbol"]: r for r in rows}
    print("\nKontrol sembolleri:")
    all_ok = True
    for sym, expected in checks.items():
        r = sym_map.get(sym)
        if r is None:
            print(f"  {sym:10s} BULUNAMADI")
            all_ok = False
        else:
            got = r["paynotu_sector_group"]
            ok  = "OK" if got == expected else f"HATA (beklenen={expected})"
            print(f"  {sym:10s} {got:30s} {ok}")
            if got != expected:
                all_ok = False
    print(f"\nKontrol: {'TUM TESTLER GECTI' if all_ok else 'HATALAR VAR'}")
