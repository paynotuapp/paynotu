import requests
from datetime import date, timedelta

_BASE = "https://www.kap.org.tr"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": f"{_BASE}/tr/bildirim-sorgu",
    "Accept": "application/json",
}


def get_member_oid(ticker: str) -> str:
    r = requests.get(
        f"{_BASE}/tr/api/member/filter/{ticker.upper()}",
        headers=_HEADERS,
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    if not data:
        raise ValueError(f"Ticker bulunamadi: {ticker}")
    return data[0]["mkkMemberOid"]


def get_disclosures_by_ticker(ticker: str, days: int = 30) -> list:
    oid = get_member_oid(ticker)
    today = date.today()
    body = {
        "fromDate": (today - timedelta(days=days)).isoformat(),
        "toDate": today.isoformat(),
        "mkkMemberOidList": [oid],
        "subjectList": [],
    }
    r = requests.post(
        f"{_BASE}/tr/api/disclosure/members/byCriteria",
        json=body,
        headers=_HEADERS,
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


def get_oda_count(ticker: str, days: int = 30) -> int:
    disclosures = get_disclosures_by_ticker(ticker, days)
    return sum(1 for d in disclosures if d.get("disclosureClass") == "ODA")


def get_all_disclosure_count(ticker: str, days: int = 30) -> dict:
    disclosures = get_disclosures_by_ticker(ticker, days)
    oda = sum(1 for d in disclosures if d.get("disclosureClass") == "ODA")
    fr = sum(1 for d in disclosures if d.get("disclosureClass") == "FR")
    return {
        "toplam": len(disclosures),
        "oda": oda,
        "fr": fr,
        "diger": len(disclosures) - oda - fr,
    }
