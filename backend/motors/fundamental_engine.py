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
    "BANKACILIK":  "bank",
    "FINANSAL":    "bank",
    "KALKINMA":    "bank",
    "SIGORTA":     "insurance",
    "SIGORTACILIK": "insurance",
    "GYO":         "gyo",
    "GAYRIMENKUL": "gyo",
    "HOLDING":     "holding",
}

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

# ── borsapy satır adı alias listeleri ────────────────────────────────────────
_NET_PROFIT_KEYS = [
    "DÖNEM KARI (ZARARI)",
    "Ana Ortaklık Payları",
    "SÜRDÜRÜLENFAALİYETLER DÖNEM KARI/ZARARI",
    "Dönem Net Kar/Zararı",
]
_REVENUE_KEYS = [
    "Satış Gelirleri",
    "HASILAT",
    "NET SATIŞLAR",
]
_GROSS_PROFIT_KEYS = [
    "BRÜT KAR (ZARAR)",
    "BRÜT KAR",
]
_OPERATING_PROFIT_KEYS = [
    "FAALİYET KARI (ZARARI)",
    "ESAS FAALİYET KARI",
]
_TOTAL_ASSETS_KEYS = [
    "TOPLAM VARLIKLAR",
    "AKTİF TOPLAMI",
]
_EQUITY_KEYS = [
    "Ana Ortaklığa Ait Özkaynaklar",
    "Özkaynaklar",
    "XVI. ÖZKAYNAKLAR",
]
_CURRENT_ASSETS_KEYS = ["Dönen Varlıklar"]
_CURRENT_LIAB_KEYS   = ["Kısa Vadeli Yükümlülükler"]
_CASH_KEYS           = ["Nakit ve Nakit Benzerleri"]
_PAID_CAPITAL_KEYS   = ["Ödenmiş Sermaye", "16.1 Ödenmiş Sermaye"]
_FIN_EXPENSE_KEYS    = [
    "(Esas Faaliyet Dışı) Finansal Giderler (-)",
    "Finansman Giderleri",
    "Finansman Gideri",
]
_AMORTIZATION_KEYS = [
    "Amortisman & İtfa Payları",
    "Amortisman Giderleri",
]
_OPERATING_CF_KEYS = [
    "İşletme Faaliyetlerinden Kaynaklanan Net Nakit",
    "İşletme Faaliyetleri Net Nakit",
]
_FCF_KEYS = [
    "Serbest Nakit Akımı",
    "Serbest Nakit Akışı",
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


def _contains_forbidden(text: str, words: List[str] = _FORBIDDEN_WORDS) -> bool:
    for w in words:
        if re.search(rf"\b{re.escape(w)}\b", text.lower()):
            return True
    return False


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
        ticker:  str,
        sektor:  Optional[str] = None,
    ) -> FundamentalResult:
        sector_group = self._get_sector_group(sektor)
        flags: List[str] = []

        data = self._fetch_data(ticker, sector_group, flags)
        if data is None:
            return self._empty_result(ticker, sector_group, flags, "veri çekilemedi")

        # Alt skorlar + nedenleri (None=calculated, "not_applicable", "missing")
        prof_s,  prof_r  = self._compute_profitability(data, sector_group, flags)
        bs_s,    bs_r    = self._compute_balance_sheet(data, sector_group, flags)
        cf_s,    cf_r    = self._compute_cash_flow(data, sector_group, flags)
        grow_s,  grow_r  = self._compute_growth(data, flags)
        val_s,   val_r   = self._compute_valuation(data, sector_group, flags)
        stab_s,  stab_r  = self._compute_stability(data, flags)
        piotr    = self._compute_piotroski(data, sector_group, flags)

        piotr_s = piotr.normalized if piotr else None
        piotr_r = (
            "not_applicable" if (piotr is None and sector_group in ("bank", "insurance"))
            else ("missing"  if piotr is None else None)
        )

        reasons = {
            "profitability": (prof_s,  prof_r),
            "balance_sheet": (bs_s,    bs_r),
            "cash_flow":     (cf_s,    cf_r),
            "growth":        (grow_s,  grow_r),
            "valuation":     (val_s,   val_r),
            "stability":     (stab_s,  stab_r),
            "piotroski":     (piotr_s, piotr_r),
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

        explanation = self._explain(subscores, piotr, sector_group)
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
            sector_group=sector_group,
            data_source=data.get("data_source", "borsapy"),
            period=data.get("period"),
        )

    # ── Sektör grubu belirleme ──────────────────────────────────────────────

    def _get_sector_group(self, sektor: Optional[str]) -> str:
        if not sektor:
            return "unknown"
        s = _normalize_tr(sektor)
        for key, group in _SECTOR_MAP.items():
            if _normalize_tr(key) in s or s in _normalize_tr(key):
                return group
        return "industrial"

    # ── Veri çekme ─────────────────────────────────────────────────────────

    def _fetch_data(
        self,
        ticker:       str,
        sector_group: str,
        flags:        List[str],
    ) -> Optional[dict]:
        if sector_group == "bank":
            d = self._fetch_banking(ticker, flags)
            if d is not None:
                return d
        return self._fetch_standard(ticker, flags)

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
            return {
                "bs":          bs,
                "is_":         is_,
                "cf":          cf,
                "info":        info,
                "period":      str(bs.columns[0]),
                "data_source": "borsapy",
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
            for fg in ("UFRS_B", "UFRS", "TMS_17"):
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
            return {
                "bs":          bs,
                "is_":         is_,
                "cf":          None,   # bankalar için mevcut değil
                "info":        info,
                "period":      str(bs.columns[0]),
                "data_source": "borsapy_banking",
            }
        except Exception as e:
            logger.warning(f"[fundamental] {ticker} banking fetch: {e}")
            return None

    # ── Alt skor: Karlılık ──────────────────────────────────────────────────

    def _compute_profitability(
        self,
        data:         dict,
        sector_group: str,
        flags:        List[str],
    ) -> Tuple[Optional[float], Optional[str]]:
        try:
            if sector_group == "bank":
                return self._profitability_bank(data)
            return self._profitability_standard(data)
        except Exception as e:
            logger.warning(f"[fundamental] profitability: {e}")
            return None, "missing"

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
            return None, "missing"
        tw = sum(w for _, w in scored)
        return round(sum(s * w for s, w in scored) / tw, 2), None

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
            return None, "missing"
        tw = sum(w for _, w in scored)
        return round(sum(s * w for s, w in scored) / tw, 2), None

    # ── Alt skor: Bilanço Sağlığı ───────────────────────────────────────────

    def _compute_balance_sheet(
        self,
        data:         dict,
        sector_group: str,
        flags:        List[str],
    ) -> Tuple[Optional[float], Optional[str]]:
        if sector_group in ("bank", "insurance"):
            return None, "not_applicable"
        try:
            bs, is_, cf = data["bs"], data["is_"], data.get("cf")

            ozkayn   = _get_row(bs,  _EQUITY_KEYS)
            doenen   = _get_row(bs,  _CURRENT_ASSETS_KEYS)
            kv_liab  = _get_row(bs,  _CURRENT_LIAB_KEYS)
            nakit    = _get_row(bs,  _CASH_KEYS)
            faaliyet = _get_row(is_, _OPERATING_PROFIT_KEYS)
            fin_gid  = _get_row(is_, _FIN_EXPENSE_KEYS)
            fin_borc = _sum_key_latest(bs, "Finansal Borçlar")
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
                return None, "missing"
            tw = sum(w for _, w in scored)
            return round(sum(s * w for s, w in scored) / tw, 2), None

        except Exception as e:
            logger.warning(f"[fundamental] balance_sheet: {e}")
            return None, "missing"

    # ── Alt skor: Nakit Akışı ───────────────────────────────────────────────

    def _compute_cash_flow(
        self,
        data:         dict,
        sector_group: str,
        flags:        List[str],
    ) -> Tuple[Optional[float], Optional[str]]:
        if sector_group in ("bank", "insurance"):
            return None, "not_applicable"
        try:
            cf = data.get("cf")
            if cf is None:
                return None, "missing"

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
                return None, "missing"
            tw = sum(w for _, w in scored)
            return round(sum(s * w for s, w in scored) / tw, 2), None

        except Exception as e:
            logger.warning(f"[fundamental] cash_flow: {e}")
            return None, "missing"

    # ── Alt skor: Büyüme ────────────────────────────────────────────────────

    def _compute_growth(
        self,
        data:  dict,
        flags: List[str],
    ) -> Tuple[Optional[float], Optional[str]]:
        try:
            bs, is_ = data["bs"], data["is_"]
            n = min(bs.shape[1], is_.shape[1])
            if n < 2:
                return None, "missing"

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
                return None, "missing"
            tw = sum(w for _, w in scored)
            score = sum(s * w for s, w in scored) / tw
            score = min(score, 9.5)  # büyüme skoru tavanı
            return round(score, 2), None

        except Exception as e:
            logger.warning(f"[fundamental] growth: {e}")
            return None, "missing"

    # ── Alt skor: Değerleme ─────────────────────────────────────────────────

    def _compute_valuation(
        self,
        data:         dict,
        sector_group: str,
        flags:        List[str],
    ) -> Tuple[Optional[float], Optional[str]]:
        try:
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
                return None, "missing"
            tw = sum(w for _, w in scored)
            return round(sum(s * w for s, w in scored) / tw, 2), None

        except Exception as e:
            logger.warning(f"[fundamental] valuation: {e}")
            return None, "missing"

    # ── Alt skor: İstikrar ──────────────────────────────────────────────────

    def _compute_stability(
        self,
        data:  dict,
        flags: List[str],
    ) -> Tuple[Optional[float], Optional[str]]:
        try:
            bs, is_ = data["bs"], data["is_"]
            n = min(bs.shape[1], is_.shape[1])

            ozkayn_latest = _get_row(bs, _EQUITY_KEYS)
            if ozkayn_latest is not None and ozkayn_latest < 0:
                flags.append("Negatif özkaynak tespit edildi.")
                return 0.0, None

            net_karlar = [_get_row_period(is_, _NET_PROFIT_KEYS, i) for i in range(n)]
            valid      = [k for k in net_karlar if k is not None]
            if not valid:
                return None, "missing"

            scored: List[Tuple[float, float]] = []
            miss = 0

            # Zarar yılı oranı (0 zarar=10, tümü zarar=0)
            loss_ratio  = sum(1 for k in valid if k < 0) / len(valid)
            scored.append(((1.0 - loss_ratio) * 10.0, 0.50))

            # Kar oynaklığı (CV)
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
                return None, "missing"
            tw = sum(w for _, w in scored)
            return round(sum(s * w for s, w in scored) / tw, 2), None

        except Exception as e:
            logger.warning(f"[fundamental] stability: {e}")
            return None, "missing"

    # ── Alt skor: Piotroski ─────────────────────────────────────────────────

    def _compute_piotroski(
        self,
        data:         dict,
        sector_group: str,
        flags:        List[str],
    ) -> Optional[PiotroskiResult]:
        if sector_group in ("bank", "insurance"):
            return None   # not_applicable

        try:
            bs, is_, cf = data["bs"], data["is_"], data.get("cf")
            n_bs = bs.shape[1]
            n_is = is_.shape[1]

            details: Dict[str, Optional[int]] = {}
            p_score = 0
            calc    = 0

            def add(name: str, value: Optional[bool]) -> None:
                nonlocal p_score, calc
                if value is None:
                    details[name] = None
                    return
                v = 1 if value else 0
                details[name] = v
                p_score += v
                calc += 1

            # ── F1: Net kar pozitif? ──────────────────────────────────────
            nk0 = _get_row_period(is_, _NET_PROFIT_KEYS, 0)
            add("f1_net_kar_pozitif",
                (nk0 > 0) if nk0 is not None else None)

            # ── F2: İşletme CF pozitif? ───────────────────────────────────
            op_cf0 = _get_row(cf, _OPERATING_CF_KEYS) if cf is not None else None
            add("f2_opcf_pozitif",
                (op_cf0 > 0) if op_cf0 is not None else None)

            # ── F3: ROA iyileşti? ─────────────────────────────────────────
            if n_is >= 2 and n_bs >= 2:
                nk1  = _get_row_period(is_, _NET_PROFIT_KEYS, 1)
                tv0  = _get_row_period(bs, _TOTAL_ASSETS_KEYS, 0)
                tv1  = _get_row_period(bs, _TOTAL_ASSETS_KEYS, 1)
                roa0 = _safe_div(nk0, tv0)
                roa1 = _safe_div(nk1, tv1)
                add("f3_roa_iyilesti",
                    (roa0 > roa1) if (roa0 is not None and roa1 is not None) else None)
            else:
                add("f3_roa_iyilesti", None)

            # ── F4: CF > Net Kar? (tahakkuk kalitesi) ────────────────────
            add("f4_cf_gt_net",
                (op_cf0 > nk0) if (op_cf0 is not None and nk0 is not None) else None)

            # ── F5: Finansal borç oranı azaldı? ──────────────────────────
            if n_bs >= 2:
                fb0 = _sum_key_period(bs, "Finansal Borçlar", 0)
                fb1 = _sum_key_period(bs, "Finansal Borçlar", 1)
                tv0 = _get_row_period(bs, _TOTAL_ASSETS_KEYS, 0)
                tv1 = _get_row_period(bs, _TOTAL_ASSETS_KEYS, 1)
                r0  = _safe_div(fb0, tv0)
                r1  = _safe_div(fb1, tv1)
                add("f5_borc_azaldi",
                    (r0 < r1) if (r0 is not None and r1 is not None) else None)
            else:
                add("f5_borc_azaldi", None)

            # ── F6: Cari oran iyileşti? ───────────────────────────────────
            if n_bs >= 2:
                dv0 = _get_row_period(bs, _CURRENT_ASSETS_KEYS, 0)
                kl0 = _get_row_period(bs, _CURRENT_LIAB_KEYS, 0)
                dv1 = _get_row_period(bs, _CURRENT_ASSETS_KEYS, 1)
                kl1 = _get_row_period(bs, _CURRENT_LIAB_KEYS, 1)
                cr0 = _safe_div(dv0, kl0)
                cr1 = _safe_div(dv1, kl1)
                add("f6_cari_oran_iyilesti",
                    (cr0 > cr1) if (cr0 is not None and cr1 is not None) else None)
            else:
                add("f6_cari_oran_iyilesti", None)

            # ── F7: Yeni hisse basılmadı? ─────────────────────────────────
            if n_bs >= 2:
                os0 = _get_row_period(bs, _PAID_CAPITAL_KEYS, 0)
                os1 = _get_row_period(bs, _PAID_CAPITAL_KEYS, 1)
                add("f7_yeni_hisse_yok",
                    (os0 <= os1 * 1.01) if (os0 is not None and os1 is not None) else None)
            else:
                add("f7_yeni_hisse_yok", None)

            # ── F8: Brüt kar marjı iyileşti? ─────────────────────────────
            if n_is >= 2:
                bk0 = _get_row_period(is_, _GROSS_PROFIT_KEYS, 0)
                sa0 = _get_row_period(is_, _REVENUE_KEYS, 0)
                bk1 = _get_row_period(is_, _GROSS_PROFIT_KEYS, 1)
                sa1 = _get_row_period(is_, _REVENUE_KEYS, 1)
                bm0 = _safe_div(bk0, sa0)
                bm1 = _safe_div(bk1, sa1)
                add("f8_brut_marj_iyilesti",
                    (bm0 > bm1) if (bm0 is not None and bm1 is not None) else None)
            else:
                add("f8_brut_marj_iyilesti", None)

            # ── F9: Aktif devir hızı iyileşti? ───────────────────────────
            if n_is >= 2 and n_bs >= 2:
                sa0 = _get_row_period(is_, _REVENUE_KEYS, 0)
                sa1 = _get_row_period(is_, _REVENUE_KEYS, 1)
                tv0 = _get_row_period(bs, _TOTAL_ASSETS_KEYS, 0)
                tv1 = _get_row_period(bs, _TOTAL_ASSETS_KEYS, 1)
                at0 = _safe_div(sa0, tv0)
                at1 = _safe_div(sa1, tv1)
                add("f9_aktif_devir_iyilesti",
                    (at0 > at1) if (at0 is not None and at1 is not None) else None)
            else:
                add("f9_aktif_devir_iyilesti", None)

            # ── Normalize ─────────────────────────────────────────────────
            if calc < 5:
                normalized = None
                flags.append(
                    f"Piotroski skoru hesaplanamadı: yeterli kriter yok "
                    f"({calc}/9)."
                )
            else:
                normalized = round(p_score / calc * 10, 2)
                flags.append(
                    f"Piotroski {p_score}/9 kriterin {calc} tanesi "
                    f"hesaplanarak üretildi."
                )

            return PiotroskiResult(
                score=p_score,
                normalized=normalized,
                calculated_criteria=calc,
                total_criteria=9,
                details=details,
            )

        except Exception as e:
            logger.warning(f"[fundamental] piotroski: {e}")
            return None

    # ── Ağırlıklı ortalama + kalite ────────────────────────────────────────

    def _weighted_average(
        self,
        reasons: Dict[str, Tuple[Optional[float], Optional[str]]],
        weights: Dict[str, float],
    ) -> Tuple[Optional[float], float]:
        """
        Returns (weighted_score, quality).

        quality = calculated_weight / (calculated_weight + missing_weight)
        not_applicable → ağırlıktan çıkar, kaliteyi etkilemez.
        missing        → kaliteyi düşürür.
        """
        wsum  = 0.0
        wapp  = 0.0   # applicable ağırlık
        wcalc = 0.0   # hesaplanan ağırlık
        wmiss = 0.0   # eksik ağırlık

        for key, w in weights.items():
            score, reason = reasons.get(key, (None, "missing"))
            if reason == "not_applicable":
                continue
            wapp += w
            if score is not None and reason is None:
                wcalc += w
                wsum  += score * w
            else:
                wmiss += w

        denom   = wcalc + wmiss
        quality = round(wcalc / denom, 2) if denom > 0 else 0.0
        if wapp == 0 or wcalc == 0:
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
