# -*- coding: utf-8 -*-
"""
PayNotu — Temel Analiz Motoru (Fundamental Engine) v1.0
========================================================
Görev: Şirketin finansal sağlığını 0–10 arası tek bir
finansal_skor değerine dönüştür.

Yatırım tavsiyesi değil.  Al / sat / tut yok.  Gelecek tahmin yok.
Ölçülen şey: finansal tablo verilerinden türetilen sağlık skoru.

Sektör grupları:
  industrial  — sanayi, enerji, teknoloji, perakende, vb.
  bank        — bankacılık, finansal
  insurance   — sigortacılık
  gyo         — gayrimenkul yatırım ortaklığı
  holding     — holding
  unknown     — eşleşme yok

Alt skorlar (0–10):
  profitability  — karlılık
  balance_sheet  — bilanço sağlığı  (bank/insurance → not_applicable)
  cash_flow      — nakit akışı      (bank/insurance → not_applicable)
  growth         — büyüme
  valuation      — değerleme
  stability      — istikrar
  piotroski      — Piotroski F-Skoru (bank/insurance → not_applicable)
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── Yasak kelime filtresi ─────────────────────────────────────────────────────
_FORBIDDEN_WORDS: List[str] = [
    "al", "sat", "tut", "fırsat", "ucuz", "pahalı",
    "yükselecek", "düşecek", "hedef fiyat", "prim", "kaçırma",
]

# ── Normalize eşik tablosu: (low, high) ──────────────────────────────────────
_T: Dict[str, Tuple[float, float]] = {
    "roe":           (0.00,  0.30),
    "roa":           (0.00,  0.15),
    "nkm":          (-0.10,  0.25),
    "gross_margin":  (0.00,  0.50),
    "op_margin":     (0.00,  0.30),
    "nim":           (0.00,  0.08),   # Net Interest Margin (banka)
    "current_ratio": (0.80,  2.50),
    "debt_equity":   (0.00,  3.00),   # reverse=True
    "interest_cov":  (1.00, 10.00),
    "nd_ebitda":     (0.00,  6.00),   # reverse=True
    "fcf_nk":       (-0.50,  1.50),   # FCF / Net Kar
    "fcf_margin":   (-0.05,  0.15),   # FCF / Satışlar
    "growth":       (-0.20,  0.50),
}

# ── Sektöre göre F/K ve PD/DD tavan değerleri (normalize için) ───────────────
_FK_HIGH  = {"bank": 20.0, "gyo": 20.0, "insurance": 20.0,
             "holding": 25.0, "industrial": 30.0, "unknown": 30.0}
_PDDD_HIGH = {"bank": 2.0, "gyo": 1.5, "insurance": 2.0,
              "holding": 2.5, "industrial": 4.0, "unknown": 4.0}

# ── Sektör eşleme tablosu (normalize edilmiş Türkçe → group) ─────────────────
_SECTOR_MAP: Dict[str, str] = {
    "BANKACILIK":   "bank",
    "FINANSAL":     "bank",
    "KALKINMA":     "bank",
    "VARLIK":       "bank",   # Varlık Yönetimi
    "ARACI KURUM":  "bank",   # Aracı Kurumlar
    "SERMAYE PIYA": "bank",   # Sermaye Piyasaları
    "SIGORTA":      "insurance",
    "SIGORTACILIK": "insurance",
    "GYO":          "gyo",
    "GAYRIMENKUL":  "gyo",
    "HOLDING":      "holding",
}

# Tam eşleşme gerektiren girdiler — alt string aramasına girmeden önce kontrol edilir.
# "financial" tek başına eşleşmesin diye _SECTOR_MAP'tan ayrı tutulur.
_SECTOR_EXACT: Dict[str, str] = {
    "FINANCIAL SERVICES": "bank",
    "BANKALAR":           "bank",
    "BANKS":              "bank",
    "BANK":               "bank",
}

# ── Firestore'dan gelen canonical sector_group değerleri ─────────────────────
# Bu değerler _get_sector_group() tarafından doğrudan geçirilir.
_CANONICAL_SECTOR_GROUPS: set = {
    "industrial",
    "bank",
    "insurance",
    "gyo",
    "holding",
    "financial_special",
    "investment_trust",
    "technology_operational",
    "energy_utility",
    "service_operational",
    "real_estate_operational",
    "unknown",
}

# Henüz özel modeli olmayan gruplar → skor üretme, "Veri Yetersiz" döndür
_UNSUPPORTED_GROUPS: set = {
    "financial_special",
}

# V1'de genel operasyonel (industrial) modelle hesaplanan genişletilmiş gruplar
# Compute fonksiyonlarına "industrial" olarak iletilir; flag eklenir.
_COMPUTE_GROUP_MAP: Dict[str, str] = {
    "technology_operational":  "industrial",
    "energy_utility":          "industrial",
    "service_operational":     "industrial",
    "real_estate_operational": "industrial",
}

_V1_OPERATIONAL_FLAG = (
    "Bu sektör V1'de genel operasyonel model ile hesaplanmıştır; "
    "sektör özel eşikleri sonraki etapta uygulanacaktır."
)

# ── Piotroski uygulanabilirlik sabitleri ──────────────────────────────────────
_PIOTROSKI_NOT_APPLICABLE_GROUPS: set = {
    "bank", "insurance", "financial_special", "investment_trust", "unknown",
}
_PIOTROSKI_LIMITED_GROUPS: set = {"gyo", "holding"}

_PIOTROSKI_NA_MSGS: Dict[str, str] = {
    "bank":              "Bankalar için klasik Piotroski F-Score uygulanabilir değildir.",
    "insurance":         "Sigorta şirketleri için klasik Piotroski F-Score uygulanabilir değildir.",
    "financial_special": "Financial special sektör grubu için klasik Piotroski F-Score uygulanabilir değildir.",
    "investment_trust":  "Investment trust sektör grubu için klasik Piotroski F-Score uygulanabilir değildir.",
    "unknown":           "Sektör grubu bilinmediğinden Piotroski F-Score hesaplanamadı.",
}
_PIOTROSKI_LIMITED_MSG = (
    "Bu sektörde Piotroski kriterleri sınırlı yorumlanmalıdır."
)
_PIOTROSKI_OPERATIONAL_FLAG = (
    "Piotroski skoru genel operasyonel finansal tablo mantığıyla hesaplanmıştır."
)
_PIOTROSKI_OPERATIONAL_GROUPS: set = {
    "technology_operational", "energy_utility",
    "service_operational", "real_estate_operational",
}


def _piotroski_confidence(calc: int) -> str:
    """Hesaplanan kriter sayısına göre confidence seviyesi."""
    if calc >= 7:
        return "high"
    if calc >= 5:
        return "medium"
    return "insufficient"

# ── Alt skor ağırlıkları ──────────────────────────────────────────────────────
_WEIGHTS: Dict[str, float] = {
    "profitability": 0.25,
    "balance_sheet": 0.20,
    "cash_flow":     0.15,
    "growth":        0.15,
    "valuation":     0.10,
    "stability":     0.10,
    "piotroski":     0.05,
}

# ── Broker Operational ağırlıkları ────────────────────────────────────────────
# cash_flow ve piotroski "not_applicable" → _weighted_average tarafından dışlanır.
# Kalan 5 alt skor: profitability(30) + balance_sheet/capital_strength(25)
#                   + growth(20) + stability(15) + valuation(10) = 1.00
_BROKER_WEIGHTS: Dict[str, float] = {
    "profitability":  0.30,
    "balance_sheet":  0.25,   # capital_strength bu alana map edilir
    "cash_flow":      0.15,   # not_applicable — dışlanır
    "growth":         0.20,
    "valuation":      0.10,
    "stability":      0.15,
    "piotroski":      0.05,   # not_applicable — dışlanır
}

_BROKER_PIOTROSKI_NA_MSG = (
    "Aracı kurumlar için klasik Piotroski F-Score uygulanabilir değildir. "
    "Yapısal CFO volatilitesi ve işlem hacmi kaynaklı gelir satırı anomalisi "
    "(3C = işlem hacmi, gelir değil) nedeniyle standart kriterler güvenilir "
    "sonuç üretmez."
)

# ── Lending Operational ağırlıkları ──────────────────────────────────────────
# cash_flow ve piotroski not_applicable → dışlanır.
# Kalan 5: profitability(30) + balance_sheet/capital_adequacy(25)
#          + growth(20) + stability(15) + valuation(10) = 1.00
_LENDING_WEIGHTS: Dict[str, float] = {
    "profitability":  0.30,
    "balance_sheet":  0.25,   # capital_adequacy bu alana map edilir
    "cash_flow":      0.15,   # not_applicable
    "growth":         0.20,
    "valuation":      0.10,
    "stability":      0.15,
    "piotroski":      0.05,   # limited ama final skora dahil değil → not_applicable
}

_LENDING_PIOTROSKI_MSG = (
    "Lending operational şirketlerinde klasik Piotroski F-Score sınırlı "
    "yorumlanmalıdır; final skora dahil edilmedi."
)

_LENDING_STALE_CUTOFF = pd.Timestamp("2025-11-30")

# ── Insurance V1 ağırlıkları ──────────────────────────────────────────────────
# cash_flow ve piotroski → not_applicable (dışlanır)
# balance_sheet = technical_perf
# wapp = 0.30+0.25+0.20+0.10+0.15 = 1.00
_INS_WEIGHTS: Dict[str, float] = {
    "profitability":  0.30,
    "balance_sheet":  0.25,   # technical_perf bu alana map edilir
    "cash_flow":      0.15,   # not_applicable
    "growth":         0.20,
    "valuation":      0.10,
    "stability":      0.15,
    "piotroski":      0.05,   # not_applicable
}

_INS_PIOTROSKI_NA_MSG = (
    "Sigorta şirketleri için klasik Piotroski F-Score uygulanabilir değildir."
)

_INS_NET_PROFIT_KEYS: List[str] = [
    "F-Dönem Net Karı",
    "N- Dönem Net Karı veya Zararı",
]
_INS_TECHNICAL_INCOME_KEYS: List[str] = [
    "A- Hayat Dışı Teknik Gelir",
    "D- Hayat Teknik Gelir",
    "G- Emeklilik Teknik Gelir",
]
_INS_TECHNICAL_BALANCE_KEYS: List[str] = [
    "J- Genel Teknik Bölüm Dengesi",
    "C- Teknik Bölüm Dengesi- Hayat Dışı",
    "F- Teknik Bölüm Dengesi- Hayat",
    "I- Teknik Bölüm Dengesi- Emeklilik",
    "I - Teknik Bölüm Dengesi- Emeklilik",
]
_INS_PREMIUM_KEYS: List[str] = [
    "1.1- Yazılan Primler (Reasürör Payı Düşülmüş Olarak)",
    "1.1.1- Brüt Yazılan Primler (+)",
]
_INS_INVESTMENT_INCOME_KEYS: List[str] = [
    "K- Yatırım Gelirleri",
]

# ── Investment Trust ağırlıkları ──────────────────────────────────────────────
# profitability / cash_flow / piotroski → not_applicable (dışlanır)
# balance_sheet = leverage, growth = nav_growth
# wapp (not_applicable dışlandığında) = 0.15+0.30+0.35+0.20 = 1.00
_IT_WEIGHTS: Dict[str, float] = {
    "profitability":  0.25,   # not_applicable
    "balance_sheet":  0.15,   # leverage
    "cash_flow":      0.15,   # not_applicable
    "growth":         0.30,   # nav_growth
    "valuation":      0.35,   # P/B odaklı
    "stability":      0.20,
    "piotroski":      0.05,   # not_applicable
}

_IT_PIOTROSKI_NA_MSG = (
    "Yatırım ortaklıkları için klasik Piotroski F-Score uygulanabilir değildir; "
    "model NAV/özkaynak odaklı hesaplanmıştır."
)

# ── GYO V1 ağırlıkları ────────────────────────────────────────────────────────
# cash_flow ve piotroski not_applicable → _weighted_average tarafından dışlanır.
# Kalan 5: profitability(25) + balance_sheet/asset_strength(20)
#          + growth(20) + valuation(25) + stability(10) = 1.00
_GYO_WEIGHTS: Dict[str, float] = {
    "profitability": 0.25,   # ROE + ROA
    "balance_sheet": 0.20,   # asset_strength bu alana map edilir
    "cash_flow":     0.15,   # not_applicable — dışlanır
    "growth":        0.20,   # equity YoY dominant, revenue dışarıda
    "valuation":     0.25,   # P/B dominant
    "stability":     0.10,   # equity CV + NI pozitiflik
    "piotroski":     0.05,   # limited, final skora dahil değil — dışlanır
}

# P/B skor parametreleri
_IT_PB_DEEP_DISCOUNT = 0.3   # altında → floor skor + flag
_IT_PB_DISCOUNT_CAP  = 0.5   # altında → skor 5.0'a cap (aşırı düşük P/B otomatik iyi sayılmaz)
_IT_PB_PREMIUM_CEIL  = 2.5   # üstünde → skor 0 + flag

# Investment trust kaynak seçim eşikleri
_IT_ISYAT_MIN_YEAR      = 2023                        # isyatirim dönemi >= bu yılsa geçerli
_IT_YF_PREFERRED_CUTOFF = pd.Timestamp("2025-12-01")  # yfinance bu tarih >= ise borsapy yerine tercih edilir


def _it_period_year(data: Optional[dict]) -> int:
    """Veri döneminin yılını döndür; bulunamazsa 0."""
    if data is None:
        return 0
    period = data.get("period") or ""
    m = re.match(r"^(\d{4})", str(period))
    return int(m.group(1)) if m else 0


def _it_latest_col_ym(data: Optional[dict]) -> Optional[Tuple[int, int]]:
    """Veri setinin en güncel kolon (year, month) tuple'ını döndür."""
    if data is None:
        return None
    for key in ("is_", "bs"):
        df = data.get(key)
        if df is None or (hasattr(df, "empty") and df.empty):
            continue
        try:
            for col in df.columns[:1]:
                t = _parse_col_period(col)
                if t:
                    return (t[0], t[1])
        except Exception:
            pass
    return None


def _it_has_required(data: dict, yf: bool) -> bool:
    """equity ve total_assets satırları mevcut mu?"""
    try:
        bs = data.get("bs", pd.DataFrame())
        if yf:
            return (
                _yf_get(bs, YF_TOTAL_EQUITY_KEYS) is not None and
                _yf_get(bs, YF_TOTAL_ASSETS_KEYS) is not None
            )
        return (
            _get_row(bs, _EQUITY_KEYS) is not None and
            _get_row(bs, _TOTAL_ASSETS_KEYS) is not None
        )
    except Exception:
        return False


def _is_lending_stale(data: dict) -> bool:
    """Verinin en güncel döneminin 2025-11-30'dan önce olup olmadığını kontrol et."""
    try:
        is_ = data.get("is_")
        if is_ is None or is_.empty:
            return False
        latest = is_.columns[0]
        ts = pd.Timestamp(latest) if not hasattr(latest, "date") else pd.Timestamp(latest)
        return ts < _LENDING_STALE_CUTOFF
    except Exception:
        return False

# ── borsapy satır adı alias listeleri ────────────────────────────────────────
_NET_PROFIT_KEYS = [
    "DÖNEM KARI (ZARARI)",
    "Ana Ortaklık Payları",
    "SÜRDÜRÜLENFAALİYETLER DÖNEM KARI/ZARARI",
    "Dönem Net Kar/Zararı",
    # İş Yatırım XI_29
    "NET PROFIT AFTER TAXES",
    "Profit (Loss)",
    "Net Income",
]
_REVENUE_KEYS = [
    "Satış Gelirleri",
    "HASILAT",
    "NET SATIŞLAR",
    # İş Yatırım XI_29 — sadece gelir satırları, "Maliyeti" içerenler hariç
    "Satışlar",
    "Hasılat",
    "Revenue",
    "Net Revenues",
    "Total Revenue",
    "Net Sales",
]
_GROSS_PROFIT_KEYS = [
    "BRÜT KAR (ZARAR)",
    "BRÜT KAR",
    # İş Yatırım XI_29
    "Ticari Faaliyetlerden Brüt Kar (Zarar)",
    "Gross Profit",
]
_OPERATING_PROFIT_KEYS = [
    "FAALİYET KARI (ZARARI)",
    "ESAS FAALİYET KARI",
    # İş Yatırım EN
    "Operating Income",
    "Operating Profit",
]
_TOTAL_ASSETS_KEYS = [
    "TOPLAM VARLIKLAR",
    "AKTİF TOPLAMI",
    "Total Assets",
]
_EQUITY_KEYS = [
    "Ana Ortaklığa Ait Özkaynaklar",
    "Özkaynaklar",
    "XVI. ÖZKAYNAKLAR",
    # İş Yatırım EN
    "Equity",
    "Total Equity",
    "Common Equity",
]
_CURRENT_ASSETS_KEYS = ["Dönen Varlıklar", "Current Assets"]
_CURRENT_LIAB_KEYS   = ["Kısa Vadeli Yükümlülükler", "Current Liabilities"]
_CASH_KEYS           = ["Nakit ve Nakit Benzerleri", "Cash and Cash Equivalents"]
_PAID_CAPITAL_KEYS   = ["Ödenmiş Sermaye", "16.1 Ödenmiş Sermaye", "Paid-in Capital"]
_FIN_EXPENSE_KEYS    = [
    "(Esas Faaliyet Dışı) Finansal Giderler (-)",
    "Finansman Giderleri",
    "Finansman Gideri",
    "Interest Expense",
]
_FIN_DEBT_KEYS = [
    "Finansal Borçlar",
    "Financial Liabilities",
    "Borrowings",
]
_AMORTIZATION_KEYS = [
    "Amortisman & İtfa Payları",
    "Amortisman Giderleri",
    "Depreciation and Amortization",
]
_OPERATING_CF_KEYS = [
    "İşletme Faaliyetlerinden Kaynaklanan Net Nakit",
    "İşletme Faaliyetleri Net Nakit",
    # İş Yatırım EN
    "Operating Activities",
    "Net Cash From Operating Activities",
    "Cash Flow From Operating Activities",
]
_FCF_KEYS = [
    "Serbest Nakit Akımı",
    "Serbest Nakit Akışı",
    # İş Yatırım
    "Serbest Nakit Akım",
    "Free Cash Flow",
]
# Banka satır adları
_BANK_TOTAL_ASSETS_KEYS = ["AKTİF TOPLAMI", "PASİF TOPLAMI"]
_BANK_EQUITY_KEYS       = ["XVI. ÖZKAYNAKLAR", "ÖZKAYNAKLAR"]
_BANK_NET_PROFIT_KEYS   = [
    "XXIII. NET DÖNEM KARI/ZARARI (XVII+XXII)",
    "XVI. SÜRDÜRÜLENFAALİYETLER DÖNEM NET K/Z",
    "16.4.2 Dönem Net Kar/Zararı",
]
_BANK_INTEREST_INCOME_KEYS = ["I. FAİZ GELİRLERİ", "FAİZ GELİRLERİ"]
_BANK_NET_INTEREST_KEYS    = [
    "III. NET FAİZ GELİRİ/GİDERİ (I - II)",
    "NET FAİZ GELİRİ/GİDERİ",
]
_BANK_TOTAL_INCOME_KEYS = [
    "VIII. FAALİYET GELİRLERİ/GİDERLERİ TOPLAMI (III+IV+V+VI+VII)",
    "FAALİYET GELİRLERİ/GİDERLERİ TOPLAMI",
]


# ── yfinance satır adı alias listeleri ───────────────────────────────────────
# yfinance v0.2.x+ CamelCase format kullanır (boşluksuz)
YF_REVENUE_KEYS = [
    "TotalRevenue", "OperatingRevenue", "Revenue",
    # eski yfinance sürümleri için fallback
    "Total Revenue", "Operating Revenue",
]
YF_NET_INCOME_KEYS = [
    "NetIncome",
    "NetIncomeCommonStockholders",
    "NetIncomeFromContinuingOperationNetMinorityInterest",
    # eski format
    "Net Income",
    "Net Income Common Stockholders",
    "Net Income From Continuing Operation Net Minority Interest",
]
YF_GROSS_PROFIT_KEYS = ["GrossProfit", "Gross Profit"]
YF_OPERATING_INCOME_KEYS = [
    "OperatingIncome", "TotalOperatingIncomeAsReported",
    # eski format
    "Operating Income", "Operating Income Or Loss",
    "Total Operating Income As Reported",
]
YF_EBITDA_KEYS = ["EBITDA", "NormalizedEBITDA", "Normalized EBITDA"]
YF_TOTAL_ASSETS_KEYS = ["TotalAssets", "Total Assets"]
YF_TOTAL_EQUITY_KEYS = [
    "CommonStockEquity",
    "StockholdersEquity",
    "TotalEquityGrossMinorityInterest",
    # eski format
    "Common Stock Equity",
    "Stockholders Equity",
    "Total Equity Gross Minority Interest",
]
YF_TOTAL_DEBT_KEYS = [
    "TotalDebt", "NetDebt",
    # eski format
    "Total Debt", "Net Debt",
]
YF_CURRENT_ASSETS_KEYS = [
    "CurrentAssets", "TotalCurrentAssets",
    # eski format
    "Current Assets", "Total Current Assets",
]
YF_CURRENT_LIABILITIES_KEYS = [
    "CurrentLiabilities", "TotalCurrentLiabilities",
    # eski format
    "Current Liabilities", "Total Current Liabilities",
    "Total Current Liabilities Payments Due Within One Year",
]
YF_INTEREST_EXPENSE_KEYS = [
    "InterestExpense", "InterestExpenseNonOperating",
    # eski format
    "Interest Expense", "Interest Expense Non Operating",
]
YF_NET_INTEREST_INCOME_KEYS = ["NetInterestIncome", "Net Interest Income"]
# Brüt faiz geliri — lending_operational için (NetInterestIncome'dan ayrı)
YF_INTEREST_INCOME_GROSS_KEYS = [
    "InterestIncome", "TotalInterestIncome",
    "Interest Income", "Total Interest Income",
]
YF_OPERATING_CASHFLOW_KEYS = [
    "OperatingCashFlow", "CashFlowFromContinuingOperatingActivities",
    # eski format
    "Operating Cash Flow", "Cash Flow From Continuing Operating Activities",
]
YF_FREE_CASHFLOW_KEYS = ["FreeCashFlow", "Free Cash Flow"]
YF_SHARES_KEYS = [
    "ShareIssued", "OrdinarySharesNumber",
    # eski format
    "Share Issued", "Ordinary Shares Number",
]


def _to_yfinance_symbol(ticker: str) -> str:
    """THYAO → THYAO.IS   |   thyao.is → THYAO.IS"""
    symbol = str(ticker or "").strip()
    symbol = symbol.replace("ı", "I").replace("İ", "I").upper()
    if symbol.endswith(".IS"):
        return symbol
    if "." in symbol:
        symbol = symbol.split(".", 1)[0]
    return f"{symbol}.IS"


# ════════════════════════════════════════════════════════════════════════════
# Dataclass'lar
# ════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class MetricAvailability:
    calculated:     int
    missing:        int
    not_applicable: int

    @property
    def quality(self) -> float:
        d = self.calculated + self.missing
        return round(self.calculated / d, 2) if d > 0 else 0.0


@dataclass(frozen=True)
class FundamentalSubscores:
    profitability:  Optional[float] = None
    balance_sheet:  Optional[float] = None
    cash_flow:      Optional[float] = None
    growth:         Optional[float] = None
    valuation:      Optional[float] = None
    stability:      Optional[float] = None
    piotroski:      Optional[float] = None


@dataclass(frozen=True)
class PiotroskiResult:
    score:               Optional[int]
    normalized:          Optional[float]
    calculated_criteria: int
    total_criteria:      int = 9
    coverage:            float = 0.0            # calculated_criteria / 9
    confidence:          str = "insufficient"   # high/medium/insufficient/not_applicable
    applicability:       str = "applicable"     # applicable/limited/not_applicable
    missing_criteria:    List[str] = field(default_factory=list)
    details:             dict = field(default_factory=dict)


@dataclass(frozen=True)
class FundamentalResult:
    ticker:                  str
    financial_score:         Optional[float]
    financial_score_label:   str
    financial_score_quality: float
    subscores:               FundamentalSubscores
    piotroski:               Optional[PiotroskiResult]
    financial_flags:         List[str]
    explanation:             str
    sector_group:            str
    data_source:             str
    period:                  Optional[str]

    def copyWith(self, **kwargs) -> "FundamentalResult":
        import dataclasses
        return dataclasses.replace(self, **kwargs)


# ════════════════════════════════════════════════════════════════════════════
# Yardımcı fonksiyonlar
# ════════════════════════════════════════════════════════════════════════════

def _parse_col_period(col) -> Optional[Tuple[int, int, str]]:
    """Kolon adından (year, month, label) tuple üretir.

    Desteklenen formatlar: pd.Timestamp, "YYYY-MM-DD", "YYYY-MM-DD HH:MM:SS",
    "YYYY/MM", "YYYY-MM", "YYYY".
    """
    try:
        if hasattr(col, "year"):          # pd.Timestamp
            y, m = int(col.year), int(col.month)
        else:
            s = str(col).strip()
            m1 = re.match(r'^(\d{4})-(\d{2})-\d{2}', s)
            if m1:
                y, m = int(m1.group(1)), int(m1.group(2))
            else:
                m2 = re.match(r'^(\d{4})[/\-](\d{1,2})$', s)
                if m2:
                    y, m = int(m2.group(1)), int(m2.group(2))
                else:
                    m3 = re.match(r'^(\d{4})$', s)
                    if not m3:
                        return None
                    y, m = int(m3.group(1)), 12
    except Exception:
        return None
    label = f"{y} Yıllık" if m == 12 else f"{y} {m} Aylık"
    return (y, m, label)


def _extract_period_from_columns(df: Optional[pd.DataFrame]) -> Optional[str]:
    """DataFrame kolonlarından en güncel dönemi tespit eder."""
    if df is None or df.empty or len(df.columns) == 0:
        return None
    best: Optional[Tuple[int, int, str]] = None
    for col in df.columns:
        t = _parse_col_period(col)
        if t and (best is None or (t[0], t[1]) > (best[0], best[1])):
            best = t
    return best[2] if best else None


def _detect_latest_period(*dfs: Optional[pd.DataFrame]) -> Optional[str]:
    """Birden fazla DataFrame'den en güncel dönemi tespit eder."""
    best: Optional[Tuple[int, int, str]] = None
    for df in dfs:
        if df is None or df.empty:
            continue
        for col in df.columns:
            t = _parse_col_period(col)
            if t and (best is None or (t[0], t[1]) > (best[0], best[1])):
                best = t
    return best[2] if best else None


def _normalize_tr(text: str) -> str:
    """Türkçe karakterleri ASCII'ye çevir, büyük harf ve strip."""
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", text)
    out  = "".join(c for c in nfkd if not unicodedata.combining(c))
    for tr, en in {"ı": "i", "İ": "I", "Ş": "S", "ş": "s", "Ğ": "G",
                   "ğ": "g", "Ç": "C", "ç": "c", "Ü": "U", "ü": "u",
                   "Ö": "O", "ö": "o"}.items():
        out = out.replace(tr, en)
    return out.upper().strip()


def _normalize(
    value: Optional[float],
    low:   float,
    high:  float,
    reverse: bool = False,
) -> Optional[float]:
    if value is None or high == low:
        return None
    r = (value - low) / (high - low)
    r = max(0.0, min(1.0, r))
    if reverse:
        r = 1.0 - r
    return round(r * 10, 2)


def _safe_div(a, b, default=None):
    try:
        if b is None or b == 0:
            return default
        r = a / b
        return r if np.isfinite(r) else default
    except Exception:
        return default


def _get_row(df: pd.DataFrame, candidates: List[str]) -> Optional[float]:
    """İlk eşleşen satırın en son dönem (col 0) değeri."""
    idx = df.index.str.strip()
    for key in candidates:
        matches = df[idx == key.strip()]
        if not matches.empty:
            v = matches.iloc[0, 0]
            return float(v) if pd.notna(v) else None
    return None


def _get_row_period(
    df: pd.DataFrame,
    candidates: List[str],
    period_idx: int,
) -> Optional[float]:
    """Belirli dönem index için satır değeri."""
    if period_idx >= df.shape[1]:
        return None
    idx = df.index.str.strip()
    for key in candidates:
        matches = df[idx == key.strip()]
        if not matches.empty:
            v = matches.iloc[0, period_idx]
            return float(v) if pd.notna(v) else None
    return None


def _sum_key_period(
    df: pd.DataFrame,
    key: str,
    period_idx: int,
) -> Optional[float]:
    """Aynı isimli tüm satırların belirli dönem toplamı (KV+UV Finansal Borçlar gibi)."""
    if period_idx >= df.shape[1]:
        return None
    idx     = df.index.str.strip()
    matches = df[idx == key.strip()]
    if matches.empty:
        return None
    values = [float(v) for v in matches.iloc[:, period_idx] if pd.notna(v)]
    return sum(values) if values else None


def _sum_key_latest(df: pd.DataFrame, key: str) -> Optional[float]:
    """Aynı isimli tüm satırların col 0 toplamı."""
    return _sum_key_period(df, key, 0)


def _iy_ttm_sum(
    df: pd.DataFrame,
    keys: List[str],
    n: int = 4,
    min_valid: int = 2,
) -> Optional[float]:
    """İş Yatırım pivotlanmış df'den TTM: ilk n kolon toplamı.

    Kolonlar newest-first sıralı: col 0 = en güncel çeyrek.
    min_valid: en az bu kadar geçerli çeyrek yoksa None döner.
    """
    if df is None or df.empty:
        return None
    idx = df.index.str.strip()
    for key in keys:
        matches = df[idx == key.strip()]
        if matches.empty:
            continue
        vals: List[float] = []
        for i in range(min(n, df.shape[1])):
            v = matches.iloc[0, i]
            if pd.notna(v):
                try:
                    vals.append(float(v))
                except (TypeError, ValueError):
                    pass
        if len(vals) >= min_valid:
            return sum(vals)
    return None


def _contains_forbidden(text: str, words: List[str] = _FORBIDDEN_WORDS) -> bool:
    for w in words:
        if re.search(rf"\b{re.escape(w)}\b", text.lower()):
            return True
    return False


def _yf_get(df: Optional[pd.DataFrame], keys: List[str]) -> Optional[float]:
    """yfinance DataFrame'den ilk eşleşen satırın en güncel (col 0) değeri."""
    if df is None or df.empty:
        return None
    for key in keys:
        if key in df.index:
            v = df.loc[key].iloc[0]
            return float(v) if pd.notna(v) else None
    return None


def _yf_ttm(df: Optional[pd.DataFrame], keys: List[str],
            start: int = 0, n: int = 4, min_q: int = 2) -> Optional[float]:
    """Son n çeyreğin toplamı (TTM). NaN olanlar atlanır.
    min_q: geçerli çeyrek sayısı bu değerin altındaysa None döner.
    """
    if df is None or df.empty:
        return None
    for key in keys:
        if key in df.index:
            row = df.loc[key]
            end = min(start + n, len(row))
            vals = [float(v) for v in row.iloc[start:end] if pd.notna(v)]
            if len(vals) >= min_q:
                return sum(vals)
    return None


# ════════════════════════════════════════════════════════════════════════════
# FundamentalEngine
# ════════════════════════════════════════════════════════════════════════════

class FundamentalEngine:
    """
    Şirket finansal tablolarından 0–10 arası sağlık skoru üretir.
    Yatırım tavsiyesi içermez; al/sat/tut yok.
    """

    # ── Genel giriş ────────────────────────────────────────────────────────

    def calculate(
        self,
        ticker:          str,
        sektor:          Optional[str] = None,
        sector_group:    Optional[str] = None,   # Firestore canonical değeri öncelikli
        financial_model: Optional[str] = None,   # şimdilik kullanılmıyor, imza uyumu için
        sector_profile:  Optional[str] = None,   # broker_operational vb. alt profil
    ) -> FundamentalResult:
        # ── Sektör grubu belirle ────────────────────────────────────────────
        if sector_group and sector_group in _CANONICAL_SECTOR_GROUPS:
            sg = sector_group
        else:
            sg = self._get_sector_group(sektor)

        flags: List[str] = []

        # ── Broker Operational özel yolu ────────────────────────────────────
        if sg == "financial_special" and sector_profile == "broker_operational":
            return self._calculate_broker_operational(
                ticker, sg, sector_profile, flags
            )

        # ── Lending Operational özel yolu ───────────────────────────────────
        if sg == "financial_special" and sector_profile == "lending_operational":
            return self._calculate_lending_operational(
                ticker, sg, sector_profile, flags
            )

        # ── Asset Management özel yolu ──────────────────────────────────────
        # V1: lending_operational modeli kullanılır; AUM alacak uyarısı eklenir.
        if sg == "financial_special" and sector_profile == "asset_mgmt":
            flags.append(
                "Varlık yönetim şirketi lending modeli üzerinden hesaplandı; "
                "OtherReceivables kaynaklı bilanço şişmesi ROA'yı sistematik "
                "olarak düşük gösterebilir."
            )
            return self._calculate_lending_operational(
                ticker, sg, sector_profile, flags
            )

        # ── GYO özel yolu ──────────────────────────────────────────────────────
        if sg == "gyo":
            return self._calculate_gyo(ticker, sg, flags)

        # ── Insurance özel yolu ─────────────────────────────────────────────
        if sg == "insurance":
            return self._calculate_insurance(ticker, sg, flags)

        # ── Investment Trust özel yolu ──────────────────────────────────────
        if sg == "investment_trust":
            return self._calculate_investment_trust(ticker, sg, flags)

        # ── Guard: henüz modeli olmayan gruplar ────────────────────────────
        if sg in _UNSUPPORTED_GROUPS:
            flags.append(
                f"{sg} sektör grubu için finansal skor modeli henüz "
                "aktif değildir."
            )
            return self._empty_result(ticker, sg, flags, "model henüz aktif değil")

        # ── V1 genişletilmiş gruplar: industrial modele eşle + flag ───────
        compute_sg = _COMPUTE_GROUP_MAP.get(sg, sg)
        if compute_sg != sg:
            flags.append(_V1_OPERATIONAL_FLAG)

        data = self._fetch_data(ticker, sg, flags)
        if data is None:
            return self._empty_result(ticker, sg, flags, "veri çekilemedi")

        # Alt skorlar + (reason, metric_quality) — 3-tuple
        # compute_sg ile hesapla (industrial model fallback dahil)
        prof_s,  prof_r,  prof_q  = self._compute_profitability(data, compute_sg, flags)
        bs_s,    bs_r,    bs_q    = self._compute_balance_sheet(data, compute_sg, flags)
        cf_s,    cf_r,    cf_q    = self._compute_cash_flow(data, compute_sg, flags)
        grow_s,  grow_r,  grow_q  = self._compute_growth(data, flags, compute_sg)
        val_s,   val_r,   val_q   = self._compute_valuation(data, compute_sg, flags)
        stab_s,  stab_r,  stab_q  = self._compute_stability(data, flags, compute_sg)
        piotr    = self._compute_piotroski(data, compute_sg, flags)

        # Piotroski kalite mantığı: coverage → quality, applicability → reason
        if piotr is not None:
            piotr_s = piotr.normalized
            if piotr.applicability == "not_applicable":
                piotr_r = "not_applicable"
                piotr_q = 1.0
            elif piotr.normalized is not None:
                piotr_r = None
                piotr_q = piotr.coverage   # coverage-weighted quality
            else:
                piotr_r = "missing"
                piotr_q = 0.0
        else:
            # Sadece exception path'te None kalır
            piotr_s = None
            piotr_r = "missing"
            piotr_q = 0.0

        reasons = {
            "profitability": (prof_s,  prof_r,  prof_q),
            "balance_sheet": (bs_s,    bs_r,    bs_q),
            "cash_flow":     (cf_s,    cf_r,    cf_q),
            "growth":        (grow_s,  grow_r,  grow_q),
            "valuation":     (val_s,   val_r,   val_q),
            "stability":     (stab_s,  stab_r,  stab_q),
            "piotroski":     (piotr_s, piotr_r, piotr_q),
        }
        final_score, quality = self._weighted_average(reasons, _WEIGHTS)

        if quality < 0.30:
            final_score = None
            flags.append(
                "Finansal skor hesaplanamadı: veri kalitesi eşiğin altında "
                f"(quality={quality:.2f})."
            )
        elif quality < 0.50:
            flags.append(
                "Finansal skor sınırlı veriyle hesaplandığı için "
                "güvenilirlik düşüktür."
            )

        if final_score is not None:
            final_score = round(max(0.0, min(10.0, final_score)), 2)

        subscores = FundamentalSubscores(
            profitability = _r2(prof_s),
            balance_sheet = _r2(bs_s),
            cash_flow     = _r2(cf_s),
            growth        = _r2(grow_s),
            valuation     = _r2(val_s),
            stability     = _r2(stab_s),
            piotroski     = _r2(piotr_s),
        )

        explanation = self._explain(subscores, piotr, compute_sg)
        # Güvenlik: açıklamada yasak kelime olmamalı
        if _contains_forbidden(explanation):
            explanation = "Finansal tablo verisiyle değerlendirme yapıldı."

        return FundamentalResult(
            ticker=ticker,
            financial_score=final_score,
            financial_score_label=self._label(final_score),
            financial_score_quality=round(quality, 2),
            subscores=subscores,
            piotroski=piotr,
            financial_flags=flags,
            explanation=explanation,
            sector_group=sg,           # Firestore canonical değeri korunur
            data_source=data.get("data_source", "borsapy_yearly"),
            period=data.get("period"),
        )

    # ── Sektör grubu belirleme ──────────────────────────────────────────────

    def _get_sector_group(self, sektor: Optional[str]) -> str:
        if not sektor:
            return "unknown"
        # Firestore'dan gelen canonical değerleri doğrudan geçir
        stripped = str(sektor).strip()
        if stripped in _CANONICAL_SECTOR_GROUPS:
            return stripped
        s = _normalize_tr(sektor)
        if s in _SECTOR_EXACT:
            return _SECTOR_EXACT[s]
        for key, group in _SECTOR_MAP.items():
            if key in s or s in key:
                return group
        return "industrial"

    # ── Veri çekme ─────────────────────────────────────────────────────────

    def _fetch_data(
        self,
        ticker:       str,
        sector_group: str,
        flags:        List[str],
    ) -> Optional[dict]:
        # ── 1. Primary: İş Yatırım (unknown sektörde atla) ───────────────────
        if sector_group != "unknown":
            d = self._fetch_isyatirim(ticker, sector_group, flags)
            if d is not None:
                return d
            flags.append(
                "İş Yatırım finansal verisi alınamadı; fallback kaynak kullanıldı."
            )

        # ── 2. Fallback sırası sektöre göre ──────────────────────────────────
        if sector_group == "bank":
            # Banka fallback: borsapy_banking → yfinance
            d = self._fetch_banking(ticker, flags)
            if d is not None:
                return d
            return self._fetch_yfinance_quarterly(ticker, sector_group, flags)

        if sector_group == "insurance":
            # Sigorta fallback: borsapy_standard → yfinance
            d = self._fetch_standard(ticker, flags)
            if d is not None:
                return d
            return self._fetch_yfinance_quarterly(ticker, sector_group, flags)

        # Sanayi / GYO / Holding / unknown fallback: yfinance → borsapy
        d = self._fetch_yfinance_quarterly(ticker, sector_group, flags)
        if d is not None:
            return d
        return self._fetch_standard(ticker, flags)

    def _fetch_yfinance_quarterly(
        self,
        ticker:       str,
        sector_group: str,
        flags:        List[str],
    ) -> Optional[dict]:
        try:
            import yfinance as yf
            yf_symbol = _to_yfinance_symbol(ticker)
            t = yf.Ticker(yf_symbol)

            is_q = t.get_income_stmt(freq="quarterly")
            bs_q = t.get_balance_sheet(freq="quarterly")
            cf_q = t.get_cash_flow(freq="quarterly")

            # Fallback to property attributes if method returns empty
            if is_q is None or is_q.empty:
                is_q = getattr(t, "quarterly_income_stmt", None)
            if bs_q is None or bs_q.empty:
                bs_q = getattr(t, "quarterly_balance_sheet", None)
            if cf_q is None or cf_q.empty:
                cf_q = getattr(t, "quarterly_cashflow", None)

            if is_q is None or is_q.empty or bs_q is None or bs_q.empty:
                flags.append(f"yfinance quarterly gelir tablosu veya bilanço boş döndü ({yf_symbol}).")
                return None

            if cf_q is not None and cf_q.empty:
                cf_q = None

            period = _detect_latest_period(is_q, bs_q, cf_q)
            if period is None:
                return None

            last_price: Optional[float] = None
            try:
                v = t.fast_info.last_price
                last_price = float(v) if v else None
            except Exception:
                pass

            # Valuation için info alanları (trailingPE, priceToBook, marketCap)
            yf_info: dict = {}
            if last_price:
                yf_info["last"] = last_price
            try:
                raw_info = t.info or {}
                for k in ("trailingPE", "priceToBook", "marketCap"):
                    v = raw_info.get(k)
                    if v is not None:
                        try:
                            fv = float(v)
                            if np.isfinite(fv) and fv > 0:
                                yf_info[k] = fv
                        except (TypeError, ValueError):
                            pass
            except Exception:
                pass

            # Growth fallback için yıllık tablolar
            is_y: Optional[pd.DataFrame] = None
            bs_y: Optional[pd.DataFrame] = None
            try:
                _is_y = t.get_income_stmt(freq="yearly")
                if _is_y is not None and not _is_y.empty:
                    is_y = _is_y
            except Exception:
                pass
            try:
                _bs_y = t.get_balance_sheet(freq="yearly")
                if _bs_y is not None and not _bs_y.empty:
                    bs_y = _bs_y
            except Exception:
                pass

            flags.append(f"Veri kaynağı son finansal dönem olarak {period} verisini döndürdü.")
            return {
                "bs":          bs_q,
                "is_":         is_q,
                "cf":          cf_q,
                "info":        yf_info if yf_info else None,
                "is_y":        is_y,
                "bs_y":        bs_y,
                "period":      period,
                "data_source": "yfinance_quarterly",
                "yf":          True,
            }
        except Exception as e:
            logger.debug(f"[fundamental] {ticker} yfinance quarterly fetch: {e}")
            return None

    def _fetch_standard(self, ticker: str, flags: List[str]) -> Optional[dict]:
        try:
            import borsapy as bp
            t   = bp.Ticker(ticker)
            bs  = t.balance_sheet
            is_ = t.income_stmt
            if bs is None or bs.empty or is_ is None or is_.empty:
                return None
            info = getattr(t, "info", None)
            cf = None
            try:
                cf = t.get_cashflow()
                if cf is not None and cf.empty:
                    cf = None
            except Exception as e:
                logger.debug(f"[fundamental] {ticker} cashflow: {e}")
            period = _detect_latest_period(is_, bs, cf)
            if period is None:
                period = str(is_.columns[0]) if not is_.empty else str(bs.columns[0])
            flags.append(f"Veri kaynağı son finansal dönem olarak {period} verisini döndürdü.")
            return {
                "bs":          bs,
                "is_":         is_,
                "cf":          cf,
                "info":        info,
                "period":      period,
                "data_source": "borsapy_yearly",
            }
        except Exception as e:
            logger.warning(f"[fundamental] {ticker} standart fetch: {e}")
            return None

    def _fetch_banking(self, ticker: str, flags: List[str]) -> Optional[dict]:
        try:
            import borsapy as bp
            t   = bp.Ticker(ticker)
            bs  = None
            is_ = None
            for fg in ("UFRS", "TMS_17", "UFRS_B"):
                try:
                    _bs  = t.get_balance_sheet(financial_group=fg)
                    _is  = t.get_income_stmt(financial_group=fg)
                    if (_bs is not None and not _bs.empty and
                            _is is not None and not _is.empty):
                        bs, is_ = _bs, _is
                        break
                except Exception:
                    continue
            if bs is None or is_ is None:
                return None
            info = getattr(t, "info", None)
            period = _detect_latest_period(is_, bs)
            if period is None:
                period = str(bs.columns[0])
            flags.append(f"Veri kaynağı son finansal dönem olarak {period} verisini döndürdü.")
            return {
                "bs":          bs,
                "is_":         is_,
                "cf":          None,   # bankalar için mevcut değil
                "info":        info,
                "period":      period,
                "data_source": "borsapy_yearly",
            }
        except Exception as e:
            logger.warning(f"[fundamental] {ticker} banking fetch: {e}")
            return None

    def _fetch_isyatirim(
        self,
        ticker:       str,
        sector_group: str,
        flags:        List[str],
    ) -> Optional[dict]:
        """İş Yatırım finansal tabloları — primary kaynak adapter."""
        try:
            from isyatirimhisse import fetch_financials as _iy_fetch

            # Sektöre göre financial_group: banka/sigorta → UFRS('2'), diğerleri → XI_29('1')
            fg = "2" if sector_group in ("bank", "insurance") else "1"

            df_raw = _iy_fetch(
                symbols=[ticker],
                start_year="2022",
                end_year="2026",
                exchange="TRY",
                financial_group=fg,
            )

            if df_raw is None or df_raw.empty:
                return None

            # Sembol filtrele
            sym_col = next(
                (c for c in df_raw.columns if c.upper() == "SYMBOL"), None
            )
            df_sym = (
                df_raw[df_raw[sym_col] == ticker].copy()
                if sym_col else df_raw.copy()
            )
            if df_sym.empty:
                return None

            # Dönem kolonları: "2022/3", "2022/6", ...
            period_cols = [
                c for c in df_sym.columns
                if re.match(r"^\d{4}/\d+$", str(c))
            ]
            if not period_cols:
                return None

            # Yeniden eskiye sırala (borsapy kolonları gibi newest-first)
            period_cols_sorted = sorted(
                period_cols,
                key=lambda c: tuple(int(x) for x in str(c).split("/")),
                reverse=True,
            )

            tr_col = next(
                (c for c in df_sym.columns if "NAME_TR" in c.upper()), None
            )
            en_col = next(
                (c for c in df_sym.columns if "NAME_EN" in c.upper()), None
            )
            if not tr_col:
                return None

            # TR isimleri → index
            df_tr = (
                df_sym[[tr_col] + period_cols_sorted]
                .copy()
                .set_index(tr_col)
            )
            df_tr.index = df_tr.index.fillna("").astype(str).str.strip()

            # EN isimleri → ek satırlar (TR'de olmayan)
            parts = [df_tr]
            if en_col:
                df_en = df_sym[[en_col] + period_cols_sorted].copy()
                df_en = df_en[
                    df_en[en_col].notna() &
                    (df_en[en_col].astype(str).str.strip() != "") &
                    (df_en[en_col].astype(str).str.strip() != "None")
                ].copy()
                if not df_en.empty:
                    df_en = df_en.set_index(en_col)
                    df_en.index = df_en.index.astype(str).str.strip()
                    new_en = df_en[~df_en.index.isin(df_tr.index)]
                    if not new_en.empty:
                        parts.append(new_en)

            df_combined = pd.concat(parts) if len(parts) > 1 else df_tr

            # Sayısal dönüşüm — güvenli
            for col in period_cols_sorted:
                df_combined[col] = pd.to_numeric(
                    df_combined[col], errors="coerce"
                )

            # En güncel dönemi tespit et
            period = _detect_latest_period(df_combined)
            if period is None and period_cols_sorted:
                t = _parse_col_period(period_cols_sorted[0])
                period = t[2] if t else str(period_cols_sorted[0])

            n_periods = len(period_cols_sorted)
            flags.append(
                f"İş Yatırım finansal verisi kullanıldı. "
                f"Son dönem: {period}  ({n_periods} çeyrek, group='{fg}')"
            )

            # Valuation için piyasa verisi (yfinance anlık, hata olursa boş)
            yf_info: dict = {}
            try:
                import yfinance as yf
                t_yf = yf.Ticker(_to_yfinance_symbol(ticker))
                lp = getattr(t_yf.fast_info, "last_price", None)
                if lp:
                    yf_info["last"] = float(lp)
                raw = t_yf.info or {}
                for k in ("trailingPE", "priceToBook", "marketCap"):
                    v = raw.get(k)
                    if v is not None:
                        try:
                            fv = float(v)
                            if np.isfinite(fv) and fv > 0:
                                yf_info[k] = fv
                        except (TypeError, ValueError):
                            pass
            except Exception:
                pass

            return {
                "bs":          df_combined,
                "is_":         df_combined,
                "cf":          df_combined,   # CF satırları aynı df içinde
                "info":        yf_info if yf_info else None,
                "period":      period,
                "data_source": "isyatirim_quarterly",
                "isyat":       True,
                "n_periods":   n_periods,
            }

        except Exception as e:
            logger.warning(f"[fundamental] {ticker} isyatirim fetch: {e}")
            return None

    # ── Alt skor: Karlılık ──────────────────────────────────────────────────

    def _compute_profitability(
        self,
        data:         dict,
        sector_group: str,
        flags:        List[str],
    ) -> Tuple[Optional[float], Optional[str], float]:
        try:
            if data.get("yf"):
                return self._profitability_yfinance(data, sector_group, flags)
            if sector_group == "bank":
                return self._profitability_bank(data)
            return self._profitability_standard(data)
        except Exception as e:
            logger.warning(f"[fundamental] profitability: {e}")
            return None, "missing", 0.0

    def _profitability_yfinance(
        self, data: dict, sector_group: str, flags: List[str]
    ) -> Tuple[Optional[float], Optional[str]]:
        is_ = data["is_"]
        bs  = data["bs"]

        net_income   = _yf_ttm(is_, YF_NET_INCOME_KEYS)
        total_assets = _yf_get(bs,  YF_TOTAL_ASSETS_KEYS)
        equity       = _yf_get(bs,  YF_TOTAL_EQUITY_KEYS)

        scored: List[Tuple[float, float]] = []
        miss = 0

        def add(v, th, w=1.0):
            nonlocal miss
            s = _normalize(v, *_T[th])
            if s is not None:
                scored.append((s, w))
            else:
                miss += 1

        n_total: int
        if sector_group == "bank":
            n_total = 4
            net_interest = _yf_ttm(is_, YF_NET_INTEREST_INCOME_KEYS)
            total_income = _yf_ttm(is_, YF_REVENUE_KEYS) or net_interest
            add(_safe_div(net_income, equity),         "roe", w=0.35)
            add(_safe_div(net_income, total_assets),   "roa", w=0.25)
            add(_safe_div(net_interest, total_assets), "nim", w=0.25)
            add(_safe_div(net_income, total_income),   "nkm", w=0.15)
        else:
            n_total = 5
            revenue      = _yf_ttm(is_, YF_REVENUE_KEYS)
            gross_profit = _yf_ttm(is_, YF_GROSS_PROFIT_KEYS)
            op_income    = _yf_ttm(is_, YF_OPERATING_INCOME_KEYS)
            add(_safe_div(net_income, equity),       "roe",          w=0.30)
            add(_safe_div(net_income, total_assets), "roa",          w=0.20)
            add(_safe_div(net_income, revenue),      "nkm",          w=0.20)
            add(_safe_div(op_income,  revenue),      "op_margin",    w=0.15)
            add(_safe_div(gross_profit, revenue),    "gross_margin", w=0.15)

        if not scored:
            return None, "missing", 0.0
        mq = round(len(scored) / n_total, 2)
        tw = sum(w for _, w in scored)
        return round(sum(s * w for s, w in scored) / tw, 2), None, mq

    def _profitability_standard(
        self, data: dict
    ) -> Tuple[Optional[float], Optional[str]]:
        bs, is_ = data["bs"], data["is_"]

        net_kar  = _get_row(is_, _NET_PROFIT_KEYS)
        satis    = _get_row(is_, _REVENUE_KEYS)
        brut     = _get_row(is_, _GROSS_PROFIT_KEYS)
        faaliyet = _get_row(is_, _OPERATING_PROFIT_KEYS)
        toplam_v = _get_row(bs,  _TOTAL_ASSETS_KEYS)
        ozkayn   = _get_row(bs,  _EQUITY_KEYS)

        scored: List[Tuple[float, float]] = []
        miss = 0

        def add(value, th_key, reverse=False, weight=1.0):
            nonlocal miss
            s = _normalize(value, *_T[th_key], reverse=reverse)
            if s is not None:
                scored.append((s, weight))
            else:
                miss += 1

        add(_safe_div(net_kar, ozkayn),  "roe",          weight=0.30)
        add(_safe_div(net_kar, toplam_v),"roa",          weight=0.20)
        add(_safe_div(net_kar, satis),   "nkm",          weight=0.20)
        add(_safe_div(faaliyet, satis),  "op_margin",    weight=0.15)
        add(_safe_div(brut, satis),      "gross_margin", weight=0.15)

        if not scored:
            return None, "missing", 0.0
        mq = round(len(scored) / 5, 2)
        tw = sum(w for _, w in scored)
        return round(sum(s * w for s, w in scored) / tw, 2), None, mq

    def _profitability_bank(
        self, data: dict
    ) -> Tuple[Optional[float], Optional[str]]:
        bs, is_ = data["bs"], data["is_"]

        net_kar  = _get_row(is_, _BANK_NET_PROFIT_KEYS)
        ozkayn   = _get_row(bs,  _BANK_EQUITY_KEYS)
        toplam_v = _get_row(bs,  _BANK_TOTAL_ASSETS_KEYS)
        net_faiz = _get_row(is_, _BANK_NET_INTEREST_KEYS)
        top_gel  = _get_row(is_, _BANK_TOTAL_INCOME_KEYS)

        scored: List[Tuple[float, float]] = []
        miss = 0

        def add(value, th_key, weight=1.0):
            nonlocal miss
            s = _normalize(value, *_T[th_key])
            if s is not None:
                scored.append((s, weight))
            else:
                miss += 1

        add(_safe_div(net_kar, ozkayn),   "roe", weight=0.35)
        add(_safe_div(net_kar, toplam_v), "roa", weight=0.25)
        add(_safe_div(net_faiz, toplam_v),"nim", weight=0.25)
        add(_safe_div(net_kar, top_gel),  "nkm", weight=0.15)

        if not scored:
            return None, "missing", 0.0
        mq = round(len(scored) / 4, 2)
        tw = sum(w for _, w in scored)
        return round(sum(s * w for s, w in scored) / tw, 2), None, mq

    # ── Alt skor: Bilanço Sağlığı ───────────────────────────────────────────

    def _compute_balance_sheet(
        self,
        data:         dict,
        sector_group: str,
        flags:        List[str],
    ) -> Tuple[Optional[float], Optional[str], float]:
        if sector_group in ("bank", "insurance"):
            return None, "not_applicable", 1.0
        try:
            if data.get("yf"):
                return self._balance_sheet_yfinance(data, flags)
            bs, is_, cf = data["bs"], data["is_"], data.get("cf")

            ozkayn   = _get_row(bs,  _EQUITY_KEYS)
            doenen   = _get_row(bs,  _CURRENT_ASSETS_KEYS)
            kv_liab  = _get_row(bs,  _CURRENT_LIAB_KEYS)
            nakit    = _get_row(bs,  _CASH_KEYS)
            faaliyet = _get_row(is_, _OPERATING_PROFIT_KEYS)
            fin_gid  = _get_row(is_, _FIN_EXPENSE_KEYS)
            # borsapy'de _sum_key_latest (KV+UV toplar); isyatirimhisse'de _get_row
            fin_borc = (
                _get_row(bs, _FIN_DEBT_KEYS)
                if data.get("isyat")
                else _sum_key_latest(bs, "Finansal Borçlar")
            )
            amort    = _get_row(cf, _AMORTIZATION_KEYS) if cf is not None else None

            scored: List[Tuple[float, float]] = []
            miss = 0

            def add(value, th_key, reverse=False, weight=1.0):
                nonlocal miss
                s = _normalize(value, *_T[th_key], reverse=reverse)
                if s is not None:
                    scored.append((s, weight))
                else:
                    miss += 1

            # Borç/Özkaynak (reverse)
            if fin_borc is not None and ozkayn and ozkayn > 0:
                add(fin_borc / ozkayn, "debt_equity", reverse=True, weight=0.30)
            else:
                miss += 1

            # Cari oran
            if doenen is not None and kv_liab and kv_liab > 0:
                add(doenen / kv_liab, "current_ratio", weight=0.25)
            else:
                miss += 1

            # Faiz karşılama
            if faaliyet is not None and fin_gid is not None:
                fin_gid_abs = abs(fin_gid)
                if fin_gid_abs > 0:
                    add(faaliyet / fin_gid_abs, "interest_cov", weight=0.25)
                else:
                    miss += 1
            else:
                miss += 1

            # Net borç / FAVÖK (reverse)
            if (fin_borc is not None and nakit is not None and
                    faaliyet is not None and amort is not None):
                favok = faaliyet + amort
                if favok > 0:
                    nd = fin_borc - nakit
                    add(nd / favok, "nd_ebitda", reverse=True, weight=0.20)
                else:
                    miss += 1
            else:
                miss += 1

            if not scored:
                return None, "missing", 0.0
            mq = round(len(scored) / 4, 2)
            tw = sum(w for _, w in scored)
            return round(sum(s * w for s, w in scored) / tw, 2), None, mq

        except Exception as e:
            logger.warning(f"[fundamental] balance_sheet: {e}")
            return None, "missing", 0.0

    def _balance_sheet_yfinance(
        self, data: dict, flags: List[str]
    ) -> Tuple[Optional[float], Optional[str]]:
        is_ = data["is_"]
        bs  = data["bs"]
        cf  = data.get("cf")

        equity      = _yf_get(bs, YF_TOTAL_EQUITY_KEYS)
        curr_assets = _yf_get(bs, YF_CURRENT_ASSETS_KEYS)
        curr_liab   = _yf_get(bs, YF_CURRENT_LIABILITIES_KEYS)
        total_debt  = _yf_get(bs, YF_TOTAL_DEBT_KEYS)
        ebitda      = _yf_ttm(is_, YF_EBITDA_KEYS)
        op_income   = _yf_ttm(is_, YF_OPERATING_INCOME_KEYS)
        int_exp     = _yf_ttm(is_, YF_INTEREST_EXPENSE_KEYS)

        scored: List[Tuple[float, float]] = []
        miss = 0

        def add(v, th, reverse=False, w=1.0):
            nonlocal miss
            s = _normalize(v, *_T[th], reverse=reverse)
            if s is not None:
                scored.append((s, w))
            else:
                miss += 1

        if total_debt is not None and equity and equity > 0:
            add(total_debt / equity, "debt_equity", reverse=True, w=0.30)
        else:
            miss += 1

        if curr_assets is not None and curr_liab and curr_liab > 0:
            add(curr_assets / curr_liab, "current_ratio", w=0.25)
        else:
            miss += 1

        if op_income is not None and int_exp is not None:
            int_abs = abs(int_exp)
            if int_abs > 0:
                add(op_income / int_abs, "interest_cov", w=0.25)
            else:
                miss += 1
        else:
            miss += 1

        if total_debt is not None and ebitda and ebitda > 0:
            add(total_debt / ebitda, "nd_ebitda", reverse=True, w=0.20)
        else:
            miss += 1

        if not scored:
            return None, "missing", 0.0
        mq = round(len(scored) / 4, 2)
        tw = sum(w for _, w in scored)
        return round(sum(s * w for s, w in scored) / tw, 2), None, mq

    # ── Alt skor: Nakit Akışı ───────────────────────────────────────────────

    def _compute_cash_flow(
        self,
        data:         dict,
        sector_group: str,
        flags:        List[str],
    ) -> Tuple[Optional[float], Optional[str], float]:
        if sector_group in ("bank", "insurance"):
            return None, "not_applicable", 1.0
        try:
            if data.get("yf"):
                return self._cash_flow_yfinance(data, flags)
            cf = data.get("cf")
            if cf is None:
                return None, "missing", 0.0

            is_   = data["is_"]
            satis   = _get_row(is_, _REVENUE_KEYS)
            net_kar = _get_row(is_, _NET_PROFIT_KEYS)
            op_cf   = _get_row(cf,  _OPERATING_CF_KEYS)
            fcf     = _get_row(cf,  _FCF_KEYS)

            scored: List[Tuple[float, float]] = []
            miss = 0

            # İşletme CF pozitif?
            if op_cf is not None:
                scored.append((10.0 if op_cf > 0 else 0.0, 0.35))
            else:
                miss += 1

            # FCF pozitif?
            if fcf is not None:
                scored.append((10.0 if fcf > 0 else 0.0, 0.30))
            else:
                miss += 1

            # FCF / Net Kar (earnings quality)
            if fcf is not None and net_kar and net_kar > 0:
                s = _normalize(_safe_div(fcf, net_kar), *_T["fcf_nk"])
                if s is not None:
                    scored.append((s, 0.20))
                else:
                    miss += 1
            else:
                miss += 1

            # FCF / Satışlar
            if fcf is not None and satis and satis > 0:
                s = _normalize(_safe_div(fcf, satis), *_T["fcf_margin"])
                if s is not None:
                    scored.append((s, 0.15))
                else:
                    miss += 1
            else:
                miss += 1

            if not scored:
                return None, "missing", 0.0
            mq = round(len(scored) / 4, 2)
            tw = sum(w for _, w in scored)
            return round(sum(s * w for s, w in scored) / tw, 2), None, mq

        except Exception as e:
            logger.warning(f"[fundamental] cash_flow: {e}")
            return None, "missing", 0.0

    def _cash_flow_yfinance(
        self, data: dict, flags: List[str]
    ) -> Tuple[Optional[float], Optional[str]]:
        is_ = data["is_"]
        cf  = data.get("cf")

        if cf is None:
            return None, "missing"

        revenue    = _yf_ttm(is_, YF_REVENUE_KEYS)
        net_income = _yf_ttm(is_, YF_NET_INCOME_KEYS)
        op_cf      = _yf_ttm(cf,  YF_OPERATING_CASHFLOW_KEYS)
        fcf        = _yf_ttm(cf,  YF_FREE_CASHFLOW_KEYS)

        scored: List[Tuple[float, float]] = []
        miss = 0

        if op_cf is not None:
            scored.append((10.0 if op_cf > 0 else 0.0, 0.35))
        else:
            miss += 1

        if fcf is not None:
            scored.append((10.0 if fcf > 0 else 0.0, 0.30))
        else:
            miss += 1

        if fcf is not None and net_income and net_income > 0:
            s = _normalize(_safe_div(fcf, net_income), *_T["fcf_nk"])
            if s is not None:
                scored.append((s, 0.20))
            else:
                miss += 1
        else:
            miss += 1

        if fcf is not None and revenue and revenue > 0:
            s = _normalize(_safe_div(fcf, revenue), *_T["fcf_margin"])
            if s is not None:
                scored.append((s, 0.15))
            else:
                miss += 1
        else:
            miss += 1

        if not scored:
            return None, "missing", 0.0
        mq = round(len(scored) / 4, 2)
        tw = sum(w for _, w in scored)
        return round(sum(s * w for s, w in scored) / tw, 2), None, mq

    # ── Alt skor: Büyüme ────────────────────────────────────────────────────

    def _compute_growth(
        self,
        data:         dict,
        flags:        List[str],
        sector_group: str = "",
    ) -> Tuple[Optional[float], Optional[str], float]:
        try:
            if data.get("yf"):
                return self._growth_yfinance(data, flags)
            if data.get("isyat"):
                return self._growth_isyatirim(data, flags, sector_group)
            bs, is_ = data["bs"], data["is_"]
            n = min(bs.shape[1], is_.shape[1])
            if n < 2:
                return None, "missing", 0.0

            def series(df, keys):
                return [_get_row_period(df, keys, i) for i in range(n)]

            def yoy_avg(vals: List[Optional[float]]) -> Optional[float]:
                rates = []
                for i in range(len(vals) - 1):
                    c, p = vals[i], vals[i + 1]
                    if c is not None and p is not None and p != 0:
                        r = (c - p) / abs(p)
                        rates.append(max(-1.0, min(5.0, r)))
                return float(np.mean(rates)) if rates else None

            satis_rates  = yoy_avg(series(is_, _REVENUE_KEYS))
            kar_rates    = yoy_avg(series(is_, _NET_PROFIT_KEYS))
            ozk_rates    = yoy_avg(series(bs,  _EQUITY_KEYS))

            scored: List[Tuple[float, float]] = []
            miss = 0

            for rate, weight in [(satis_rates, 0.40), (kar_rates, 0.40), (ozk_rates, 0.20)]:
                s = _normalize(rate, *_T["growth"])
                if s is not None:
                    scored.append((s, weight))
                else:
                    miss += 1

            if not scored:
                return None, "missing", 0.0
            mq = round(len(scored) / 3, 2)
            tw = sum(w for _, w in scored)
            score = sum(s * w for s, w in scored) / tw
            score = min(score, 9.5)
            return round(score, 2), None, mq

        except Exception as e:
            logger.warning(f"[fundamental] growth: {e}")
            return None, "missing", 0.0

    def _growth_yfinance(
        self, data: dict, flags: List[str]
    ) -> Tuple[Optional[float], Optional[str], float]:
        is_  = data["is_"]
        bs   = data["bs"]
        is_y = data.get("is_y")
        bs_y = data.get("bs_y")
        n_is = is_.shape[1]
        n_bs = bs.shape[1]

        def ttm_at(df, keys, start):
            return _yf_ttm(df, keys, start=start, n=4, min_q=2)

        def yf_get_at(df, keys, col):
            """Belirli kolon index'indeki değer."""
            if df is None:
                return None
            for k in keys:
                if k in df.index and col < df.shape[1]:
                    v = df.loc[k].iloc[col]
                    return float(v) if pd.notna(v) else None
            return None

        scored: List[Tuple[float, float]] = []
        miss = 0
        used_yearly = False

        def add_growth(curr, prior, w):
            nonlocal miss
            if curr is not None and prior is not None and prior != 0:
                r = max(-1.0, min(5.0, (curr - prior) / abs(prior)))
                s = _normalize(r, *_T["growth"])
                if s is not None:
                    scored.append((s, w))
                    return
            miss += 1

        # ── Revenue YoY ──────────────────────────────────────────────────────
        rev_curr  = ttm_at(is_, YF_REVENUE_KEYS, 0)
        rev_prior = ttm_at(is_, YF_REVENUE_KEYS, 4) if n_is >= 8 else None
        if (rev_curr is None or rev_prior is None) and is_y is not None and is_y.shape[1] >= 2:
            rc = _yf_get(is_y, YF_REVENUE_KEYS)
            rp = yf_get_at(is_y, YF_REVENUE_KEYS, 1)
            if rc is not None and rp is not None:
                rev_curr, rev_prior, used_yearly = rc, rp, True
        add_growth(rev_curr, rev_prior, 0.40)

        # ── Net Income YoY ───────────────────────────────────────────────────
        ni_curr  = ttm_at(is_, YF_NET_INCOME_KEYS, 0)
        ni_prior = ttm_at(is_, YF_NET_INCOME_KEYS, 4) if n_is >= 8 else None
        if (ni_curr is None or ni_prior is None) and is_y is not None and is_y.shape[1] >= 2:
            nc = _yf_get(is_y, YF_NET_INCOME_KEYS)
            np_ = yf_get_at(is_y, YF_NET_INCOME_KEYS, 1)
            if nc is not None and np_ is not None:
                ni_curr, ni_prior, used_yearly = nc, np_, True
        add_growth(ni_curr, ni_prior, 0.40)

        # ── Equity YoY ───────────────────────────────────────────────────────
        eq_curr  = _yf_get(bs, YF_TOTAL_EQUITY_KEYS)
        eq_prior = yf_get_at(bs, YF_TOTAL_EQUITY_KEYS, 4) if n_bs >= 5 else None
        if (eq_curr is None or eq_prior is None) and bs_y is not None and bs_y.shape[1] >= 2:
            ec = _yf_get(bs_y, YF_TOTAL_EQUITY_KEYS)
            ep = yf_get_at(bs_y, YF_TOTAL_EQUITY_KEYS, 1)
            if eq_curr is None and ec is not None:
                eq_curr, used_yearly = ec, True
            if eq_prior is None and ep is not None:
                eq_prior, used_yearly = ep, True
        add_growth(eq_curr, eq_prior, 0.20)

        if used_yearly:
            flags.append(
                "Growth skorunda çeyreklik veri yetersiz olduğu için "
                "yıllık veri destekleyici olarak kullanıldı."
            )

        if not scored:
            return None, "missing", 0.0
        mq = round(len(scored) / 3, 2)
        tw = sum(w for _, w in scored)
        return round(min(sum(s * w for s, w in scored) / tw, 9.5), 2), None, mq

    def _growth_isyatirim(
        self, data: dict, flags: List[str], sector_group: str = ""
    ) -> Tuple[Optional[float], Optional[str], float]:
        """İş Yatırım çeyreklik verisiyle YoY büyüme (i vs i+4 = aynı çeyrek geçen yıl).

        Bank path: NI → _BANK_NET_PROFIT_KEYS, revenue → _BANK_TOTAL_INCOME_KEYS.
        """
        is_ = data["is_"]
        bs  = data["bs"]
        n   = is_.shape[1]   # genellikle 17

        # Banka için sektöre özel key listeleri
        if sector_group == "bank":
            ni_keys  = _BANK_NET_PROFIT_KEYS
            rev_keys = _BANK_TOTAL_INCOME_KEYS
        else:
            ni_keys  = _NET_PROFIT_KEYS
            rev_keys = _REVENUE_KEYS

        def get_at(df: pd.DataFrame, keys: List[str], col: int) -> Optional[float]:
            if col >= df.shape[1]:
                return None
            idx = df.index.str.strip()
            for key in keys:
                matches = df[idx == key.strip()]
                if not matches.empty:
                    v = matches.iloc[0, col]
                    return float(v) if pd.notna(v) else None
            return None

        def yoy(curr: Optional[float], prior: Optional[float]) -> Optional[float]:
            if curr is None or prior is None or prior == 0:
                return None
            return max(-1.0, min(5.0, (curr - prior) / abs(prior)))

        rev_yoys: List[float] = []
        ni_yoys:  List[float] = []
        eq_yoys:  List[float] = []

        for i in range(n - 4):
            r = yoy(get_at(is_, rev_keys,      i), get_at(is_, rev_keys,      i + 4))
            if r is not None:
                rev_yoys.append(r)
            r = yoy(get_at(is_, ni_keys,       i), get_at(is_, ni_keys,       i + 4))
            if r is not None:
                ni_yoys.append(r)
            r = yoy(get_at(bs,  _EQUITY_KEYS,  i), get_at(bs,  _EQUITY_KEYS,  i + 4))
            if r is not None:
                eq_yoys.append(r)

        def avg(lst: List[float]) -> Optional[float]:
            return float(np.mean(lst)) if lst else None

        scored: List[Tuple[float, float]] = []
        miss = 0
        for rate, w in [(avg(rev_yoys), 0.40), (avg(ni_yoys), 0.40), (avg(eq_yoys), 0.20)]:
            s = _normalize(rate, *_T["growth"])
            if s is not None:
                scored.append((s, w))
            else:
                miss += 1

        if not scored:
            return None, "missing", 0.0
        mq = round(len(scored) / 3, 2)
        tw = sum(w for _, w in scored)
        return round(min(sum(s * w for s, w in scored) / tw, 9.5), 2), None, mq

    # ── Alt skor: Değerleme ─────────────────────────────────────────────────

    def _compute_valuation(
        self,
        data:         dict,
        sector_group: str,
        flags:        List[str],
    ) -> Tuple[Optional[float], Optional[str], float]:
        try:
            if data.get("yf") or data.get("isyat"):
                return self._valuation_yfinance(data, sector_group, flags)
            bs, is_ = data["bs"], data["is_"]
            info    = data.get("info")

            net_kar = _get_row(is_, _NET_PROFIT_KEYS)
            ozkayn  = _get_row(bs,  _EQUITY_KEYS)
            odenmis = _get_row(bs,  _PAID_CAPITAL_KEYS)

            last_price: Optional[float] = None
            if info is not None:
                try:
                    v = (getattr(info, "last", None) or
                         (info.get("last") if hasattr(info, "get") else None))
                    last_price = float(v) if v else None
                except Exception:
                    pass

            fk_high   = _FK_HIGH.get(sector_group, 30.0)
            pddd_high = _PDDD_HIGH.get(sector_group, 4.0)

            scored: List[Tuple[float, float]] = []
            miss = 0

            # F/K (reverse) — negatif karda skip
            if (last_price and net_kar and net_kar > 0 and
                    odenmis and odenmis > 0):
                eps = net_kar / odenmis  # 1 TL nominal hisse başına kazanç
                if eps > 0:
                    fk = last_price / eps
                    s  = _normalize(fk, 0.0, fk_high, reverse=True)
                    if s is not None:
                        scored.append((s, 0.50))
                    else:
                        miss += 1
                else:
                    miss += 1
            else:
                miss += 1

            # PD/DD (reverse)
            if (last_price and odenmis and odenmis > 0 and
                    ozkayn and ozkayn > 0):
                pazar = last_price * odenmis
                pddd  = pazar / ozkayn
                s     = _normalize(pddd, 0.0, pddd_high, reverse=True)
                if s is not None:
                    scored.append((s, 0.50))
                else:
                    miss += 1
            else:
                miss += 1

            if not scored:
                return None, "missing", 0.0
            mq = round(len(scored) / 2, 2)
            tw = sum(w for _, w in scored)
            return round(sum(s * w for s, w in scored) / tw, 2), None, mq

        except Exception as e:
            logger.warning(f"[fundamental] valuation: {e}")
            return None, "missing", 0.0

    def _valuation_yfinance(
        self,
        data:         dict,
        sector_group: str,
        flags:        List[str],
    ) -> Tuple[Optional[float], Optional[str], float]:
        is_  = data["is_"]
        bs   = data["bs"]
        info = data.get("info") or {}

        fk_high   = _FK_HIGH.get(sector_group, 30.0)
        pddd_high = _PDDD_HIGH.get(sector_group, 4.0)

        scored: List[Tuple[float, float]] = []
        miss = 0

        # ── P/E (F/K) ────────────────────────────────────────────────────────
        # Öncelik 1: info.trailingPE
        trailing_pe = info.get("trailingPE") if isinstance(info, dict) else None
        pe_added = False
        if trailing_pe and np.isfinite(trailing_pe) and trailing_pe > 0:
            s = _normalize(trailing_pe, 0.0, fk_high, reverse=True)
            if s is not None:
                scored.append((s, 0.50))
                pe_added = True

        # Öncelik 2 / 3: manuel hesap (market_cap / TTM NI veya price × shares)
        if not pe_added:
            net_income = _yf_ttm(is_, YF_NET_INCOME_KEYS)
            shares     = _yf_get(bs, YF_SHARES_KEYS)
            last_price = info.get("last") if isinstance(info, dict) else None
            market_cap = info.get("marketCap") if isinstance(info, dict) else None

            pe: Optional[float] = None
            if market_cap and net_income and net_income > 0:
                pe = market_cap / net_income
            elif last_price and shares and shares > 0 and net_income and net_income > 0:
                eps = net_income / shares
                if eps > 0:
                    pe = last_price / eps

            if pe and pe > 0:
                s = _normalize(pe, 0.0, fk_high, reverse=True)
                if s is not None:
                    scored.append((s, 0.50))
                    pe_added = True

            if not pe_added:
                miss += 1
                if not last_price and not market_cap:
                    flags.append("yfinance değerleme: fiyat / piyasa değeri alınamadı.")

        # ── P/B (PD/DD) ───────────────────────────────────────────────────────
        # Öncelik 1: info.priceToBook
        price_to_book = info.get("priceToBook") if isinstance(info, dict) else None
        pb_added = False
        if price_to_book and np.isfinite(price_to_book) and price_to_book > 0:
            s = _normalize(price_to_book, 0.0, pddd_high, reverse=True)
            if s is not None:
                scored.append((s, 0.50))
                pb_added = True

        # Öncelik 2 / 3: manuel hesap
        if not pb_added:
            equity     = _yf_get(bs, YF_TOTAL_EQUITY_KEYS)
            shares     = _yf_get(bs, YF_SHARES_KEYS)
            last_price = info.get("last") if isinstance(info, dict) else None
            market_cap = info.get("marketCap") if isinstance(info, dict) else None

            pb: Optional[float] = None
            if market_cap and equity and equity > 0:
                pb = market_cap / equity
            elif last_price and shares and shares > 0 and equity and equity > 0:
                pb = (last_price * shares) / equity

            if pb and pb > 0:
                s = _normalize(pb, 0.0, pddd_high, reverse=True)
                if s is not None:
                    scored.append((s, 0.50))
                    pb_added = True

            if not pb_added:
                miss += 1

        if not scored:
            return None, "missing", 0.0
        mq = round(len(scored) / 2, 2)
        tw = sum(w for _, w in scored)
        return round(sum(s * w for s, w in scored) / tw, 2), None, mq

    # ── Alt skor: İstikrar ──────────────────────────────────────────────────

    def _compute_stability(
        self,
        data:         dict,
        flags:        List[str],
        sector_group: str = "",
    ) -> Tuple[Optional[float], Optional[str], float]:
        try:
            if data.get("yf"):
                return self._stability_yfinance(data, flags)
            bs, is_ = data["bs"], data["is_"]
            n = min(bs.shape[1], is_.shape[1])

            ozkayn_latest = _get_row(bs, _EQUITY_KEYS)
            if ozkayn_latest is not None and ozkayn_latest < 0:
                flags.append("Negatif özkaynak tespit edildi.")
                return 0.0, None, 1.0

            ni_keys   = _BANK_NET_PROFIT_KEYS if sector_group == "bank" else _NET_PROFIT_KEYS
            net_karlar = [_get_row_period(is_, ni_keys, i) for i in range(n)]
            valid      = [k for k in net_karlar if k is not None]
            if not valid:
                return None, "missing", 0.0

            scored: List[Tuple[float, float]] = []
            miss = 0

            loss_ratio = sum(1 for k in valid if k < 0) / len(valid)
            scored.append(((1.0 - loss_ratio) * 10.0, 0.50))

            if len(valid) >= 2:
                mean_abs = abs(float(np.mean(valid)))
                if mean_abs > 0:
                    cv = float(np.std(valid)) / mean_abs
                    s  = _normalize(cv, 0.0, 2.0, reverse=True)
                    if s is not None:
                        scored.append((s, 0.50))
                    else:
                        miss += 1
                else:
                    miss += 1
            else:
                miss += 1

            if not scored:
                return None, "missing", 0.0
            mq = round(len(scored) / 2, 2)
            tw = sum(w for _, w in scored)
            return round(sum(s * w for s, w in scored) / tw, 2), None, mq

        except Exception as e:
            logger.warning(f"[fundamental] stability: {e}")
            return None, "missing", 0.0

    def _stability_yfinance(
        self, data: dict, flags: List[str]
    ) -> Tuple[Optional[float], Optional[str], float]:
        is_ = data["is_"]
        bs  = data["bs"]

        equity = _yf_get(bs, YF_TOTAL_EQUITY_KEYS)
        if equity is not None and equity < 0:
            flags.append("Negatif özkaynak tespit edildi.")
            return 0.0, None, 1.0

        ni_vals: List[float] = []
        for key in YF_NET_INCOME_KEYS:
            if key in is_.index:
                ni_vals = [float(v) for v in is_.loc[key] if pd.notna(v)]
                break

        if not ni_vals:
            return None, "missing", 0.0

        scored: List[Tuple[float, float]] = []
        miss = 0

        loss_ratio = sum(1 for k in ni_vals if k < 0) / len(ni_vals)
        scored.append(((1.0 - loss_ratio) * 10.0, 0.50))

        if len(ni_vals) >= 3:
            mean_abs = abs(float(np.mean(ni_vals)))
            if mean_abs > 0:
                cv = float(np.std(ni_vals)) / mean_abs
                s = _normalize(cv, 0.0, 2.0, reverse=True)
                if s is not None:
                    scored.append((s, 0.50))
                else:
                    miss += 1
            else:
                miss += 1
        else:
            miss += 1

        if not scored:
            return None, "missing", 0.0
        mq = round(len(scored) / 2, 2)
        tw = sum(w for _, w in scored)
        return round(sum(s * w for s, w in scored) / tw, 2), None, mq

    # ── Alt skor: Piotroski ─────────────────────────────────────────────────

    def _compute_piotroski(
        self,
        data:         dict,
        sector_group: str,
        flags:        List[str],
    ) -> Optional[PiotroskiResult]:
        # ── Uygulanamaz sektörler ─────────────────────────────────────────
        if sector_group in _PIOTROSKI_NOT_APPLICABLE_GROUPS:
            msg = _PIOTROSKI_NA_MSGS.get(
                sector_group,
                f"{sector_group} sektör grubu için klasik Piotroski F-Score "
                "uygulanabilir değildir.",
            )
            flags.append(msg)
            return PiotroskiResult(
                score=None, normalized=None, calculated_criteria=0,
                total_criteria=9, coverage=0.0, confidence="not_applicable",
                applicability="not_applicable", missing_criteria=[], details={},
            )

        limited      = sector_group in _PIOTROSKI_LIMITED_GROUPS
        operational  = sector_group in _PIOTROSKI_OPERATIONAL_GROUPS

        try:
            if data.get("yf"):
                return self._piotroski_yfinance(data, flags, limited, operational)
            bs, is_, cf = data["bs"], data["is_"], data.get("cf")
            n_bs = bs.shape[1]
            n_is = is_.shape[1]

            details: Dict[str, Optional[int]] = {}
            p_score  = 0
            calc     = 0
            missing: List[str] = []

            def add(name: str, value: Optional[bool]) -> None:
                nonlocal p_score, calc
                if value is None:
                    details[name] = None
                    missing.append(name)
                    return
                v = 1 if value else 0
                details[name] = v
                p_score += v
                calc += 1

            # ── F1: Net kar pozitif? ──────────────────────────────────────
            nk0 = _get_row_period(is_, _NET_PROFIT_KEYS, 0)
            add("f1_positive_net_income",
                (nk0 > 0) if nk0 is not None else None)

            # ── F2: İşletme CF pozitif? ───────────────────────────────────
            op_cf0 = _get_row(cf, _OPERATING_CF_KEYS) if cf is not None else None
            add("f2_positive_operating_cash_flow",
                (op_cf0 > 0) if op_cf0 is not None else None)

            # ── F3: ROA iyileşti? ─────────────────────────────────────────
            if n_is >= 2 and n_bs >= 2:
                nk1  = _get_row_period(is_, _NET_PROFIT_KEYS, 1)
                tv0  = _get_row_period(bs, _TOTAL_ASSETS_KEYS, 0)
                tv1  = _get_row_period(bs, _TOTAL_ASSETS_KEYS, 1)
                roa0 = _safe_div(nk0, tv0)
                roa1 = _safe_div(nk1, tv1)
                add("f3_roa_improved",
                    (roa0 > roa1) if (roa0 is not None and roa1 is not None) else None)
            else:
                add("f3_roa_improved", None)

            # ── F4: CF > Net Kar? (tahakkuk kalitesi) ────────────────────
            add("f4_operating_cash_flow_greater_than_net_income",
                (op_cf0 > nk0) if (op_cf0 is not None and nk0 is not None) else None)

            # ── F5: Finansal borç oranı azaldı? ──────────────────────────
            if n_bs >= 2:
                fb0 = _sum_key_period(bs, "Finansal Borçlar", 0)
                fb1 = _sum_key_period(bs, "Finansal Borçlar", 1)
                tv0 = _get_row_period(bs, _TOTAL_ASSETS_KEYS, 0)
                tv1 = _get_row_period(bs, _TOTAL_ASSETS_KEYS, 1)
                r0  = _safe_div(fb0, tv0)
                r1  = _safe_div(fb1, tv1)
                add("f5_leverage_decreased",
                    (r0 < r1) if (r0 is not None and r1 is not None) else None)
            else:
                add("f5_leverage_decreased", None)

            # ── F6: Cari oran iyileşti? ───────────────────────────────────
            if n_bs >= 2:
                dv0 = _get_row_period(bs, _CURRENT_ASSETS_KEYS, 0)
                kl0 = _get_row_period(bs, _CURRENT_LIAB_KEYS, 0)
                dv1 = _get_row_period(bs, _CURRENT_ASSETS_KEYS, 1)
                kl1 = _get_row_period(bs, _CURRENT_LIAB_KEYS, 1)
                cr0 = _safe_div(dv0, kl0)
                cr1 = _safe_div(dv1, kl1)
                add("f6_current_ratio_improved",
                    (cr0 > cr1) if (cr0 is not None and cr1 is not None) else None)
            else:
                add("f6_current_ratio_improved", None)

            # ── F7: Yeni hisse basılmadı? ─────────────────────────────────
            if n_bs >= 2:
                os0 = _get_row_period(bs, _PAID_CAPITAL_KEYS, 0)
                os1 = _get_row_period(bs, _PAID_CAPITAL_KEYS, 1)
                add("f7_no_share_dilution",
                    (os0 <= os1 * 1.01) if (os0 is not None and os1 is not None) else None)
            else:
                add("f7_no_share_dilution", None)

            # ── F8: Brüt kar marjı iyileşti? ─────────────────────────────
            if n_is >= 2:
                bk0 = _get_row_period(is_, _GROSS_PROFIT_KEYS, 0)
                sa0 = _get_row_period(is_, _REVENUE_KEYS, 0)
                bk1 = _get_row_period(is_, _GROSS_PROFIT_KEYS, 1)
                sa1 = _get_row_period(is_, _REVENUE_KEYS, 1)
                bm0 = _safe_div(bk0, sa0)
                bm1 = _safe_div(bk1, sa1)
                add("f8_gross_margin_improved",
                    (bm0 > bm1) if (bm0 is not None and bm1 is not None) else None)
            else:
                add("f8_gross_margin_improved", None)

            # ── F9: Aktif devir hızı iyileşti? ───────────────────────────
            if n_is >= 2 and n_bs >= 2:
                sa0 = _get_row_period(is_, _REVENUE_KEYS, 0)
                sa1 = _get_row_period(is_, _REVENUE_KEYS, 1)
                tv0 = _get_row_period(bs, _TOTAL_ASSETS_KEYS, 0)
                tv1 = _get_row_period(bs, _TOTAL_ASSETS_KEYS, 1)
                at0 = _safe_div(sa0, tv0)
                at1 = _safe_div(sa1, tv1)
                add("f9_asset_turnover_improved",
                    (at0 > at1) if (at0 is not None and at1 is not None) else None)
            else:
                add("f9_asset_turnover_improved", None)

            # ── Coverage / confidence / normalize ─────────────────────────
            coverage     = round(calc / 9, 2)
            confidence   = _piotroski_confidence(calc)
            applicability = "limited" if limited else "applicable"
            normalized   = round(p_score / calc * 10, 2) if calc >= 5 else None

            if calc < 5:
                flags.append(
                    f"Piotroski skoru hesaplanamadı: yeterli kriter yok ({calc}/9)."
                )
            elif missing:
                flags.append(
                    f"Piotroski skoru {calc} kriter üzerinden hesaplanmıştır "
                    f"({len(missing)} kriter veri eksikliği nedeniyle hesaplanamadı)."
                )
            else:
                flags.append(
                    f"Piotroski skoru {calc} kriter üzerinden hesaplanmıştır."
                )

            if limited:
                flags.append(_PIOTROSKI_LIMITED_MSG)
            if operational:
                flags.append(_PIOTROSKI_OPERATIONAL_FLAG)

            return PiotroskiResult(
                score=p_score,
                normalized=normalized,
                calculated_criteria=calc,
                total_criteria=9,
                coverage=coverage,
                confidence=confidence,
                applicability=applicability,
                missing_criteria=missing,
                details=details,
            )

        except Exception as e:
            logger.warning(f"[fundamental] piotroski: {e}")
            return None

    def _piotroski_yfinance(
        self, data: dict, flags: List[str],
        limited: bool = False, operational: bool = False,
    ) -> Optional[PiotroskiResult]:
        is_ = data["is_"]
        bs  = data["bs"]
        cf  = data.get("cf")
        n_is = is_.shape[1]
        n_bs = bs.shape[1]

        details: Dict[str, Optional[int]] = {}
        p_score  = 0
        calc     = 0
        missing: List[str] = []

        def add(name: str, value: Optional[bool]) -> None:
            nonlocal p_score, calc
            if value is None:
                details[name] = None
                missing.append(name)
                return
            v = 1 if value else 0
            details[name] = v
            p_score += v
            calc += 1

        def bs_val(keys, col=0):
            for k in keys:
                if k in bs.index and col < len(bs.loc[k]):
                    v = bs.loc[k].iloc[col]
                    return float(v) if pd.notna(v) else None
            return None

        ni_ttm   = _yf_ttm(is_, YF_NET_INCOME_KEYS)
        ocf_ttm  = _yf_ttm(cf, YF_OPERATING_CASHFLOW_KEYS) if cf is not None else None
        assets0  = bs_val(YF_TOTAL_ASSETS_KEYS, 0)

        add("f1_net_kar_pozitif", (ni_ttm > 0) if ni_ttm is not None else None)
        add("f2_opcf_pozitif",    (ocf_ttm > 0) if ocf_ttm is not None else None)

        if n_is >= 8 and assets0:
            ni_prior = _yf_ttm(is_, YF_NET_INCOME_KEYS, start=4)
            assets4  = bs_val(YF_TOTAL_ASSETS_KEYS, 4)
            roa0 = _safe_div(ni_ttm,  assets0)
            roa1 = _safe_div(ni_prior, assets4)
            add("f3_roa_iyilesti",
                (roa0 > roa1) if (roa0 is not None and roa1 is not None) else None)
        else:
            add("f3_roa_iyilesti", None)

        add("f4_cf_gt_net",
            (ocf_ttm > ni_ttm) if (ocf_ttm is not None and ni_ttm is not None) else None)

        if n_bs >= 5:
            debt0 = bs_val(YF_TOTAL_DEBT_KEYS, 0)
            debt4 = bs_val(YF_TOTAL_DEBT_KEYS, 4)
            a4    = bs_val(YF_TOTAL_ASSETS_KEYS, 4)
            r0 = _safe_div(debt0, assets0)
            r1 = _safe_div(debt4, a4)
            add("f5_borc_azaldi",
                (r0 < r1) if (r0 is not None and r1 is not None) else None)
            ca0 = bs_val(YF_CURRENT_ASSETS_KEYS, 0)
            cl0 = bs_val(YF_CURRENT_LIABILITIES_KEYS, 0)
            ca4 = bs_val(YF_CURRENT_ASSETS_KEYS, 4)
            cl4 = bs_val(YF_CURRENT_LIABILITIES_KEYS, 4)
            cr0 = _safe_div(ca0, cl0)
            cr1 = _safe_div(ca4, cl4)
            add("f6_cari_oran_iyilesti",
                (cr0 > cr1) if (cr0 is not None and cr1 is not None) else None)
            sh0 = bs_val(YF_SHARES_KEYS, 0)
            sh4 = bs_val(YF_SHARES_KEYS, 4)
            add("f7_yeni_hisse_yok",
                (sh0 <= sh4 * 1.01) if (sh0 is not None and sh4 is not None) else None)
        else:
            add("f5_borc_azaldi",       None)
            add("f6_cari_oran_iyilesti", None)
            add("f7_yeni_hisse_yok",    None)

        if n_is >= 8:
            gp0 = _yf_ttm(is_, YF_GROSS_PROFIT_KEYS, start=0)
            sa0 = _yf_ttm(is_, YF_REVENUE_KEYS,       start=0)
            gp1 = _yf_ttm(is_, YF_GROSS_PROFIT_KEYS, start=4)
            sa1 = _yf_ttm(is_, YF_REVENUE_KEYS,       start=4)
            bm0 = _safe_div(gp0, sa0)
            bm1 = _safe_div(gp1, sa1)
            add("f8_brut_marj_iyilesti",
                (bm0 > bm1) if (bm0 is not None and bm1 is not None) else None)
            at0 = _safe_div(sa0, assets0)
            at1 = _safe_div(sa1, bs_val(YF_TOTAL_ASSETS_KEYS, 4))
            add("f9_aktif_devir_iyilesti",
                (at0 > at1) if (at0 is not None and at1 is not None) else None)
        else:
            add("f8_brut_marj_iyilesti",    None)
            add("f9_aktif_devir_iyilesti",  None)

        coverage      = round(calc / 9, 2)
        confidence    = _piotroski_confidence(calc)
        applicability = "limited" if limited else "applicable"
        normalized    = round(p_score / calc * 10, 2) if calc >= 5 else None

        if calc < 5:
            flags.append(
                f"Piotroski skoru hesaplanamadı: yeterli kriter yok ({calc}/9)."
            )
        elif missing:
            flags.append(
                f"Piotroski skoru {calc} kriter üzerinden hesaplanmıştır "
                f"({len(missing)} kriter veri eksikliği nedeniyle hesaplanamadı)."
            )
        else:
            flags.append(
                f"Piotroski skoru {calc} kriter üzerinden hesaplanmıştır."
            )

        if limited:
            flags.append(_PIOTROSKI_LIMITED_MSG)
        if operational:
            flags.append(_PIOTROSKI_OPERATIONAL_FLAG)

        return PiotroskiResult(
            score=p_score,
            normalized=normalized,
            calculated_criteria=calc,
            total_criteria=9,
            coverage=coverage,
            confidence=confidence,
            applicability=applicability,
            missing_criteria=missing,
            details=details,
        )

    # ── Ağırlıklı ortalama + kalite ────────────────────────────────────────

    def _weighted_average(
        self,
        reasons: Dict[str, Tuple],
        weights: Dict[str, float],
    ) -> Tuple[Optional[float], float]:
        """
        Returns (weighted_score, quality).

        Tuple formatı: (score, reason, metric_quality)
          metric_quality = subscore içinde hesaplanan metrik oranı (0.0–1.0)
          not_applicable → ağırlıktan çıkar, kaliteyi etkilemez.
          missing        → metric_quality=0.0, kaliteyi düşürür.
        """
        wsum  = 0.0
        wapp  = 0.0   # applicable ağırlık toplamı

        # quality = Σ(w * metric_q) / wapp
        wcalc_q = 0.0

        for key, w in weights.items():
            entry   = reasons.get(key, (None, "missing", 0.0))
            score   = entry[0]
            reason  = entry[1]
            metric_q = entry[2] if len(entry) > 2 else (0.0 if score is None else 1.0)

            if reason == "not_applicable":
                continue
            wapp += w
            if score is not None and reason is None:
                wcalc_q += w * metric_q
                wsum    += score * w
            # missing → metric_q = 0.0 → wcalc_q unchanged

        quality = round(wcalc_q / wapp, 2) if wapp > 0 else 0.0
        if wapp == 0 or wcalc_q == 0:
            return None, quality

        return round(wsum / wapp, 2), quality

    # ── Etiket ─────────────────────────────────────────────────────────────

    def _label(self, score: Optional[float]) -> str:
        if score is None:
            return "Veri Yetersiz"
        if score >= 8.0:
            return "Çok Güçlü"
        if score >= 6.5:
            return "Güçlü"
        if score >= 4.5:
            return "Nötr"
        if score >= 2.5:
            return "Zayıf"
        return "Çok Zayıf"

    # ── Açıklama ───────────────────────────────────────────────────────────

    def _explain(
        self,
        subscores:    FundamentalSubscores,
        piotroski:    Optional[PiotroskiResult],
        sector_group: str,
    ) -> str:
        parts: List[str] = []

        def strength(s: Optional[float], high: str, mid: str, low: str) -> str:
            if s is None:
                return ""
            if s >= 7.0:
                return high
            if s >= 4.0:
                return mid
            return low

        p = strength(
            subscores.profitability,
            "Karlılık göstergeleri sektör eşiklerine göre destekleyici seyretmektedir.",
            "Karlılık göstergeleri sektör eşiklerine yakın seyretmektedir.",
            "Karlılık göstergeleri sektör eşiklerine göre sınırlayıcı etki oluşturmaktadır.",
        )
        if p:
            parts.append(p)

        if subscores.balance_sheet is not None:
            b = strength(
                subscores.balance_sheet,
                "Bilanço yapısı güçlü görünmektedir.",
                "Bilanço yapısı orta düzeyde seyretmektedir.",
                "Bilanço yapısı zayıf seyretmektedir.",
            )
            if b:
                parts.append(b)

        if subscores.cash_flow is not None:
            c = strength(
                subscores.cash_flow,
                "Nakit akışı güçlü seyretmektedir.",
                "Nakit akışı orta düzeyde seyretmektedir.",
                "Nakit akışı zayıf seyretmektedir.",
            )
            if c:
                parts.append(c)

        if subscores.growth is not None:
            g = strength(
                subscores.growth,
                "Büyüme göstergeleri güçlü seyretmektedir.",
                "Büyüme göstergeleri orta düzeyde seyretmektedir.",
                "Büyüme göstergeleri sınırlı seyretmektedir.",
            )
            if g:
                parts.append(g)

        if subscores.valuation is not None:
            v = strength(
                subscores.valuation,
                "Değerleme çarpanları sektör eşiklerine göre destekleyici düzeydedir.",
                "Değerleme çarpanları sektör eşiklerine yakın seyretmektedir.",
                "Değerleme çarpanları sektör eşiklerine göre sınırlayıcı etki oluşturmaktadır.",
            )
            if v:
                parts.append(v)

        if piotroski and piotroski.score is not None and piotroski.calculated_criteria > 0:
            parts.append(
                f"Piotroski F-Skoru: {piotroski.score}/{piotroski.calculated_criteria} "
                "hesaplanan kriter üzerinden."
            )

        if not parts:
            return "Finansal tablo verisiyle değerlendirme yapıldı."
        return " ".join(parts)

    # ════════════════════════════════════════════════════════════════════════
    # Lending Operational V1 Model
    # ════════════════════════════════════════════════════════════════════════

    def _calculate_lending_operational(
        self,
        ticker:         str,
        sector_group:   str,
        sector_profile: str,
        flags:          List[str],
    ) -> FundamentalResult:
        """Lending Operational V1 model (faktoring/finansal kiralama/finansman).

        Primary: yfinance_quarterly.
        Sanayi/broker/banka eşikleri kullanılmaz; lending-spesifik eşikler.
        Piotroski: limited, final skora dahil değil.
        """
        data = self._fetch_data(ticker, sector_group, flags)
        if data is None:
            return self._empty_result(ticker, sector_group, flags, "veri çekilemedi")

        is_ = data.get("is_", pd.DataFrame())
        bs  = data.get("bs",  pd.DataFrame())

        # Stale veri kontrolü
        if _is_lending_stale(data):
            flags.append(
                "Finansal veri son dönemi güncel ana dönemden eski görünüyor; "
                "skor sınırlı veriyle hesaplanmıştır."
            )

        # Zorunlu veri kontrolü
        ni_ttm       = _yf_ttm(is_, YF_NET_INCOME_KEYS)
        equity_check = _yf_get(bs,  YF_TOTAL_EQUITY_KEYS)
        ta_check     = _yf_get(bs,  YF_TOTAL_ASSETS_KEYS)

        if ni_ttm is None or equity_check is None or ta_check is None:
            flags.append(
                "Lending operational modeli için zorunlu finansal satırlar eksik "
                "olduğu için skor hesaplanamadı."
            )
            return self._empty_result(ticker, sector_group, flags, "veri yetersiz")

        # Alt skor hesabı
        prof_s, prof_r, prof_q = self._lending_profitability(
            data, ni_ttm, equity_check, ta_check, flags
        )
        cap_s,  cap_r,  cap_q  = self._lending_capital_adequacy(
            data, equity_check, ta_check, flags
        )
        grow_s, grow_r, grow_q = self._lending_growth(data, flags)
        stab_s, stab_r, stab_q = self._lending_stability(data, flags)
        val_s,  val_r,  val_q  = self._lending_valuation(data, sector_group, flags)

        # Profitability kalite eşiği
        if prof_q < 0.60:
            flags.append(
                f"Lending modeli profitability kalitesi eşiğin altında "
                f"(quality={prof_q:.2f} < 0.60)."
            )
            return self._empty_result(
                ticker, sector_group, flags, "profitability kalitesi yetersiz"
            )

        # Piotroski: limited ama final skora dahil değil
        flags.append(_LENDING_PIOTROSKI_MSG)
        piotr_limited = PiotroskiResult(
            score=None, normalized=None, calculated_criteria=0,
            total_criteria=9, coverage=0.0, confidence="not_applicable",
            applicability="limited", missing_criteria=[], details={},
        )

        reasons = {
            "profitability": (prof_s, prof_r, prof_q),
            "balance_sheet": (cap_s,  cap_r,  cap_q),   # capital_adequacy
            "cash_flow":     (None,   "not_applicable", 1.0),
            "growth":        (grow_s, grow_r, grow_q),
            "valuation":     (val_s,  val_r,  val_q),
            "stability":     (stab_s, stab_r, stab_q),
            "piotroski":     (None,   "not_applicable", 1.0),
        }
        final_score, quality = self._weighted_average(reasons, _LENDING_WEIGHTS)

        if quality < 0.55:
            final_score = None
            flags.append(
                f"Lending finansal skoru hesaplanamadı: genel veri kalitesi "
                f"yetersiz (quality={quality:.2f} < 0.55)."
            )

        if final_score is not None:
            final_score = round(max(0.0, min(10.0, final_score)), 2)

        flags.append(
            "Lending modeli V1: capital_adequacy skoru "
            "finansal_subscores.balance_sheet alanında raporlanmaktadır."
        )

        subscores = FundamentalSubscores(
            profitability = _r2(prof_s),
            balance_sheet = _r2(cap_s),
            cash_flow     = None,
            growth        = _r2(grow_s),
            valuation     = _r2(val_s),
            stability     = _r2(stab_s),
            piotroski     = None,
        )

        explanation = self._explain(subscores, piotr_limited, sector_group)
        if _contains_forbidden(explanation):
            explanation = "Finansal tablo verisiyle değerlendirme yapıldı."

        return FundamentalResult(
            ticker=ticker,
            financial_score=final_score,
            financial_score_label=self._label(final_score),
            financial_score_quality=round(quality, 2),
            subscores=subscores,
            piotroski=piotr_limited,
            financial_flags=flags,
            explanation=explanation,
            sector_group=sector_group,
            data_source=data.get("data_source", "yfinance_quarterly"),
            period=data.get("period"),
        )

    def _lending_profitability(
        self,
        data:         dict,
        ni_ttm:       Optional[float],
        equity:       Optional[float],
        total_assets: Optional[float],
        flags:        List[str],
    ) -> Tuple[Optional[float], Optional[str], float]:
        """ROE (TTM) + ROA (TTM) + Gelir marjı proxy.

        Gelir marjı: NIM varsa (IntInc-IntExp)/TA, yoksa NI/Revenue.
        Sanayi borç eşikleri kullanılmaz.
        """
        try:
            is_ = data.get("is_", pd.DataFrame())

            scored: List[Tuple[float, float]] = []
            miss = 0

            # ROE = TTM NI / equity  [0, 0.30]
            s = _normalize(_safe_div(ni_ttm, equity), 0.0, 0.30)
            if s is not None: scored.append((s, 0.35))
            else:             miss += 1

            # ROA = TTM NI / total_assets  [0, 0.12] — lending-specific ceiling
            s = _normalize(_safe_div(ni_ttm, total_assets), 0.0, 0.12)
            if s is not None: scored.append((s, 0.35))
            else:             miss += 1

            # Gelir marjı proxy
            int_inc = (_yf_ttm(is_, YF_INTEREST_INCOME_GROSS_KEYS) or
                       _yf_ttm(is_, YF_NET_INTEREST_INCOME_KEYS))
            int_exp = _yf_ttm(is_, YF_INTEREST_EXPENSE_KEYS)
            revenue = _yf_ttm(is_, YF_REVENUE_KEYS) or int_inc

            im_score: Optional[float] = None
            if int_inc is not None and int_exp is not None:
                nii = int_inc - int_exp
                if nii > 0:
                    nim = _safe_div(nii, total_assets)
                    im_score = _normalize(nim, 0.0, 0.08)   # NIM [0, 8%]
                # NIM negatif/sıfır ise revenue proxy'e geç
            if im_score is None and revenue is not None and revenue > 0:
                ni_margin = _safe_div(ni_ttm, revenue)
                im_score = _normalize(ni_margin, 0.0, 0.50)  # NI/Rev [0, 50%]

            if im_score is not None: scored.append((im_score, 0.30))
            else:                    miss += 1

            if not scored:
                return None, "missing", 0.0
            mq = round(len(scored) / 3, 2)
            tw = sum(w for _, w in scored)
            return round(sum(s * w for s, w in scored) / tw, 2), None, mq

        except Exception as e:
            logger.warning(f"[fundamental/lending] profitability: {e}")
            return None, "missing", 0.0

    def _lending_capital_adequacy(
        self,
        data:         dict,
        equity:       Optional[float],
        total_assets: Optional[float],
        flags:        List[str],
    ) -> Tuple[Optional[float], Optional[str], float]:
        """Equity/TA + FinDebt/Equity.

        Lending-spesifik eşikler: Eq/TA [0.06,0.35]; FD/Eq [0,8] reverse.
        Sanayi current_ratio, debt_to_ebitda kullanılmaz.
        """
        try:
            bs = data.get("bs", pd.DataFrame())
            fin_debt = _yf_get(bs, YF_TOTAL_DEBT_KEYS)

            scored: List[Tuple[float, float]] = []
            miss = 0

            # Equity / Total Assets  [0.06, 0.35]
            s = _normalize(_safe_div(equity, total_assets), 0.06, 0.35)
            if s is not None: scored.append((s, 0.55))
            else:             miss += 1

            # Financial Debt / Equity  [0.0, 8.0]  reverse
            if fin_debt is not None and equity is not None and equity > 0:
                s = _normalize(fin_debt / equity, 0.0, 8.0, reverse=True)
                if s is not None: scored.append((s, 0.45))
                else:             miss += 1
            else:
                miss += 1

            if not scored:
                return None, "missing", 0.0
            mq = round(len(scored) / 2, 2)
            tw = sum(w for _, w in scored)
            return round(sum(s * w for s, w in scored) / tw, 2), None, mq

        except Exception as e:
            logger.warning(f"[fundamental/lending] capital_adequacy: {e}")
            return None, "missing", 0.0

    def _lending_growth(
        self,
        data:  dict,
        flags: List[str],
    ) -> Tuple[Optional[float], Optional[str], float]:
        """NI YoY + Equity YoY + Revenue/IntInc YoY.

        Aynı çeyrek karşılaştırması; yeterli dönem yoksa yıllık fallback.
        Cap: NI/Rev ±300%, Equity ±200%.
        """
        try:
            is_  = data.get("is_", pd.DataFrame())
            bs   = data.get("bs",  pd.DataFrame())
            is_y = data.get("is_y")
            bs_y = data.get("bs_y")
            n_is = is_.shape[1]
            n_bs = bs.shape[1]

            scored: List[Tuple[float, float]] = []
            miss = 0
            used_yearly = False

            def yf_at(df, keys, col):
                if df is None: return None
                for k in keys:
                    if k in df.index and col < df.shape[1]:
                        v = df.loc[k].iloc[col]
                        return float(v) if pd.notna(v) else None
                return None

            def yoy(curr, prev, cap):
                if curr is None or prev is None or prev == 0: return None
                return max(-cap, min(cap, (curr - prev) / abs(prev)))

            # NI YoY (cap ±300%)
            ni_curr  = _yf_ttm(is_, YF_NET_INCOME_KEYS, 0)
            ni_prev  = _yf_ttm(is_, YF_NET_INCOME_KEYS, 4) if n_is >= 8 else None
            if (ni_curr is None or ni_prev is None) and is_y is not None and is_y.shape[1] >= 2:
                nc  = _yf_get(is_y, YF_NET_INCOME_KEYS)
                np_ = yf_at(is_y, YF_NET_INCOME_KEYS, 1)
                if nc is not None and np_ is not None:
                    ni_curr, ni_prev, used_yearly = nc, np_, True
            ni_yoy = yoy(ni_curr, ni_prev, 3.0)

            # Equity YoY (cap ±200%)
            eq_curr = _yf_get(bs, YF_TOTAL_EQUITY_KEYS)
            eq_prev = yf_at(bs, YF_TOTAL_EQUITY_KEYS, 4) if n_bs >= 5 else None
            if (eq_curr is None or eq_prev is None) and bs_y is not None and bs_y.shape[1] >= 2:
                ec = _yf_get(bs_y, YF_TOTAL_EQUITY_KEYS)
                ep = yf_at(bs_y, YF_TOTAL_EQUITY_KEYS, 1)
                if eq_curr is None and ec is not None: eq_curr, used_yearly = ec, True
                if eq_prev is None and ep is not None: eq_prev, used_yearly = ep, True
            eq_yoy = yoy(eq_curr, eq_prev, 2.0)

            # Revenue/IntInc YoY (cap ±300%)
            rev_keys = (YF_INTEREST_INCOME_GROSS_KEYS +
                        YF_NET_INTEREST_INCOME_KEYS +
                        YF_REVENUE_KEYS)
            rev_curr = _yf_ttm(is_, rev_keys, 0)
            rev_prev = _yf_ttm(is_, rev_keys, 4) if n_is >= 8 else None
            if (rev_curr is None or rev_prev is None) and is_y is not None and is_y.shape[1] >= 2:
                rc  = _yf_get(is_y, rev_keys)
                rp  = yf_at(is_y, rev_keys, 1)
                if rc is not None and rp is not None:
                    rev_curr, rev_prev, used_yearly = rc, rp, True
            rev_yoy = yoy(rev_curr, rev_prev, 3.0)

            if used_yearly:
                flags.append(
                    "Lending growth skorunda çeyreklik dönem yetersiz; "
                    "yıllık veri destekleyici kullanıldı."
                )

            for rate, w in [(ni_yoy, 0.40), (eq_yoy, 0.35), (rev_yoy, 0.25)]:
                s = _normalize(rate, *_T["growth"])
                if s is not None: scored.append((s, w))
                else:             miss += 1

            if not scored:
                return None, "missing", 0.0
            mq = round(len(scored) / 3, 2)
            tw = sum(w for _, w in scored)
            return round(min(sum(s * w for s, w in scored) / tw, 9.5), 2), None, mq

        except Exception as e:
            logger.warning(f"[fundamental/lending] growth: {e}")
            return None, "missing", 0.0

    def _lending_stability(
        self,
        data:  dict,
        flags: List[str],
    ) -> Tuple[Optional[float], Optional[str], float]:
        """Son 4 dönemde pozitif NI sayısı + NI volatilitesi."""
        try:
            is_ = data.get("is_", pd.DataFrame())

            ni_all: List[float] = []
            for k in YF_NET_INCOME_KEYS:
                if k in is_.index:
                    ni_all = [float(v) for v in is_.loc[k] if pd.notna(v)]
                    break

            if not ni_all:
                return None, "missing", 0.0

            ni_last4 = ni_all[:4]
            scored: List[Tuple[float, float]] = []
            miss = 0

            # Pozitif NI sayısı (0/4 → 0, 4/4 → 10)
            pos_count = sum(1 for v in ni_last4 if v > 0)
            scored.append(((pos_count / 4) * 10.0, 0.60))

            # NI volatilitesi: CV ters normalize [0, 2]
            if len(ni_all) >= 3:
                mean_abs = abs(float(np.mean(ni_all)))
                if mean_abs > 0:
                    cv = float(np.std(ni_all)) / mean_abs
                    s  = _normalize(cv, 0.0, 2.0, reverse=True)
                    if s is not None: scored.append((s, 0.40))
                    else:             miss += 1
                else:
                    miss += 1
            else:
                miss += 1

            if not scored:
                return None, "missing", 0.0
            mq = round(len(scored) / 2, 2)
            tw = sum(w for _, w in scored)
            return round(sum(s * w for s, w in scored) / tw, 2), None, mq

        except Exception as e:
            logger.warning(f"[fundamental/lending] stability: {e}")
            return None, "missing", 0.0

    def _lending_valuation(
        self,
        data:         dict,
        sector_group: str,
        flags:        List[str],
    ) -> Tuple[Optional[float], Optional[str], float]:
        """P/E + P/B (yfinance info veya marketCap hesabı)."""
        try:
            is_  = data.get("is_", pd.DataFrame())
            bs   = data.get("bs",  pd.DataFrame())
            info = data.get("info") or {}

            fk_high   = _FK_HIGH.get(sector_group, 30.0)
            pddd_high = _PDDD_HIGH.get(sector_group, 4.0)

            scored: List[Tuple[float, float]] = []
            miss = 0

            # P/E
            pe_added = False
            trailing_pe = info.get("trailingPE") if isinstance(info, dict) else None
            if trailing_pe and np.isfinite(trailing_pe) and trailing_pe > 0:
                s = _normalize(trailing_pe, 0.0, fk_high, reverse=True)
                if s is not None:
                    scored.append((s, 0.50))
                    pe_added = True
            if not pe_added:
                ni_ttm_v   = _yf_ttm(is_, YF_NET_INCOME_KEYS)
                market_cap = info.get("marketCap") if isinstance(info, dict) else None
                if market_cap and ni_ttm_v and ni_ttm_v > 0:
                    pe = market_cap / ni_ttm_v
                    if pe > 0:
                        s = _normalize(pe, 0.0, fk_high, reverse=True)
                        if s is not None:
                            scored.append((s, 0.50))
                            pe_added = True
                if not pe_added:
                    miss += 1

            # P/B
            pb_added = False
            price_to_book = info.get("priceToBook") if isinstance(info, dict) else None
            if price_to_book and np.isfinite(price_to_book) and price_to_book > 0:
                s = _normalize(price_to_book, 0.0, pddd_high, reverse=True)
                if s is not None:
                    scored.append((s, 0.50))
                    pb_added = True
            if not pb_added:
                equity_v   = _yf_get(bs, YF_TOTAL_EQUITY_KEYS)
                market_cap = info.get("marketCap") if isinstance(info, dict) else None
                if market_cap and equity_v and equity_v > 0:
                    pb = market_cap / equity_v
                    if pb > 0:
                        s = _normalize(pb, 0.0, pddd_high, reverse=True)
                        if s is not None:
                            scored.append((s, 0.50))
                            pb_added = True
                if not pb_added:
                    miss += 1

            if not scored:
                return None, "missing", 0.0
            mq = round(len(scored) / 2, 2)
            tw = sum(w for _, w in scored)
            return round(sum(s * w for s, w in scored) / tw, 2), None, mq

        except Exception as e:
            logger.warning(f"[fundamental/lending] valuation: {e}")
            return None, "missing", 0.0

    # ════════════════════════════════════════════════════════════════════════
    # Broker Operational V1 Model
    # ════════════════════════════════════════════════════════════════════════

    def _calculate_broker_operational(
        self,
        ticker:         str,
        sector_group:   str,
        sector_profile: str,
        flags:          List[str],
    ) -> FundamentalResult:
        """Broker Operational V1 model.

        Kaynak: isyatirim_group_1 (primary) → yfinance_quarterly (fallback).
        3C (Satış Gelirleri) hiçbir hesaplamada kullanılmaz.
        Piotroski: not_applicable.
        """
        data = self._fetch_data(ticker, sector_group, flags)
        if data is None:
            return self._empty_result(ticker, sector_group, flags, "veri çekilemedi")

        isyat = data.get("isyat", False)
        yf    = data.get("yf", False)
        df    = data["is_"]
        bs    = data.get("bs", df)

        # Zorunlu veri kontrolü
        if isyat:
            ni_ttm       = _iy_ttm_sum(df, _NET_PROFIT_KEYS, n=4)
            equity_check = _get_row(df, _EQUITY_KEYS)
            ta_check     = _get_row(df, _TOTAL_ASSETS_KEYS)
        else:
            ni_ttm       = _yf_ttm(df, YF_NET_INCOME_KEYS)
            equity_check = _yf_get(bs, YF_TOTAL_EQUITY_KEYS)
            ta_check     = _yf_get(bs, YF_TOTAL_ASSETS_KEYS)

        if ni_ttm is None or equity_check is None or ta_check is None:
            flags.append(
                "Broker modeli için zorunlu veri eksik "
                "(net_income TTM / equity / total_assets)."
            )
            return self._empty_result(
                ticker, sector_group, flags, "veri yetersiz"
            )

        # Alt skor hesabı
        prof_s, prof_r, prof_q = self._broker_profitability(
            data, ni_ttm, equity_check, ta_check, flags
        )
        cap_s,  cap_r,  cap_q  = self._broker_capital_strength(
            data, equity_check, ta_check, flags
        )
        grow_s, grow_r, grow_q = self._broker_growth(data, flags)
        stab_s, stab_r, stab_q = self._broker_stability(data, flags)
        val_s,  val_r,  val_q  = self._broker_valuation(
            data, sector_group, flags
        )

        # Profitability kalite eşiği
        if prof_q < 0.60:
            flags.append(
                f"Broker modeli profitability kalitesi eşiğin altında "
                f"(quality={prof_q:.2f} < 0.60)."
            )
            return self._empty_result(
                ticker, sector_group, flags, "profitability kalitesi yetersiz"
            )

        # Piotroski: not_applicable
        flags.append(_BROKER_PIOTROSKI_NA_MSG)
        piotr_na = PiotroskiResult(
            score=None, normalized=None, calculated_criteria=0,
            total_criteria=9, coverage=0.0, confidence="not_applicable",
            applicability="not_applicable", missing_criteria=[], details={},
        )

        reasons = {
            "profitability": (prof_s, prof_r, prof_q),
            "balance_sheet": (cap_s,  cap_r,  cap_q),   # capital_strength
            "cash_flow":     (None,   "not_applicable", 1.0),
            "growth":        (grow_s, grow_r, grow_q),
            "valuation":     (val_s,  val_r,  val_q),
            "stability":     (stab_s, stab_r, stab_q),
            "piotroski":     (None,   "not_applicable", 1.0),
        }
        final_score, quality = self._weighted_average(reasons, _BROKER_WEIGHTS)

        if quality < 0.55:
            final_score = None
            flags.append(
                f"Broker finansal skoru hesaplanamadı: genel veri kalitesi "
                f"yetersiz (quality={quality:.2f} < 0.55)."
            )

        if final_score is not None:
            final_score = round(max(0.0, min(10.0, final_score)), 2)

        flags.append(
            "Broker modeli V1: capital_strength skoru "
            "finansal_subscores.balance_sheet alanında raporlanmaktadır."
        )

        subscores = FundamentalSubscores(
            profitability = _r2(prof_s),
            balance_sheet = _r2(cap_s),
            cash_flow     = None,
            growth        = _r2(grow_s),
            valuation     = _r2(val_s),
            stability     = _r2(stab_s),
            piotroski     = None,
        )

        explanation = self._explain(subscores, piotr_na, sector_group)
        if _contains_forbidden(explanation):
            explanation = "Finansal tablo verisiyle değerlendirme yapıldı."

        return FundamentalResult(
            ticker=ticker,
            financial_score=final_score,
            financial_score_label=self._label(final_score),
            financial_score_quality=round(quality, 2),
            subscores=subscores,
            piotroski=piotr_na,
            financial_flags=flags,
            explanation=explanation,
            sector_group=sector_group,
            data_source=data.get("data_source", "isyatirim_quarterly"),
            period=data.get("period"),
        )

    def _broker_profitability(
        self,
        data:         dict,
        ni_ttm:       Optional[float],
        equity:       Optional[float],
        total_assets: Optional[float],
        flags:        List[str],
    ) -> Tuple[Optional[float], Optional[str], float]:
        """ROE (TTM) + ROA (TTM) + Op.Margin proxy (3DF/3D).

        3C kullanılmaz. Op.Margin = 3DF/3D, 1.0'a cap edilir.
        """
        try:
            isyat = data.get("isyat", False)
            yf    = data.get("yf", False)
            df    = data["is_"]

            # Gross profit proxy (3D) ve operating income (3DF)
            if isyat:
                gross_profit = _get_row(df, _GROSS_PROFIT_KEYS)
                op_income    = _get_row(df, _OPERATING_PROFIT_KEYS)
            elif yf:
                gross_profit = _yf_ttm(df, YF_GROSS_PROFIT_KEYS)
                op_income    = _yf_ttm(df, YF_OPERATING_INCOME_KEYS)
            else:
                gross_profit = _get_row(df, _GROSS_PROFIT_KEYS)
                op_income    = _get_row(df, _OPERATING_PROFIT_KEYS)

            scored: List[Tuple[float, float]] = []
            miss = 0

            # ROE = TTM NI / equity  [0, 0.30]
            s = _normalize(_safe_div(ni_ttm, equity), 0.0, 0.30)
            if s is not None: scored.append((s, 0.35))
            else:             miss += 1

            # ROA = TTM NI / total_assets  [0, 0.15]
            s = _normalize(_safe_div(ni_ttm, total_assets), 0.0, 0.15)
            if s is not None: scored.append((s, 0.30))
            else:             miss += 1

            # Op.Margin proxy = 3DF / 3D  (cap 1.0)
            if op_income is not None and gross_profit and gross_profit != 0:
                opm = op_income / gross_profit
                if opm > 1.0:
                    flags.append(
                        f"Broker 3DF/3D={opm:.2f} > 1.0; "
                        "other_income_material=True — 1.0'a cap edildi."
                    )
                    opm = 1.0
                s = _normalize(opm, 0.0, 1.0)
                if s is not None: scored.append((s, 0.35))
                else:             miss += 1
            else:
                miss += 1

            if not scored:
                return None, "missing", 0.0
            mq = round(len(scored) / 3, 2)
            tw = sum(w for _, w in scored)
            return round(sum(s * w for s, w in scored) / tw, 2), None, mq

        except Exception as e:
            logger.warning(f"[fundamental/broker] profitability: {e}")
            return None, "missing", 0.0

    def _broker_capital_strength(
        self,
        data:         dict,
        equity:       Optional[float],
        total_assets: Optional[float],
        flags:        List[str],
    ) -> Tuple[Optional[float], Optional[str], float]:
        """Equity/TA + FinDebt/Equity.

        FinDebt = 2AA + 2BA (KV + UV Finansal Borçlar).
        current_ratio kullanılmaz (aracı kurumlarda yanıltıcı).
        """
        try:
            isyat = data.get("isyat", False)
            yf    = data.get("yf", False)
            df    = data["is_"]

            if isyat:
                fin_debt = _sum_key_latest(df, "Finansal Borçlar")
            elif yf:
                fin_debt = _yf_get(data.get("bs", df), YF_TOTAL_DEBT_KEYS)
            else:
                fin_debt = _sum_key_latest(df, "Finansal Borçlar")

            scored: List[Tuple[float, float]] = []
            miss = 0

            # Equity / Total Assets  [0.05, 0.50]
            s = _normalize(_safe_div(equity, total_assets), 0.05, 0.50)
            if s is not None: scored.append((s, 0.55))
            else:             miss += 1

            # Financial Debt / Equity  [0.0, 4.0]  reverse
            if fin_debt is not None and equity and equity > 0:
                s = _normalize(fin_debt / equity, 0.0, 4.0, reverse=True)
                if s is not None: scored.append((s, 0.45))
                else:             miss += 1
            else:
                miss += 1

            if not scored:
                return None, "missing", 0.0
            mq = round(len(scored) / 2, 2)
            tw = sum(w for _, w in scored)
            return round(sum(s * w for s, w in scored) / tw, 2), None, mq

        except Exception as e:
            logger.warning(f"[fundamental/broker] capital_strength: {e}")
            return None, "missing", 0.0

    def _broker_growth(
        self,
        data:  dict,
        flags: List[str],
    ) -> Tuple[Optional[float], Optional[str], float]:
        """YoY büyüme: aynı çeyrek karşılaştırması (col 0 vs col 4).

        NI YoY + Equity YoY + Gross Profit YoY.
        3C kullanılmaz — gross profit proxy (3D) kullanılır.
        Cap: ±500%.
        """
        try:
            isyat = data.get("isyat", False)
            yf    = data.get("yf", False)

            def cap_yoy(r: Optional[float]) -> Optional[float]:
                if r is None:
                    return None
                return max(-5.0, min(5.0, r))

            scored: List[Tuple[float, float]] = []
            miss = 0

            if isyat:
                df = data["is_"]

                def iy_yoy(keys: List[str]) -> Optional[float]:
                    if df.shape[1] < 5:
                        return None
                    c = _get_row_period(df, keys, 0)
                    p = _get_row_period(df, keys, 4)
                    if c is None or p is None or p == 0:
                        return None
                    return cap_yoy((c - p) / abs(p))

                ni_yoy = iy_yoy(_NET_PROFIT_KEYS)
                eq_yoy = iy_yoy(_EQUITY_KEYS)
                gp_yoy = iy_yoy(_GROSS_PROFIT_KEYS)   # 3D, NOT 3C

            elif yf:
                is_ = data["is_"]
                bs  = data.get("bs", is_)
                n_is = is_.shape[1]
                n_bs = bs.shape[1]

                def yf_at(df, keys, col):
                    for k in keys:
                        if k in df.index and col < df.shape[1]:
                            v = df.loc[k].iloc[col]
                            return float(v) if pd.notna(v) else None
                    return None

                ni_c = _yf_ttm(is_, YF_NET_INCOME_KEYS, 0)
                ni_p = _yf_ttm(is_, YF_NET_INCOME_KEYS, 4) if n_is >= 8 else None
                eq_c = _yf_get(bs, YF_TOTAL_EQUITY_KEYS)
                eq_p = yf_at(bs, YF_TOTAL_EQUITY_KEYS, 4) if n_bs >= 5 else None
                # gross profit proxy, NOT revenue
                gp_c = _yf_ttm(is_, YF_GROSS_PROFIT_KEYS, 0)
                gp_p = _yf_ttm(is_, YF_GROSS_PROFIT_KEYS, 4) if n_is >= 8 else None

                def yoy(c, p):
                    if c is None or p is None or p == 0:
                        return None
                    return cap_yoy((c - p) / abs(p))

                ni_yoy = yoy(ni_c, ni_p)
                eq_yoy = yoy(eq_c, eq_p)
                gp_yoy = yoy(gp_c, gp_p)

            else:
                return None, "missing", 0.0

            for rate, w in [(ni_yoy, 0.40), (eq_yoy, 0.35), (gp_yoy, 0.25)]:
                s = _normalize(rate, *_T["growth"])
                if s is not None: scored.append((s, w))
                else:             miss += 1

            if not scored:
                return None, "missing", 0.0
            mq = round(len(scored) / 3, 2)
            tw = sum(w for _, w in scored)
            return round(min(sum(s * w for s, w in scored) / tw, 9.5), 2), None, mq

        except Exception as e:
            logger.warning(f"[fundamental/broker] growth: {e}")
            return None, "missing", 0.0

    def _broker_stability(
        self,
        data:  dict,
        flags: List[str],
    ) -> Tuple[Optional[float], Optional[str], float]:
        """Son 4 çeyrekte pozitif NI sayısı + NI volatilitesi.

        Tek çeyrek zarar sert ceza değil; sürekli zarar düşük skor.
        """
        try:
            isyat = data.get("isyat", False)
            yf    = data.get("yf", False)

            if isyat:
                df = data["is_"]
                ni_last4 = [
                    _get_row_period(df, _NET_PROFIT_KEYS, i)
                    for i in range(min(4, df.shape[1]))
                ]
                ni_last4 = [v for v in ni_last4 if v is not None]
                ni_all = [
                    _get_row_period(df, _NET_PROFIT_KEYS, i)
                    for i in range(min(17, df.shape[1]))
                ]
                ni_all = [v for v in ni_all if v is not None]
            elif yf:
                is_ = data["is_"]
                ni_last4 = []
                for k in YF_NET_INCOME_KEYS:
                    if k in is_.index:
                        ni_last4 = [
                            float(v) for v in is_.loc[k].iloc[:4]
                            if pd.notna(v)
                        ]
                        break
                ni_all = ni_last4
            else:
                return None, "missing", 0.0

            if not ni_last4:
                return None, "missing", 0.0

            scored: List[Tuple[float, float]] = []
            miss = 0

            # Pozitif NI sayısı (0/4 → 0, 4/4 → 10)
            pos_count = sum(1 for v in ni_last4 if v > 0)
            scored.append(((pos_count / 4) * 10.0, 0.60))

            # NI volatilitesi: CV ters normalize  [0, 2]
            if len(ni_all) >= 3:
                mean_abs = abs(float(np.mean(ni_all)))
                if mean_abs > 0:
                    cv = float(np.std(ni_all)) / mean_abs
                    s  = _normalize(cv, 0.0, 2.0, reverse=True)
                    if s is not None: scored.append((s, 0.40))
                    else:             miss += 1
                else:
                    miss += 1
            else:
                miss += 1

            if not scored:
                return None, "missing", 0.0
            mq = round(len(scored) / 2, 2)
            tw = sum(w for _, w in scored)
            return round(sum(s * w for s, w in scored) / tw, 2), None, mq

        except Exception as e:
            logger.warning(f"[fundamental/broker] stability: {e}")
            return None, "missing", 0.0

    def _broker_valuation(
        self,
        data:         dict,
        sector_group: str,
        flags:        List[str],
    ) -> Tuple[Optional[float], Optional[str], float]:
        """P/E ve P/B.

        Önce yfinance info.trailingPE / priceToBook.
        Yoksa market_cap / TTM NI veya market_cap / equity.
        """
        try:
            isyat = data.get("isyat", False)
            df    = data["is_"]
            bs    = data.get("bs", df)
            info  = data.get("info") or {}

            fk_high   = _FK_HIGH.get(sector_group, 30.0)
            pddd_high = _PDDD_HIGH.get(sector_group, 4.0)

            scored: List[Tuple[float, float]] = []
            miss = 0

            # ── P/E ────────────────────────────────────────────────────────
            pe_added = False
            trailing_pe = info.get("trailingPE") if isinstance(info, dict) else None
            if trailing_pe and np.isfinite(trailing_pe) and trailing_pe > 0:
                s = _normalize(trailing_pe, 0.0, fk_high, reverse=True)
                if s is not None:
                    scored.append((s, 0.50))
                    pe_added = True

            if not pe_added:
                market_cap = info.get("marketCap") if isinstance(info, dict) else None
                ni_ttm_val = (
                    _iy_ttm_sum(df, _NET_PROFIT_KEYS, 4)
                    if isyat
                    else _yf_ttm(df, YF_NET_INCOME_KEYS)
                )
                if market_cap and ni_ttm_val and ni_ttm_val > 0:
                    pe = market_cap / ni_ttm_val
                    if pe > 0:
                        s = _normalize(pe, 0.0, fk_high, reverse=True)
                        if s is not None:
                            scored.append((s, 0.50))
                            pe_added = True
                if not pe_added:
                    miss += 1

            # ── P/B ────────────────────────────────────────────────────────
            pb_added = False
            price_to_book = (
                info.get("priceToBook") if isinstance(info, dict) else None
            )
            if price_to_book and np.isfinite(price_to_book) and price_to_book > 0:
                s = _normalize(price_to_book, 0.0, pddd_high, reverse=True)
                if s is not None:
                    scored.append((s, 0.50))
                    pb_added = True

            if not pb_added:
                market_cap = info.get("marketCap") if isinstance(info, dict) else None
                equity_val = (
                    _get_row(df, _EQUITY_KEYS)
                    if isyat
                    else _yf_get(bs, YF_TOTAL_EQUITY_KEYS)
                )
                if market_cap and equity_val and equity_val > 0:
                    pb = market_cap / equity_val
                    if pb > 0:
                        s = _normalize(pb, 0.0, pddd_high, reverse=True)
                        if s is not None:
                            scored.append((s, 0.50))
                            pb_added = True
                if not pb_added:
                    miss += 1

            if not scored:
                return None, "missing", 0.0
            mq = round(len(scored) / 2, 2)
            tw = sum(w for _, w in scored)
            return round(sum(s * w for s, w in scored) / tw, 2), None, mq

        except Exception as e:
            logger.warning(f"[fundamental/broker] valuation: {e}")
            return None, "missing", 0.0

    # ════════════════════════════════════════════════════════════════════════
    # Investment Trust V1 Model
    # ════════════════════════════════════════════════════════════════════════

    def _it_yf_info(self, ticker: str) -> dict:
        """yfinance info'dan priceToBook, marketCap, last_price çek."""
        yf_info: dict = {}
        try:
            import yfinance as yf
            t_yf = yf.Ticker(_to_yfinance_symbol(ticker))
            lp   = getattr(t_yf.fast_info, "last_price", None)
            if lp:
                yf_info["last"] = float(lp)
            raw = t_yf.info or {}
            for k in ("priceToBook", "marketCap"):
                v = raw.get(k)
                if v is not None:
                    try:
                        fv = float(v)
                        if np.isfinite(fv) and fv > 0:
                            yf_info[k] = fv
                    except (TypeError, ValueError):
                        pass
        except Exception:
            pass
        return yf_info

    def _fetch_investment_trust(
        self,
        ticker: str,
        flags:  List[str],
    ) -> Optional[dict]:
        """Kaynak önceliği:
        1. isyatirim_quarterly — dönem >= 2023 VE zorunlu metrikler varsa
        2. yfinance_quarterly  — dönem >= 2025-12-01 VE zorunlu metrikler varsa
        3. borsapy_yearly      — fallback (flag eklenir)
        """
        # ── 1. İş Yatırım ─────────────────────────────────────────────────────
        iy_flags: List[str] = []
        iy_data = self._fetch_isyatirim(ticker, "investment_trust", iy_flags)
        if iy_data is not None:
            iy_year = _it_period_year(iy_data)
            if iy_year >= _IT_ISYAT_MIN_YEAR:
                if _it_has_required(iy_data, yf=False):
                    flags.extend(iy_flags)
                    # isyatirim kendi içinde yfinance info çekiyor; dict değilse güncelle
                    if not isinstance(iy_data.get("info"), dict):
                        iy_data = {**iy_data, "info": self._it_yf_info(ticker)}
                    return iy_data
                else:
                    flags.append(
                        "İş Yatırım yatırım ortaklığı verisi zorunlu metrikleri eksik "
                        "(equity/total_assets); atlandı."
                    )
            else:
                flags.append(
                    f"İş Yatırım yatırım ortaklığı verisi eski dönem döndürdüğü için "
                    f"kullanılmadı (dönem: {iy_data.get('period')})."
                )

        # ── 2. yfinance_quarterly ─────────────────────────────────────────────
        yf_flags: List[str] = []
        yf_data = self._fetch_yfinance_quarterly(ticker, "investment_trust", yf_flags)

        # ── 3. borsapy_yearly ─────────────────────────────────────────────────
        bp_flags: List[str] = []
        bp_data = self._fetch_standard(ticker, bp_flags)

        # yfinance tercihli mi? (dönem >= cutoff VE zorunlu metrikler)
        yf_ym = _it_latest_col_ym(yf_data)
        yf_ts = pd.Timestamp(f"{yf_ym[0]}-{yf_ym[1]:02d}-01") if yf_ym else None
        yf_preferred = (
            yf_data is not None and
            yf_ts is not None and
            yf_ts >= _IT_YF_PREFERRED_CUTOFF and
            _it_has_required(yf_data, yf=True)
        )

        if yf_preferred:
            flags.extend(yf_flags)
            flags.append(
                f"Yatırım ortaklığı skoru güncel yfinance quarterly verisiyle hesaplandı "
                f"(dönem: {yf_data.get('period')})."
            )
            return yf_data

        # borsapy fallback
        if bp_data is not None:
            flags.extend(bp_flags)
            bp_year = _it_period_year(bp_data)
            flags.append(
                f"Yatırım ortaklığı skoru {bp_year} yıllık finansal veriyle hesaplanmıştır; "
                "daha güncel geçerli çeyreklik veri bulunamadı."
            )
            return {**bp_data, "info": self._it_yf_info(ticker)}

        # Son çare: yfinance (dönem eski de olsa)
        if yf_data is not None:
            flags.extend(yf_flags)
            flags.append(
                "Investment trust: borsapy veri alınamadı; yfinance_quarterly (stale) kullanıldı."
            )
            return yf_data

        return None

    def _calculate_investment_trust(
        self,
        ticker:       str,
        sector_group: str,
        flags:        List[str],
    ) -> FundamentalResult:
        """Investment Trust V1 modeli (MKYO/GSYO).

        Primary: borsapy_yearly + yfinance valuation bilgisi.
        Fallback: yfinance_quarterly.
        isyatirim: atlanır.
        Revenue/Satış Gelirleri: hiçbir hesapta kullanılmaz.
        Piotroski: not_applicable.
        """
        data = self._fetch_investment_trust(ticker, flags)
        if data is None:
            return self._empty_result(ticker, sector_group, flags, "veri çekilemedi")

        yf  = data.get("yf", False)
        bs  = data.get("bs", pd.DataFrame())
        is_ = data.get("is_", pd.DataFrame())

        # Zorunlu veri kontrolü
        if yf:
            equity_check = _yf_get(bs, YF_TOTAL_EQUITY_KEYS)
            ta_check     = _yf_get(bs, YF_TOTAL_ASSETS_KEYS)
        else:
            equity_check = _get_row(bs, _EQUITY_KEYS)
            ta_check     = _get_row(bs, _TOTAL_ASSETS_KEYS)

        if equity_check is None or ta_check is None:
            flags.append(
                "Investment trust modeli için zorunlu finansal satırlar eksik "
                "(equity / total_assets); skor hesaplanamadı."
            )
            return self._empty_result(ticker, sector_group, flags, "equity/total_assets eksik")

        # Stale veri uyarısı
        period_str = data.get("period") or ""
        if period_str:
            m = re.match(r"^(\d{4})", period_str)
            if m and int(m.group(1)) < 2023:
                flags.append(
                    "Finansal veri son dönemi görece eski görünüyor; "
                    "skor sınırlı güncellikte veriyle hesaplanmıştır."
                )

        # Alt skor hesabı
        val_s,  val_r,  val_q  = self._it_valuation(data, equity_check, flags)
        grow_s, grow_r, grow_q = self._it_nav_growth(data, flags)
        stab_s, stab_r, stab_q = self._it_stability(data, flags)
        lev_s,  lev_r,  lev_q  = self._it_leverage(equity_check, ta_check, flags)

        # Piotroski: not_applicable
        flags.append(_IT_PIOTROSKI_NA_MSG)
        piotr_na = PiotroskiResult(
            score=None, normalized=None, calculated_criteria=0,
            total_criteria=9, coverage=0.0, confidence="not_applicable",
            applicability="not_applicable", missing_criteria=[], details={},
        )

        reasons = {
            "profitability": (None,   "not_applicable", 1.0),
            "balance_sheet": (lev_s,  lev_r,  lev_q),    # leverage
            "cash_flow":     (None,   "not_applicable", 1.0),
            "growth":        (grow_s, grow_r, grow_q),   # nav_growth
            "valuation":     (val_s,  val_r,  val_q),
            "stability":     (stab_s, stab_r, stab_q),
            "piotroski":     (None,   "not_applicable", 1.0),
        }
        final_score, quality = self._weighted_average(reasons, _IT_WEIGHTS)

        if quality < 0.55:
            final_score = None
            flags.append(
                f"Investment trust finansal skoru hesaplanamadı: genel veri kalitesi "
                f"yetersiz (quality={quality:.2f} < 0.55)."
            )

        if final_score is not None:
            final_score = round(max(0.0, min(10.0, final_score)), 2)

        flags.append(
            "Investment trust modeli V1: leverage skoru "
            "finansal_subscores.balance_sheet alanında raporlanmaktadır."
        )

        subscores = FundamentalSubscores(
            profitability = None,
            balance_sheet = _r2(lev_s),
            cash_flow     = None,
            growth        = _r2(grow_s),
            valuation     = _r2(val_s),
            stability     = _r2(stab_s),
            piotroski     = None,
        )

        explanation = self._it_explain(subscores, val_s, grow_s)
        if _contains_forbidden(explanation):
            explanation = "Finansal tablo verisiyle değerlendirme yapıldı."

        return FundamentalResult(
            ticker=ticker,
            financial_score=final_score,
            financial_score_label=self._label(final_score),
            financial_score_quality=round(quality, 2),
            subscores=subscores,
            piotroski=piotr_na,
            financial_flags=flags,
            explanation=explanation,
            sector_group=sector_group,
            data_source=data.get("data_source", "borsapy_yearly"),
            period=data.get("period"),
        )

    def _it_pb_score(self, pb: float, flags: List[str]) -> float:
        """P/B bantlama — investment trust özel."""
        if pb > _IT_PB_PREMIUM_CEIL:
            flags.append(
                "Piyasa değeri özkaynak/NAV seviyesinin belirgin üzerinde görünüyor; "
                "valuation alt skoru sınırlayıcı etki oluşturdu."
            )
            return 0.0
        if pb < _IT_PB_DEEP_DISCOUNT:
            flags.append(
                "Piyasa değeri ile özkaynak/NAV arasında belirgin iskonto görülüyor; "
                "bu fark tek başına olumlu veya olumsuz yorumlanmamalıdır."
            )
            return 2.0
        if pb < _IT_PB_DISCOUNT_CAP:
            flags.append(
                "Piyasa değeri ile özkaynak/NAV arasında belirgin iskonto görülüyor; "
                "bu fark tek başına olumlu veya olumsuz yorumlanmamalıdır."
            )
            return 5.0
        # 0.5 – 2.5: skor ters normalize  (0.5→10, 2.5→0)
        s = _normalize(pb, 0.5, 2.5, reverse=True)
        return s if s is not None else 5.0

    def _it_valuation(
        self,
        data:   dict,
        equity: float,
        flags:  List[str],
    ) -> Tuple[Optional[float], Optional[str], float]:
        """P/B odaklı valuation. revenue kullanılmaz."""
        try:
            bs   = data.get("bs", pd.DataFrame())
            info = data.get("info") or {}
            yf   = data.get("yf", False)

            pb: Optional[float] = None

            if isinstance(info, dict):
                # 1. yfinance info.priceToBook
                ptb = info.get("priceToBook")
                if ptb is not None and np.isfinite(ptb) and ptb > 0:
                    pb = float(ptb)

                # 2. marketCap / equity
                if pb is None:
                    mc = info.get("marketCap")
                    if mc and float(mc) > 0 and equity > 0:
                        pb = float(mc) / equity

                # 3. last_price × paid_capital / equity (borsapy path)
                if pb is None and not yf:
                    last_price = info.get("last")
                    if last_price and float(last_price) > 0 and equity > 0:
                        odenmis = _get_row(bs, _PAID_CAPITAL_KEYS)
                        if odenmis and odenmis > 0:
                            pb = (float(last_price) * odenmis) / equity

            if pb is None or pb <= 0:
                flags.append(
                    "Investment trust valuation: P/B hesaplanamadı "
                    "(fiyat/piyasa değeri verisi yok)."
                )
                return None, "missing", 0.0

            score = self._it_pb_score(pb, flags)
            return round(score, 2), None, 1.0

        except Exception as e:
            logger.warning(f"[fundamental/it] valuation: {e}")
            return None, "missing", 0.0

    def _it_nav_growth(
        self,
        data:  dict,
        flags: List[str],
    ) -> Tuple[Optional[float], Optional[str], float]:
        """Equity YoY büyüme. Cap ±200%. Normalize: -20%→0, +50%→10."""
        try:
            yf   = data.get("yf", False)
            bs   = data.get("bs", pd.DataFrame())
            bs_y = data.get("bs_y")

            equity_t:    Optional[float] = None
            equity_prev: Optional[float] = None

            if yf:
                equity_t = _yf_get(bs, YF_TOTAL_EQUITY_KEYS)
                n_bs     = bs.shape[1]
                # t-4 quarterly deneme
                if n_bs >= 5:
                    for k in YF_TOTAL_EQUITY_KEYS:
                        if k in bs.index:
                            v = bs.loc[k].iloc[4]
                            if pd.notna(v):
                                equity_prev = float(v)
                                break
                # Yıllık fallback
                if equity_prev is None and bs_y is not None and bs_y.shape[1] >= 2:
                    for k in YF_TOTAL_EQUITY_KEYS:
                        if k in bs_y.index:
                            v = bs_y.loc[k].iloc[1]
                            if pd.notna(v):
                                equity_prev = float(v)
                                break
            elif data.get("isyat"):
                # isyatirim quarterly: YoY = col 0 (son çeyrek) vs col 4 (1 yıl önce aynı çeyrek)
                equity_t    = _get_row_period(bs, _EQUITY_KEYS, 0)
                equity_prev = _get_row_period(bs, _EQUITY_KEYS, 4) if bs.shape[1] >= 5 else None
            else:
                # borsapy_yearly: col 0 = son yıl, col 1 = önceki yıl
                equity_t    = _get_row_period(bs, _EQUITY_KEYS, 0)
                equity_prev = _get_row_period(bs, _EQUITY_KEYS, 1)

            if equity_t is None or equity_prev is None or equity_prev == 0:
                return None, "missing", 0.0

            nav_growth = max(-2.0, min(2.0, (equity_t - equity_prev) / abs(equity_prev)))
            score      = _normalize(nav_growth, -0.20, 0.50)
            if score is None:
                return None, "missing", 0.0
            return round(score, 2), None, 1.0

        except Exception as e:
            logger.warning(f"[fundamental/it] nav_growth: {e}")
            return None, "missing", 0.0

    def _it_stability(
        self,
        data:  dict,
        flags: List[str],
    ) -> Tuple[Optional[float], Optional[str], float]:
        """Son 4 yılda pozitif NI sayısı + NI volatilitesi. CV cap 3.0."""
        try:
            yf   = data.get("yf", False)
            is_  = data.get("is_", pd.DataFrame())
            is_y = data.get("is_y")

            ni_series: List[float] = []

            if yf:
                # Yıllık veri tercih (GSYO için portföy değer hareketleri quarterly'de gürültülü)
                if is_y is not None and not is_y.empty:
                    for k in YF_NET_INCOME_KEYS:
                        if k in is_y.index:
                            ni_series = [float(v) for v in is_y.loc[k] if pd.notna(v)]
                            break
                if not ni_series:
                    for k in YF_NET_INCOME_KEYS:
                        if k in is_.index:
                            ni_series = [float(v) for v in is_.loc[k] if pd.notna(v)]
                            break
            else:
                # borsapy_yearly — en fazla 6 yıl al
                n = min(6, is_.shape[1])
                ni_series = [
                    v for v in
                    [_get_row_period(is_, _NET_PROFIT_KEYS, i) for i in range(n)]
                    if v is not None
                ]

            if not ni_series:
                return None, "missing", 0.0

            ni_last4 = ni_series[:4]
            scored: List[Tuple[float, float]] = []
            miss = 0

            n_periods = max(len(ni_last4), 1)
            pos_count = sum(1 for v in ni_last4 if v > 0)
            scored.append(((pos_count / n_periods) * 10.0, 0.60))

            # Volatilite CV — GSYO/MKYO için geniş bant (3.0)
            if len(ni_series) >= 2:
                mean_abs = abs(float(np.mean(ni_series)))
                if mean_abs > 0:
                    cv = float(np.std(ni_series)) / mean_abs
                    s  = _normalize(cv, 0.0, 3.0, reverse=True)
                    if s is not None:
                        scored.append((s, 0.40))
                    else:
                        miss += 1
                else:
                    miss += 1
            else:
                miss += 1

            if not scored:
                return None, "missing", 0.0
            mq = round(len(scored) / 2, 2)
            tw = sum(w for _, w in scored)
            return round(sum(s * w for s, w in scored) / tw, 2), None, mq

        except Exception as e:
            logger.warning(f"[fundamental/it] stability: {e}")
            return None, "missing", 0.0

    def _it_leverage(
        self,
        equity:       float,
        total_assets: float,
        flags:        List[str],
    ) -> Tuple[Optional[float], Optional[str], float]:
        """Debt/Assets = max(TA - Equity, 0) / TA. Reverse: 0.00→10, 0.20→0."""
        try:
            if total_assets <= 0:
                return None, "missing", 0.0
            implied_debt = max(total_assets - equity, 0.0)
            debt_ratio   = implied_debt / total_assets
            score = _normalize(debt_ratio, 0.0, 0.20, reverse=True)
            if score is None:
                return None, "missing", 0.0
            return round(score, 2), None, 1.0
        except Exception as e:
            logger.warning(f"[fundamental/it] leverage: {e}")
            return None, "missing", 0.0

    def _it_explain(
        self,
        subscores: FundamentalSubscores,
        val_score: Optional[float],
        nav_score: Optional[float],
    ) -> str:
        """Investment trust açıklama metni."""
        parts: List[str] = []

        if val_score is not None:
            if val_score >= 7.0:
                parts.append(
                    "Değerleme göstergeleri özkaynak/NAV bazında destekleyici seyretmektedir."
                )
            elif val_score >= 4.0:
                parts.append(
                    "Değerleme göstergeleri özkaynak/NAV bazında orta düzeyde seyretmektedir."
                )
            else:
                parts.append(
                    "Değerleme göstergeleri özkaynak/NAV bazında sınırlayıcı etki oluşturmaktadır."
                )

        if nav_score is not None:
            if nav_score >= 7.0:
                parts.append("NAV/özkaynak büyüme göstergeleri güçlü seyretmektedir.")
            elif nav_score >= 4.0:
                parts.append("NAV/özkaynak büyüme göstergeleri orta düzeyde seyretmektedir.")
            else:
                parts.append("NAV/özkaynak büyüme göstergeleri sınırlı seyretmektedir.")

        if subscores.stability is not None:
            if subscores.stability >= 7.0:
                parts.append("Net kar istikrarı güçlü seyretmektedir.")
            elif subscores.stability >= 4.0:
                parts.append("Net kar istikrarı orta düzeyde seyretmektedir.")
            else:
                parts.append("Net kar istikrarı sınırlı seyretmektedir.")

        if subscores.balance_sheet is not None:
            if subscores.balance_sheet >= 7.0:
                parts.append("Bilanço kaldıraç düzeyi düşük görünmektedir.")
            elif subscores.balance_sheet >= 4.0:
                parts.append("Bilanço kaldıraç düzeyi orta düzeyde seyretmektedir.")
            else:
                parts.append("Bilanço kaldıraç düzeyi yüksek görünmektedir.")

        if not parts:
            return "Finansal tablo verisiyle değerlendirme yapıldı."
        return " ".join(parts)

    # ════════════════════════════════════════════════════════════════════════
    # Insurance V1 Model
    # ════════════════════════════════════════════════════════════════════════

    def _ins_annual_ni_col_idx(self, df: pd.DataFrame) -> int:
        """isyatirim G2 sigorta verisi için en güncel FY (ay=12) kolon indeksi.

        Sigorta tabloları kümülatif raporlanır; FY değeri ay=12 kolonundan alınır.
        Yıllık kolon yoksa 0 (en güncel çeyrek) döner.
        """
        best_idx = 0
        best_ym  = (0, 0)
        for i, col in enumerate(df.columns):
            t = _parse_col_period(col)
            if t and t[1] == 12 and (t[0], t[1]) > best_ym:
                best_ym  = (t[0], t[1])
                best_idx = i
        return best_idx

    def _calculate_insurance(
        self,
        ticker:       str,
        sector_group: str,
        flags:        List[str],
    ) -> FundamentalResult:
        """Insurance V1 Modeli.

        Kaynak: isyatirim_quarterly (group=2, UFRS sigorta teknik format).
        Revenue / gross_margin / current_ratio / Piotroski kullanılmaz.
        Teknik performans: J- Genel Teknik Bölüm Dengesi / toplam teknik gelir.
        FY net kar: kümülatif tabloda ay=12 kolonu.
        """
        data = self._fetch_data(ticker, sector_group, flags)
        if data is None:
            return self._empty_result(ticker, sector_group, flags, "veri çekilemedi")

        df = data["is_"]   # isyatirim: is_ = bs = cf = df_combined
        bs = data["bs"]

        # ── Zorunlu metrikler ────────────────────────────────────────────────
        fy_idx       = self._ins_annual_ni_col_idx(df)
        annual_ni    = _get_row_period(df, _INS_NET_PROFIT_KEYS, fy_idx)
        equity       = _get_row(bs, _EQUITY_KEYS)       # "Total Equity"
        total_assets = _get_row(bs, _TOTAL_ASSETS_KEYS) # "AKTİF TOPLAMI"

        if annual_ni is None or equity is None or total_assets is None:
            flags.append(
                "Sigorta modeli için zorunlu metrikler eksik "
                "(net_income / equity / total_assets); skor hesaplanamadı."
            )
            return self._empty_result(ticker, sector_group, flags, "zorunlu metrikler eksik")

        # ── Alt skorlar ──────────────────────────────────────────────────────
        prof_s, prof_r, prof_q = self._ins_profitability(
            data, annual_ni, equity, total_assets, flags
        )
        tech_s, tech_r, tech_q = self._ins_technical_perf(data, flags)
        grow_s, grow_r, grow_q = self._ins_growth(data, flags)
        stab_s, stab_r, stab_q = self._ins_stability(data, fy_idx, flags)
        val_s,  val_r,  val_q  = self._ins_valuation(data, annual_ni, equity, flags)

        # ── Piotroski: not_applicable ────────────────────────────────────────
        flags.append(_INS_PIOTROSKI_NA_MSG)
        piotr_na = PiotroskiResult(
            score=None, normalized=None, calculated_criteria=0,
            total_criteria=9, coverage=0.0, confidence="not_applicable",
            applicability="not_applicable", missing_criteria=[], details={},
        )

        reasons = {
            "profitability": (prof_s, prof_r, prof_q),
            "balance_sheet": (tech_s, tech_r, tech_q),   # technical_perf
            "cash_flow":     (None,   "not_applicable", 1.0),
            "growth":        (grow_s, grow_r, grow_q),
            "valuation":     (val_s,  val_r,  val_q),
            "stability":     (stab_s, stab_r, stab_q),
            "piotroski":     (None,   "not_applicable", 1.0),
        }
        final_score, quality = self._weighted_average(reasons, _INS_WEIGHTS)

        if quality < 0.55:
            final_score = None
            flags.append(
                f"Sigorta finansal skoru hesaplanamadı: genel veri kalitesi "
                f"yetersiz (quality={quality:.2f} < 0.55)."
            )

        if final_score is not None:
            final_score = round(max(0.0, min(10.0, final_score)), 2)

        flags.append(
            "Sigorta modeli V1: teknik performans skoru "
            "finansal_subscores.balance_sheet alanında raporlanmaktadır."
        )

        subscores = FundamentalSubscores(
            profitability = _r2(prof_s),
            balance_sheet = _r2(tech_s),
            cash_flow     = None,
            growth        = _r2(grow_s),
            valuation     = _r2(val_s),
            stability     = _r2(stab_s),
            piotroski     = None,
        )

        explanation = self._ins_explain(subscores, tech_s)
        if _contains_forbidden(explanation):
            explanation = "Finansal tablo verisiyle değerlendirme yapıldı."

        return FundamentalResult(
            ticker=ticker,
            financial_score=final_score,
            financial_score_label=self._label(final_score),
            financial_score_quality=round(quality, 2),
            subscores=subscores,
            piotroski=piotr_na,
            financial_flags=flags,
            explanation=explanation,
            sector_group=sector_group,
            data_source=data.get("data_source", "isyatirim_quarterly"),
            period=data.get("period"),
        )

    def _ins_profitability(
        self,
        data:         dict,
        annual_ni:    float,
        equity:       float,
        total_assets: float,
        flags:        List[str],
    ) -> Tuple[Optional[float], Optional[str], float]:
        """ROE (FY) + ROA (FY). revenue kullanılmaz."""
        try:
            scored: List[Tuple[float, float]] = []
            miss = 0

            s = _normalize(_safe_div(annual_ni, equity), 0.0, 0.30)
            if s is not None: scored.append((s, 0.50))
            else:             miss += 1

            s = _normalize(_safe_div(annual_ni, total_assets), 0.0, 0.15)
            if s is not None: scored.append((s, 0.50))
            else:             miss += 1

            if not scored:
                return None, "missing", 0.0
            mq = round(len(scored) / 2, 2)
            tw = sum(w for _, w in scored)
            return round(sum(s * w for s, w in scored) / tw, 2), None, mq

        except Exception as e:
            logger.warning(f"[fundamental/ins] profitability: {e}")
            return None, "missing", 0.0

    def _ins_technical_perf(
        self,
        data:  dict,
        flags: List[str],
    ) -> Tuple[Optional[float], Optional[str], float]:
        """Teknik performans: teknik denge / |toplam teknik gelir|.

        Önce J- Genel Teknik Bölüm Dengesi, yoksa C+F+I toplamı.
        Normalize: -0.20 → 0, +0.20 → 10.
        """
        try:
            df = data["is_"]

            # Teknik denge — J- birleşik toplamı önce
            tech_balance = _get_row(df, ["J- Genel Teknik Bölüm Dengesi"])
            if tech_balance is None:
                parts = [
                    _get_row(df, ["C- Teknik Bölüm Dengesi- Hayat Dışı"]),
                    _get_row(df, ["F- Teknik Bölüm Dengesi- Hayat"]),
                    _get_row(df, ["I- Teknik Bölüm Dengesi- Emeklilik",
                                   "I - Teknik Bölüm Dengesi- Emeklilik"]),
                ]
                valid = [v for v in parts if v is not None]
                tech_balance = sum(valid) if valid else None

            if tech_balance is None:
                return None, "missing", 0.0

            # Toplam teknik gelir: A + D + G
            tech_income = 0.0
            n_found = 0
            for key in _INS_TECHNICAL_INCOME_KEYS:
                v = _get_row(df, [key])
                if v is not None:
                    tech_income += v
                    n_found += 1

            if n_found == 0 or tech_income == 0:
                return None, "missing", 0.0

            ratio = tech_balance / abs(tech_income)
            score = _normalize(ratio, -0.20, 0.20)
            if score is None:
                return None, "missing", 0.0
            return round(score, 2), None, 1.0

        except Exception as e:
            logger.warning(f"[fundamental/ins] technical_perf: {e}")
            return None, "missing", 0.0

    def _ins_growth(
        self,
        data:  dict,
        flags: List[str],
    ) -> Tuple[Optional[float], Optional[str], float]:
        """NI YoY + Equity YoY + Prim YoY. col 0 vs col 4 (aynı çeyrek). Cap ±200%."""
        try:
            df   = data["is_"]
            bs   = data["bs"]
            n_df = df.shape[1]
            n_bs = bs.shape[1]

            def yoy(curr, prev):
                if curr is None or prev is None or prev == 0:
                    return None
                return max(-2.0, min(2.0, (curr - prev) / abs(prev)))

            scored: List[Tuple[float, float]] = []
            miss = 0

            # Net Income YoY
            ni_c = _get_row_period(df, _INS_NET_PROFIT_KEYS, 0)
            ni_p = _get_row_period(df, _INS_NET_PROFIT_KEYS, 4) if n_df >= 5 else None
            s = _normalize(yoy(ni_c, ni_p), -0.20, 0.50)
            if s is not None: scored.append((s, 0.40))
            else:             miss += 1

            # Equity YoY
            eq_c = _get_row_period(bs, _EQUITY_KEYS, 0)
            eq_p = _get_row_period(bs, _EQUITY_KEYS, 4) if n_bs >= 5 else None
            s = _normalize(yoy(eq_c, eq_p), -0.20, 0.50)
            if s is not None: scored.append((s, 0.35))
            else:             miss += 1

            # Premium YoY
            pr_c = _get_row_period(df, _INS_PREMIUM_KEYS, 0)
            pr_p = _get_row_period(df, _INS_PREMIUM_KEYS, 4) if n_df >= 5 else None
            s = _normalize(yoy(pr_c, pr_p), -0.20, 0.50)
            if s is not None: scored.append((s, 0.25))
            else:             miss += 1

            if not scored:
                return None, "missing", 0.0
            mq = round(len(scored) / 3, 2)
            tw = sum(w for _, w in scored)
            return round(min(sum(s * w for s, w in scored) / tw, 9.5), 2), None, mq

        except Exception as e:
            logger.warning(f"[fundamental/ins] growth: {e}")
            return None, "missing", 0.0

    def _ins_stability(
        self,
        data:   dict,
        fy_idx: int,
        flags:  List[str],
    ) -> Tuple[Optional[float], Optional[str], float]:
        """Son 4 FY'de pozitif NI sayısı + NI volatilitesi. CV cap 3.0."""
        try:
            df = data["is_"]

            # Tüm FY (ay=12) kolon indekslerini bul
            fy_indices: List[int] = []
            for i, col in enumerate(df.columns):
                t = _parse_col_period(col)
                if t and t[1] == 12:
                    fy_indices.append(i)
            fy_indices.sort()   # DataFrame zaten newest-first → küçük index = yeni

            ni_series: List[float] = []
            for idx in fy_indices[:4]:
                v = _get_row_period(df, _INS_NET_PROFIT_KEYS, idx)
                if v is not None:
                    ni_series.append(v)

            # FY kolon yoksa son 4 çeyrekle fallback
            if not ni_series:
                for i in range(min(4, df.shape[1])):
                    v = _get_row_period(df, _INS_NET_PROFIT_KEYS, i)
                    if v is not None:
                        ni_series.append(v)

            if not ni_series:
                return None, "missing", 0.0

            scored: List[Tuple[float, float]] = []
            miss = 0

            pos_count = sum(1 for v in ni_series if v > 0)
            scored.append(((pos_count / len(ni_series)) * 10.0, 0.60))

            if len(ni_series) >= 2:
                mean_abs = abs(float(np.mean(ni_series)))
                if mean_abs > 0:
                    cv = float(np.std(ni_series)) / mean_abs
                    s  = _normalize(cv, 0.0, 3.0, reverse=True)
                    if s is not None: scored.append((s, 0.40))
                    else:             miss += 1
                else:
                    miss += 1
            else:
                miss += 1

            if not scored:
                return None, "missing", 0.0
            mq = round(len(scored) / 2, 2)
            tw = sum(w for _, w in scored)
            return round(sum(s * w for s, w in scored) / tw, 2), None, mq

        except Exception as e:
            logger.warning(f"[fundamental/ins] stability: {e}")
            return None, "missing", 0.0

    def _ins_valuation(
        self,
        data:      dict,
        annual_ni: float,
        equity:    float,
        flags:     List[str],
    ) -> Tuple[Optional[float], Optional[str], float]:
        """P/E + P/B. yfinance info öncelikli, fallback marketCap hesabı."""
        try:
            info      = data.get("info") or {}
            fk_high   = _FK_HIGH.get("insurance", 20.0)
            pddd_high = _PDDD_HIGH.get("insurance", 2.0)

            scored: List[Tuple[float, float]] = []
            miss = 0

            # P/E
            pe_added    = False
            trailing_pe = info.get("trailingPE") if isinstance(info, dict) else None
            if trailing_pe and np.isfinite(trailing_pe) and trailing_pe > 0:
                s = _normalize(trailing_pe, 0.0, fk_high, reverse=True)
                if s is not None:
                    scored.append((s, 0.50))
                    pe_added = True
            if not pe_added:
                market_cap = info.get("marketCap") if isinstance(info, dict) else None
                if market_cap and annual_ni and annual_ni > 0:
                    pe = market_cap / annual_ni
                    if pe > 0:
                        s = _normalize(pe, 0.0, fk_high, reverse=True)
                        if s is not None:
                            scored.append((s, 0.50))
                            pe_added = True
                if not pe_added:
                    miss += 1

            # P/B
            pb_added      = False
            price_to_book = info.get("priceToBook") if isinstance(info, dict) else None
            if price_to_book and np.isfinite(price_to_book) and price_to_book > 0:
                s = _normalize(price_to_book, 0.0, pddd_high, reverse=True)
                if s is not None:
                    scored.append((s, 0.50))
                    pb_added = True
            if not pb_added:
                market_cap = info.get("marketCap") if isinstance(info, dict) else None
                if market_cap and equity and equity > 0:
                    pb = market_cap / equity
                    if pb > 0:
                        s = _normalize(pb, 0.0, pddd_high, reverse=True)
                        if s is not None:
                            scored.append((s, 0.50))
                            pb_added = True
                if not pb_added:
                    miss += 1

            if not scored:
                return None, "missing", 0.0
            mq = round(len(scored) / 2, 2)
            tw = sum(w for _, w in scored)
            return round(sum(s * w for s, w in scored) / tw, 2), None, mq

        except Exception as e:
            logger.warning(f"[fundamental/ins] valuation: {e}")
            return None, "missing", 0.0

    def _ins_explain(
        self,
        subscores:  FundamentalSubscores,
        tech_score: Optional[float],
    ) -> str:
        """Insurance açıklama metni."""
        parts: List[str] = []

        if subscores.profitability is not None:
            if subscores.profitability >= 7.0:
                parts.append(
                    "Karlılık göstergeleri (ROE/ROA) destekleyici seyretmektedir."
                )
            elif subscores.profitability >= 4.0:
                parts.append(
                    "Karlılık göstergeleri (ROE/ROA) orta düzeyde seyretmektedir."
                )
            else:
                parts.append(
                    "Karlılık göstergeleri (ROE/ROA) sınırlayıcı etki oluşturmaktadır."
                )

        if tech_score is not None:
            if tech_score >= 7.0:
                parts.append("Teknik bölüm dengesi güçlü seyretmektedir.")
            elif tech_score >= 4.0:
                parts.append("Teknik bölüm dengesi orta düzeyde seyretmektedir.")
            else:
                parts.append("Teknik bölüm dengesi zayıf seyretmektedir.")

        if subscores.growth is not None:
            if subscores.growth >= 7.0:
                parts.append(
                    "Büyüme göstergeleri (net kar/özkaynak/prim) güçlü seyretmektedir."
                )
            elif subscores.growth >= 4.0:
                parts.append("Büyüme göstergeleri orta düzeyde seyretmektedir.")
            else:
                parts.append("Büyüme göstergeleri sınırlı seyretmektedir.")

        if subscores.stability is not None:
            if subscores.stability >= 7.0:
                parts.append("Net kar sürekliliği güçlü görünmektedir.")
            elif subscores.stability >= 4.0:
                parts.append("Net kar sürekliliği orta düzeyde seyretmektedir.")
            else:
                parts.append("Net kar sürekliliği sınırlı seyretmektedir.")

        if not parts:
            return "Finansal tablo verisiyle değerlendirme yapıldı."
        return " ".join(parts)

    # ════════════════════════════════════════════════════════════════════════
    # GYO V1 Model
    # ════════════════════════════════════════════════════════════════════════

    def _calculate_gyo(
        self,
        ticker:       str,
        sector_group: str,
        flags:        List[str],
    ) -> FundamentalResult:
        """GYO V1 modeli (Gayrimenkul Yatırım Ortaklığı).

        Primary: isyatirim_quarterly → borsapy_yearly (fallback).
        yfinance: sadece valuation için (P/B, P/E, marketCap).
        cash_flow: not_applicable (inşaat GYO yapısal negatif OCF).
        piotroski: limited, gösterilir ama final skora dahil değil.
        Revenue: hiçbir hesaplamada kullanılmaz.
        """
        data = self._fetch_data(ticker, sector_group, flags)
        if data is None:
            return self._empty_result(ticker, sector_group, flags, "veri çekilemedi")

        bs    = data["bs"]
        isyat = data.get("isyat", False)
        yf    = data.get("yf", False)

        # ── Zorunlu metrikler (equity + total_assets) ────────────────────────
        if isyat or not yf:
            equity       = _get_row(bs, _EQUITY_KEYS)
            total_assets = _get_row(bs, _TOTAL_ASSETS_KEYS)
        else:
            equity       = _yf_get(bs, YF_TOTAL_EQUITY_KEYS)
            total_assets = _yf_get(bs, YF_TOTAL_ASSETS_KEYS)

        if equity is None or total_assets is None:
            flags.append(
                "GYO modeli için zorunlu metrikler eksik "
                "(equity / total_assets); skor hesaplanamadı."
            )
            return self._empty_result(
                ticker, sector_group, flags, "zorunlu metrikler eksik"
            )

        if equity < 0:
            flags.append("GYO: Negatif özkaynak tespit edildi.")
            return self._empty_result(
                ticker, sector_group, flags, "negatif özkaynak"
            )

        # ── Sabit flagler ────────────────────────────────────────────────────
        flags.append(
            "GYO V1 modeli: nakit akışı GYO iş modeli gereği "
            "final skora dahil edilmedi."
        )
        flags.append(
            "GYO V1 modeli: karlılık metrikleri yatırım amaçlı gayrimenkul "
            "yeniden değerleme etkisi içerebilir."
        )

        # ── Alt skor hesabı ──────────────────────────────────────────────────
        prof_s, prof_r, prof_q = self._gyo_profitability(
            data, equity, total_assets, flags
        )
        as_s,   as_r,   as_q   = self._gyo_asset_strength(
            data, equity, total_assets, flags
        )
        grow_s, grow_r, grow_q = self._gyo_growth(data, flags)
        val_s,  val_r,  val_q  = self._gyo_valuation(data, flags)
        stab_s, stab_r, stab_q = self._gyo_stability(data, flags)

        # ── Piotroski: limited, final skora dahil değil ──────────────────────
        piotr = self._compute_piotroski(data, "gyo", flags)

        reasons = {
            "profitability": (prof_s, prof_r,  prof_q),
            "balance_sheet": (as_s,   as_r,    as_q),   # asset_strength
            "cash_flow":     (None,   "not_applicable", 1.0),
            "growth":        (grow_s, grow_r,  grow_q),
            "valuation":     (val_s,  val_r,   val_q),
            "stability":     (stab_s, stab_r,  stab_q),
            "piotroski":     (None,   "not_applicable", 1.0),
        }
        final_score, quality = self._weighted_average(reasons, _GYO_WEIGHTS)

        if quality < 0.35:
            final_score = None
            flags.append(
                f"GYO finansal skoru hesaplanamadı: veri kalitesi eşiğin "
                f"altında (quality={quality:.2f} < 0.35)."
            )
        elif quality < 0.55:
            flags.append("GYO skoru sınırlı veriyle hesaplanmıştır.")

        if final_score is not None:
            final_score = round(max(0.0, min(10.0, final_score)), 2)

        subscores = FundamentalSubscores(
            profitability = _r2(prof_s),
            balance_sheet = _r2(as_s),     # asset_strength
            cash_flow     = None,
            growth        = _r2(grow_s),
            valuation     = _r2(val_s),
            stability     = _r2(stab_s),
            piotroski     = _r2(piotr.normalized) if piotr else None,
        )

        explanation = self._gyo_explain(subscores)
        if _contains_forbidden(explanation):
            explanation = "Finansal tablo verisiyle değerlendirme yapıldı."

        return FundamentalResult(
            ticker=ticker,
            financial_score=final_score,
            financial_score_label=self._label(final_score),
            financial_score_quality=round(quality, 2),
            subscores=subscores,
            piotroski=piotr,
            financial_flags=flags,
            explanation=explanation,
            sector_group=sector_group,
            data_source=data.get("data_source", "isyatirim_quarterly"),
            period=data.get("period"),
        )

    def _gyo_profitability(
        self,
        data:         dict,
        equity:       float,
        total_assets: float,
        flags:        List[str],
    ) -> Tuple[Optional[float], Optional[str], float]:
        """ROE + ROA. TTM NI (isyatirim) / col-0 NI (borsapy).
        Revenue, gross_margin, op_margin kullanılmaz.
        """
        try:
            df    = data["is_"]
            isyat = data.get("isyat", False)
            yf    = data.get("yf", False)

            if isyat:
                ni = _iy_ttm_sum(df, _NET_PROFIT_KEYS, n=4, min_valid=2)
                # Negatif çeyrek sayısını kontrol et
                neg_count = sum(
                    1 for i in range(min(4, df.shape[1]))
                    if (_get_row_period(df, _NET_PROFIT_KEYS, i) or 0) < 0
                )
                if neg_count >= 2:
                    flags.append(
                        "GYO: Net kâr son dönemlerde negatif; "
                        "yeniden değerleme etkisi bulunabilir."
                    )
            elif yf:
                ni = _yf_ttm(df, YF_NET_INCOME_KEYS)
            else:
                ni = _get_row(df, _NET_PROFIT_KEYS)

            scored: List[Tuple[float, float]] = []
            miss = 0

            # ROE = NI / equity  [0.00, 0.30]
            s = _normalize(_safe_div(ni, equity), 0.0, 0.30)
            if s is not None: scored.append((s, 0.50))
            else:             miss += 1

            # ROA = NI / total_assets  [0.00, 0.15]
            s = _normalize(_safe_div(ni, total_assets), 0.0, 0.15)
            if s is not None: scored.append((s, 0.50))
            else:             miss += 1

            if not scored:
                return None, "missing", 0.0
            mq = round(len(scored) / 2, 2)
            tw = sum(w for _, w in scored)
            return round(sum(s * w for s, w in scored) / tw, 2), None, mq

        except Exception as e:
            logger.warning(f"[fundamental/gyo] profitability: {e}")
            return None, "missing", 0.0

    def _gyo_asset_strength(
        self,
        data:         dict,
        equity:       float,
        total_assets: float,
        flags:        List[str],
    ) -> Tuple[Optional[float], Optional[str], float]:
        """Equity Ratio (60%) + Debt/Assets (40%).

        Equity Ratio = equity / total_assets  [0.20 → 0, 0.80 → 10]
        Debt / Assets = financial_debt / total_assets  [0.00 → 10, 0.50 → 0]  reverse
        current_ratio, debt/ebitda, interest_coverage kullanılmaz.
        """
        try:
            bs    = data["bs"]
            isyat = data.get("isyat", False)
            yf    = data.get("yf", False)

            if isyat:
                fin_debt = _get_row(bs, _FIN_DEBT_KEYS)
            elif yf:
                fin_debt = _yf_get(bs, YF_TOTAL_DEBT_KEYS)
            else:
                fin_debt = _sum_key_latest(bs, "Finansal Borçlar")

            scored: List[Tuple[float, float]] = []
            miss = 0

            # Equity Ratio  [0.20 → 0, 0.80 → 10]
            s = _normalize(_safe_div(equity, total_assets), 0.20, 0.80)
            if s is not None: scored.append((s, 0.60))
            else:             miss += 1

            # Debt / Assets  [0.00 → 10, 0.50 → 0]  reverse
            if fin_debt is not None and total_assets > 0:
                s = _normalize(fin_debt / total_assets, 0.0, 0.50, reverse=True)
                if s is not None: scored.append((s, 0.40))
                else:             miss += 1
            else:
                miss += 1

            if not scored:
                return None, "missing", 0.0
            mq = round(len(scored) / 2, 2)
            tw = sum(w for _, w in scored)
            return round(sum(s * w for s, w in scored) / tw, 2), None, mq

        except Exception as e:
            logger.warning(f"[fundamental/gyo] asset_strength: {e}")
            return None, "missing", 0.0

    def _gyo_growth(
        self,
        data:  dict,
        flags: List[str],
    ) -> Tuple[Optional[float], Optional[str], float]:
        """Equity YoY (60%) + Net Income YoY (40%).
        Revenue kullanılmaz (konut proje teslim döngüsüne bağlı volatilite).
        YoY: aynı çeyrek karşılaştırması (col i vs col i+4).
        """
        try:
            df    = data["is_"]
            bs    = data["bs"]
            isyat = data.get("isyat", False)
            yf    = data.get("yf", False)

            def yoy(curr: Optional[float], prior: Optional[float]) -> Optional[float]:
                if curr is None or prior is None or prior == 0:
                    return None
                return max(-1.0, min(5.0, (curr - prior) / abs(prior)))

            eq_yoys: List[float] = []
            ni_yoys: List[float] = []

            if isyat:
                n = min(df.shape[1], bs.shape[1])

                def _get_at(frame: pd.DataFrame, keys: List[str], col: int) -> Optional[float]:
                    if col >= frame.shape[1]:
                        return None
                    idx = frame.index.str.strip()
                    for k in keys:
                        m = frame[idx == k.strip()]
                        if not m.empty:
                            v = m.iloc[0, col]
                            return float(v) if pd.notna(v) else None
                    return None

                for i in range(n - 4):
                    r = yoy(_get_at(bs, _EQUITY_KEYS, i),
                            _get_at(bs, _EQUITY_KEYS, i + 4))
                    if r is not None:
                        eq_yoys.append(r)
                    r = yoy(_get_at(df, _NET_PROFIT_KEYS, i),
                            _get_at(df, _NET_PROFIT_KEYS, i + 4))
                    if r is not None:
                        ni_yoys.append(r)

            elif yf:
                bs_y = data.get("bs_y")
                is_y = data.get("is_y")
                n_bs = bs.shape[1]
                n_is = df.shape[1]

                def _yf_at(frame: Optional[pd.DataFrame], keys: List[str],
                            col: int) -> Optional[float]:
                    if frame is None:
                        return None
                    for k in keys:
                        if k in frame.index and col < frame.shape[1]:
                            v = frame.loc[k].iloc[col]
                            return float(v) if pd.notna(v) else None
                    return None

                eq_c = _yf_at(bs, YF_TOTAL_EQUITY_KEYS, 0)
                eq_p = _yf_at(bs, YF_TOTAL_EQUITY_KEYS, 4) if n_bs >= 5 else None
                if (eq_c is None or eq_p is None) and bs_y is not None:
                    eq_c = _yf_at(bs_y, YF_TOTAL_EQUITY_KEYS, 0)
                    eq_p = _yf_at(bs_y, YF_TOTAL_EQUITY_KEYS, 1)
                r = yoy(eq_c, eq_p)
                if r is not None:
                    eq_yoys.append(r)

                ni_c = _yf_ttm(df, YF_NET_INCOME_KEYS, start=0)
                ni_p = _yf_ttm(df, YF_NET_INCOME_KEYS, start=4) if n_is >= 8 else None
                if (ni_c is None or ni_p is None) and is_y is not None:
                    ni_c = _yf_at(is_y, YF_NET_INCOME_KEYS, 0)
                    ni_p = _yf_at(is_y, YF_NET_INCOME_KEYS, 1)
                r = yoy(ni_c, ni_p)
                if r is not None:
                    ni_yoys.append(r)

            else:
                # borsapy_yearly: col i+1 = geçen yıl
                n = min(bs.shape[1], df.shape[1])
                for i in range(n - 1):
                    r = yoy(_get_row_period(bs, _EQUITY_KEYS, i),
                            _get_row_period(bs, _EQUITY_KEYS, i + 1))
                    if r is not None:
                        eq_yoys.append(r)
                    r = yoy(_get_row_period(df, _NET_PROFIT_KEYS, i),
                            _get_row_period(df, _NET_PROFIT_KEYS, i + 1))
                    if r is not None:
                        ni_yoys.append(r)

            def avg(lst: List[float]) -> Optional[float]:
                return float(np.mean(lst)) if lst else None

            scored: List[Tuple[float, float]] = []
            miss = 0

            s = _normalize(avg(eq_yoys), *_T["growth"])
            if s is not None: scored.append((s, 0.60))
            else:             miss += 1

            s = _normalize(avg(ni_yoys), *_T["growth"])
            if s is not None: scored.append((s, 0.40))
            else:             miss += 1

            if not scored:
                return None, "missing", 0.0
            mq = round(len(scored) / 2, 2)
            tw = sum(w for _, w in scored)
            return round(min(sum(s * w for s, w in scored) / tw, 9.5), 2), None, mq

        except Exception as e:
            logger.warning(f"[fundamental/gyo] growth: {e}")
            return None, "missing", 0.0

    def _gyo_valuation(
        self,
        data:  dict,
        flags: List[str],
    ) -> Tuple[Optional[float], Optional[str], float]:
        """P/B (70%) + P/E koşullu (30%).

        P/B: GYO NAV proxy — _PDDD_HIGH["gyo"] = 1.5.
        P/E: sadece 0 < P/E < 30 ise dahil edilir.
        """
        try:
            info      = data.get("info") or {}
            fk_high   = _FK_HIGH.get("gyo", 20.0)
            pddd_high = _PDDD_HIGH.get("gyo", 1.5)

            scored: List[Tuple[float, float]] = []
            miss = 0

            # ── P/B (70%) ─────────────────────────────────────────────────────
            pb_added      = False
            price_to_book = info.get("priceToBook") if isinstance(info, dict) else None
            if price_to_book and np.isfinite(price_to_book) and price_to_book > 0:
                s = _normalize(price_to_book, 0.0, pddd_high, reverse=True)
                if s is not None:
                    if price_to_book < 0.15:
                        flags.append(
                            "GYO: P/B seviyesi düşük görünmektedir; bu durum "
                            "tek başına olumlu veya olumsuz yorumlanmamalıdır."
                        )
                    scored.append((s, 0.70))
                    pb_added = True

            # P/B fallback: marketCap / equity
            if not pb_added:
                market_cap = info.get("marketCap") if isinstance(info, dict) else None
                bs         = data["bs"]
                isyat_f    = data.get("isyat", False)
                yf_f       = data.get("yf", False)
                eq = (_get_row(bs, _EQUITY_KEYS) if (isyat_f or not yf_f)
                      else _yf_get(bs, YF_TOTAL_EQUITY_KEYS))
                if market_cap and eq and eq > 0:
                    pb = market_cap / eq
                    if pb > 0:
                        s = _normalize(pb, 0.0, pddd_high, reverse=True)
                        if s is not None:
                            scored.append((s, 0.70))
                            pb_added = True
                if not pb_added:
                    miss += 1

            # ── P/E (30%) — sadece 0 < P/E < 30 ─────────────────────────────
            pe_added    = False
            trailing_pe = info.get("trailingPE") if isinstance(info, dict) else None
            if (trailing_pe and np.isfinite(trailing_pe) and 0 < trailing_pe < 30):
                s = _normalize(trailing_pe, 0.0, fk_high, reverse=True)
                if s is not None:
                    scored.append((s, 0.30))
                    pe_added = True

            if not pe_added:
                if trailing_pe and np.isfinite(trailing_pe) and trailing_pe > 0:
                    flags.append(
                        "GYO: P/E metriği güvenilir bulunmadığı için valuation "
                        "P/B ağırlıklı hesaplandı."
                    )
                miss += 1

            if not scored:
                return None, "missing", 0.0
            mq = round(len(scored) / 2, 2)
            tw = sum(w for _, w in scored)
            return round(sum(s * w for s, w in scored) / tw, 2), None, mq

        except Exception as e:
            logger.warning(f"[fundamental/gyo] valuation: {e}")
            return None, "missing", 0.0

    def _gyo_stability(
        self,
        data:  dict,
        flags: List[str],
    ) -> Tuple[Optional[float], Optional[str], float]:
        """Equity CV (60%) + NI pozitif oran (40%).

        Equity CV: özkaynak istikrarı — GYO'da NI'dan daha güvenilir gösterge.
        NI CV kullanılmaz (yeniden değerleme kaynaklı gürültü).
        """
        try:
            df    = data["is_"]
            bs    = data["bs"]
            isyat = data.get("isyat", False)
            yf    = data.get("yf", False)

            scored: List[Tuple[float, float]] = []
            miss = 0

            # ── Equity CV ─────────────────────────────────────────────────────
            eq_vals: List[float] = []
            if isyat or not yf:
                for i in range(min(8, bs.shape[1])):
                    v = _get_row_period(bs, _EQUITY_KEYS, i)
                    if v is not None:
                        eq_vals.append(v)
            else:
                for key in YF_TOTAL_EQUITY_KEYS:
                    if key in bs.index:
                        eq_vals = [float(v) for v in bs.loc[key] if pd.notna(v)]
                        break

            if len(eq_vals) >= 2:
                mean_abs = abs(float(np.mean(eq_vals)))
                if mean_abs > 0:
                    cv = float(np.std(eq_vals)) / mean_abs
                    # CV eşiği: enflasyon ortamında özkaynak büyür → 1.5 geniş bant
                    s = _normalize(cv, 0.0, 1.5, reverse=True)
                    if s is not None: scored.append((s, 0.60))
                    else:             miss += 1
                else:
                    miss += 1
            else:
                miss += 1

            # ── NI pozitif oran ───────────────────────────────────────────────
            ni_vals: List[float] = []
            if isyat:
                for i in range(min(8, df.shape[1])):
                    v = _get_row_period(df, _NET_PROFIT_KEYS, i)
                    if v is not None:
                        ni_vals.append(v)
            elif yf:
                for key in YF_NET_INCOME_KEYS:
                    if key in df.index:
                        ni_vals = [float(v) for v in df.loc[key] if pd.notna(v)]
                        break
            else:
                for i in range(min(6, df.shape[1])):
                    v = _get_row_period(df, _NET_PROFIT_KEYS, i)
                    if v is not None:
                        ni_vals.append(v)

            if ni_vals:
                pos_ratio = sum(1 for v in ni_vals if v > 0) / len(ni_vals)
                scored.append((pos_ratio * 10.0, 0.40))
            else:
                miss += 1

            if not scored:
                return None, "missing", 0.0
            mq = round(len(scored) / 2, 2)
            tw = sum(w for _, w in scored)
            return round(sum(s * w for s, w in scored) / tw, 2), None, mq

        except Exception as e:
            logger.warning(f"[fundamental/gyo] stability: {e}")
            return None, "missing", 0.0

    def _gyo_explain(
        self,
        subscores: FundamentalSubscores,
    ) -> str:
        """GYO açıklama metni. Yatırım tavsiyesi içermez."""
        parts: List[str] = []

        if subscores.profitability is not None:
            if subscores.profitability >= 7.0:
                parts.append(
                    "Karlılık göstergeleri (ROE/ROA) sektör eşiklerine göre "
                    "destekleyici seyretmektedir."
                )
            elif subscores.profitability >= 4.0:
                parts.append(
                    "Karlılık göstergeleri (ROE/ROA) sektör eşiklerine yakın "
                    "seyretmektedir."
                )
            else:
                parts.append(
                    "Karlılık göstergeleri (ROE/ROA) sektör eşiklerine göre "
                    "sınırlayıcı etki oluşturmaktadır."
                )

        if subscores.balance_sheet is not None:
            if subscores.balance_sheet >= 7.0:
                parts.append(
                    "Özkaynak yapısı ve borçluluk düzeyi güçlü "
                    "seyretmektedir."
                )
            elif subscores.balance_sheet >= 4.0:
                parts.append(
                    "Özkaynak yapısı ve borçluluk düzeyi orta düzeyde "
                    "seyretmektedir."
                )
            else:
                parts.append(
                    "Özkaynak yapısı veya borçluluk düzeyi sınırlayıcı etki "
                    "oluşturmaktadır."
                )

        if subscores.growth is not None:
            if subscores.growth >= 7.0:
                parts.append(
                    "Büyüme göstergeleri (özkaynak/net kâr) güçlü "
                    "seyretmektedir."
                )
            elif subscores.growth >= 4.0:
                parts.append("Büyüme göstergeleri orta düzeyde seyretmektedir.")
            else:
                parts.append("Büyüme göstergeleri sınırlı seyretmektedir.")

        if subscores.valuation is not None:
            if subscores.valuation >= 7.0:
                parts.append(
                    "Değerleme çarpanları (P/B) sektör eşiklerine göre "
                    "destekleyici düzeydedir."
                )
            elif subscores.valuation >= 4.0:
                parts.append(
                    "Değerleme çarpanları (P/B) sektör eşiklerine yakın "
                    "seyretmektedir."
                )
            else:
                parts.append(
                    "Değerleme çarpanları (P/B) sektör eşiklerine göre "
                    "sınırlayıcı etki oluşturmaktadır."
                )

        if subscores.stability is not None:
            if subscores.stability >= 7.0:
                parts.append(
                    "Özkaynak istikrarı ve net kâr sürekliliği güçlü "
                    "seyretmektedir."
                )
            elif subscores.stability >= 4.0:
                parts.append(
                    "Özkaynak istikrarı ve net kâr sürekliliği orta düzeyde "
                    "seyretmektedir."
                )
            else:
                parts.append(
                    "Özkaynak istikrarı veya net kâr sürekliliği sınırlı "
                    "seyretmektedir."
                )

        if not parts:
            return "Finansal tablo verisiyle değerlendirme yapıldı."
        return " ".join(parts)

    # ── Boş sonuç ──────────────────────────────────────────────────────────

    def _empty_result(
        self,
        ticker:       str,
        sector_group: str,
        flags:        List[str],
        reason:       str = "",
    ) -> FundamentalResult:
        if reason:
            flags.append(f"Finansal veri alınamadı: {reason}.")
        return FundamentalResult(
            ticker=ticker,
            financial_score=None,
            financial_score_label="Veri Yetersiz",
            financial_score_quality=0.0,
            subscores=FundamentalSubscores(),
            piotroski=None,
            financial_flags=flags,
            explanation="Finansal tablo verisi alınamadı.",
            sector_group=sector_group,
            data_source="none",
            period=None,
        )


# ── Yardımcı ─────────────────────────────────────────────────────────────────

def _r2(v: Optional[float]) -> Optional[float]:
    return round(v, 2) if v is not None else None
