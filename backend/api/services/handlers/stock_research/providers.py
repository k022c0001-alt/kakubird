import json
import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart"
EDINET_DOCUMENTS_URL = "https://api.edinet-fsa.go.jp/api/v2/documents.json"
EDINET_PORTAL_URL = "https://disclosure.edinet-fsa.go.jp/"


class PriceProvider(Protocol):
    def fetch_history(self, symbol: str) -> Dict[str, Any]: ...


class ReportProvider(Protocol):
    def fetch_reports(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]: ...


class YahooFinancePriceProvider:
    """Fetch daily closes from Yahoo Finance's unauthenticated chart endpoint."""

    def __init__(self, timeout: float = 10.0):
        self.timeout = timeout

    def fetch_history(self, symbol: str) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=100)
        params = urlencode(
            {
                "period1": int(start.timestamp()),
                "period2": int((now + timedelta(days=1)).timestamp()),
                "interval": "1d",
                "events": "history",
            }
        )
        source_url = f"{YAHOO_CHART_URL}/{symbol}?{params}"
        request = Request(
            source_url,
            headers={"User-Agent": "kakubird-stock-research/1.0"},
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            raise RuntimeError(
                f"Yahoo Finance price data could not be retrieved ({type(exc).__name__})."
            ) from exc

        chart = payload.get("chart", {})
        if chart.get("error"):
            error = chart["error"]
            raise RuntimeError(
                f"Yahoo Finance returned an error: {error.get('description', 'unknown error')}"
            )
        results = chart.get("result") or []
        if not results:
            raise RuntimeError("Yahoo Finance returned no price observations.")

        result = results[0]
        timestamps = result.get("timestamp") or []
        quotes = result.get("indicators", {}).get("quote") or [{}]
        closes = quotes[0].get("close") or []
        observations = []
        tokyo = ZoneInfo("Asia/Tokyo")
        for timestamp, close in zip(timestamps, closes):
            if close is None:
                continue
            observations.append(
                {
                    "date": datetime.fromtimestamp(
                        timestamp, timezone.utc
                    ).astimezone(tokyo).date().isoformat(),
                    "close": float(close),
                }
            )

        if len(observations) < 2:
            raise RuntimeError("Yahoo Finance returned fewer than two valid closes.")

        return {
            "symbol": symbol,
            "currency": result.get("meta", {}).get("currency"),
            "observations": observations,
            "as_of": observations[-1]["date"],
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "source": "Yahoo Finance chart data (unofficial, potentially delayed)",
            "source_url": source_url,
        }


class UnavailableReportProvider:
    def fetch_reports(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        return {
            symbol: {
                "status": "unavailable",
                "reason": (
                    "Official filing retrieval is not configured. Set EDINET_API_KEY "
                    "to enable EDINET filing metadata; extracted quarterly financial "
                    "facts and XBRL/report-content summaries are not supported."
                ),
                "source": "EDINET API (not configured)",
                "source_url": EDINET_PORTAL_URL,
                "reports": [],
            }
            for symbol in symbols
        }


class EdinetReportProvider:
    """Retrieve official EDINET filing metadata; it does not interpret XBRL contents."""

    def __init__(
        self,
        api_key: str,
        lookback_days: int = 30,
        timeout: float = 8.0,
    ):
        self.api_key = api_key
        self.lookback_days = max(1, min(90, lookback_days))
        self.timeout = timeout

    def fetch_reports(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        requested = set(symbols)
        matches: Dict[str, List[Dict[str, Any]]] = {
            symbol: [] for symbol in symbols
        }
        today = date.today()
        for day_offset in range(self.lookback_days):
            report_date = (today - timedelta(days=day_offset)).isoformat()
            params = urlencode(
                {
                    "date": report_date,
                    "type": 2,
                    "Subscription-Key": self.api_key,
                }
            )
            request = Request(
                f"{EDINET_DOCUMENTS_URL}?{params}",
                headers={"User-Agent": "kakubird-stock-research/1.0"},
            )
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
                raise RuntimeError(
                    "EDINET filing metadata could not be retrieved "
                    f"({type(exc).__name__})."
                ) from exc

            for document in payload.get("results", []):
                code = document.get("secCode") or document.get("securitiesCode") or ""
                symbol = next(
                    (
                        candidate
                        for candidate in requested
                        if code[:4] == candidate[:4]
                    ),
                    None,
                )
                description = document.get("docDescription") or ""
                if not symbol or not self._is_financial_report(description):
                    continue
                matches[symbol].append(
                    {
                        "document_id": document.get("docID"),
                        "title": description,
                        "filer": document.get("filerName"),
                        "submitted_at": document.get("submitDateTime"),
                        "period_start": document.get("periodStart"),
                        "period_end": document.get("periodEnd"),
                        "content_summary_status": "metadata_only",
                    }
                )

        result = {}
        for symbol, reports in matches.items():
            reports.sort(
                key=lambda item: item.get("submitted_at") or "", reverse=True
            )
            result[symbol] = {
                "status": "available" if reports else "unavailable",
                "reason": (
                    "Official filing metadata only. Filing contents/XBRL are not "
                    "parsed, so no statement about reported financial performance "
                    "is inferred."
                    if reports
                    else (
                        "No matching official financial filing was found within "
                        f"the {self.lookback_days}-day EDINET search window."
                    )
                ),
                "source": "EDINET API",
                "source_url": EDINET_DOCUMENTS_URL,
                "as_of": today.isoformat(),
                "lookback_days": self.lookback_days,
                "reports": reports,
            }
        return result

    @staticmethod
    def _is_financial_report(description: str) -> bool:
        return any(
            term in description
            for term in ("四半期報告書", "半期報告書", "有価証券報告書")
        )


def configured_report_provider() -> ReportProvider:
    api_key = os.getenv("EDINET_API_KEY", "").strip()
    if not api_key:
        return UnavailableReportProvider()
    try:
        lookback_days = int(os.getenv("STOCK_RESEARCH_EDINET_LOOKBACK_DAYS", "30"))
    except ValueError:
        lookback_days = 30
    return EdinetReportProvider(api_key, lookback_days=lookback_days)
