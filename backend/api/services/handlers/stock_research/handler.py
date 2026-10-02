import asyncio
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from ..base_handler import BaseHandler
from .analysis import analyze_price_history
from .providers import (
    PriceProvider,
    ReportProvider,
    YahooFinancePriceProvider,
    configured_report_provider,
)


_SYMBOL_PATTERN = re.compile(r"(?<!\d)(\d{4})(?:\.T)?(?!\d)", re.IGNORECASE)
_RESEARCH_TERMS = (
    "株",
    "銘柄",
    "株価",
    "株式",
    "stock",
    "stocks",
    "equity",
)
_RESEARCH_INTENTS = (
    "調査",
    "分析",
    "スクリーニング",
    "値動き",
    "上げ下げ",
    "業績",
    "決算",
    "レポート",
    "report",
    "screen",
    "research",
    "trend",
    "performance",
)
_MAX_UNIVERSE_SIZE = 12


class StockResearchHandler(BaseHandler):
    """Analyze an explicit set of Japanese tickers using source-attributed data."""

    def __init__(
        self,
        price_provider: Optional[PriceProvider] = None,
        report_provider: Optional[ReportProvider] = None,
    ):
        self.price_provider = price_provider or YahooFinancePriceProvider()
        self.report_provider = report_provider or configured_report_provider()

    async def can_handle(self, message: str) -> bool:
        normalized = (message or "").lower()
        has_symbol = bool(_SYMBOL_PATTERN.search(normalized))
        has_research_terms = any(term in normalized for term in _RESEARCH_TERMS)
        has_intent = any(term in normalized for term in _RESEARCH_INTENTS)
        return (has_symbol and (has_research_terms or has_intent)) or (
            has_research_terms and has_intent
        )

    async def calculate_score(
        self, message: str, current_signals: Optional[dict] = None
    ) -> int:
        return 100 if await self.can_handle(message) else 0

    async def handle(self, request: Any) -> Tuple[str, Dict[str, Any]]:
        message = (
            getattr(request, "message", "")
            if not isinstance(request, str)
            else request
        )
        message = message or ""
        explicit_symbols = self._extract_symbols(message)
        symbols = explicit_symbols or self._configured_universe()
        if not symbols:
            return "text", self._universe_required_response()
        if len(symbols) > _MAX_UNIVERSE_SIZE:
            return "text", {
                "message": (
                    f"一度に調査できる銘柄は最大{_MAX_UNIVERSE_SIZE}件です。"
                    "銘柄コードを絞るか、STOCK_RESEARCH_UNIVERSEを調整してください。"
                ),
                "blocks": [],
                "stock_research": {
                    "status": "invalid_universe",
                    "requested_count": len(symbols),
                    "maximum_count": _MAX_UNIVERSE_SIZE,
                },
            }

        price_results = await asyncio.gather(
            *(self._fetch_price(symbol) for symbol in symbols)
        )
        try:
            reports = await asyncio.to_thread(
                self.report_provider.fetch_reports, symbols
            )
        except Exception as exc:
            reports = {
                symbol: {
                    "status": "unavailable",
                    "reason": (
                        "Official report retrieval failed "
                        f"({type(exc).__name__}); no financial facts were inferred."
                    ),
                    "source": "EDINET API",
                    "source_url": "https://disclosure.edinet-fsa.go.jp/",
                    "reports": [],
                }
                for symbol in symbols
            }

        stocks = []
        for symbol, price in zip(symbols, price_results):
            report = reports.get(
                symbol,
                {
                    "status": "unavailable",
                    "reason": "The report provider returned no result for this symbol.",
                    "reports": [],
                },
            )
            stocks.append(
                {
                    "symbol": symbol,
                    "price": price,
                    "business_performance": {
                        "status": "unavailable",
                        "reason": (
                            "Quarterly financial facts are not extracted from the "
                            "official filings provider. This feature does not infer "
                            "business performance from price movements."
                        ),
                        "comparison_period": "latest reported quarter vs prior quarter",
                        "cadence_note": (
                            "A three-month market-price window is not the same as a "
                            "company reporting quarter. Japanese issuers publish "
                            "quarterly or semiannual filings on different schedules."
                        ),
                    },
                    "official_reports": report,
                }
            )

        result = {
            "status": "partial" if any(
                stock["price"]["status"] == "unavailable"
                or stock["business_performance"]["status"] == "unavailable"
                or stock["official_reports"]["status"] != "available"
                for stock in stocks
            ) else "complete",
            "universe": {
                "source": "explicit message symbols" if explicit_symbols else "STOCK_RESEARCH_UNIVERSE",
                "symbols": symbols,
                "coverage": "configured/explicit universe only; not all Japanese listings",
            },
            "price_window": "approximately 3 months",
            "stocks": stocks,
            "disclosures": [
                "Yahoo Finance chart data is an unofficial, potentially delayed source.",
                "Unavailable values are left unavailable; no prices or financial facts are fabricated.",
                "Official filing metadata is not a summary of the filing contents.",
            ],
        }
        return "ui_code", {
            "message": self._format_summary(result),
            "blocks": [
                {
                    "type": "StockResearchBlock",
                    "props": {"data": result},
                }
            ],
            "stock_research": result,
        }

    async def _fetch_price(self, symbol: str) -> Dict[str, Any]:
        try:
            raw = await asyncio.to_thread(
                self.price_provider.fetch_history, f"{symbol}.T"
            )
            analysis = analyze_price_history(raw.get("observations", []))
            if analysis is None:
                raise RuntimeError("The source returned fewer than two valid closes.")
            return {
                "status": "available",
                **analysis,
                "currency": raw.get("currency"),
                "as_of": raw.get("as_of"),
                "retrieved_at": raw.get("retrieved_at"),
                "source": raw.get("source", "Yahoo Finance chart data"),
                "source_url": raw.get("source_url"),
            }
        except Exception as exc:
            return {
                "status": "unavailable",
                "reason": f"Price history unavailable ({type(exc).__name__}).",
                "source": "Yahoo Finance chart data",
                "source_url": (
                    "https://query1.finance.yahoo.com/v8/finance/chart/"
                    f"{symbol}.T"
                ),
            }

    @staticmethod
    def _extract_symbols(message: str) -> List[str]:
        return list(dict.fromkeys(_SYMBOL_PATTERN.findall(message or "")))

    @staticmethod
    def _configured_universe() -> List[str]:
        codes = re.findall(
            r"(?<!\d)(\d{4})(?:\.T)?(?!\d)",
            os.getenv("STOCK_RESEARCH_UNIVERSE", ""),
            re.IGNORECASE,
        )
        return list(dict.fromkeys(codes))

    @staticmethod
    def _universe_required_response() -> Dict[str, Any]:
        return {
            "message": (
                "調査対象の銘柄コードがありません。例:「7203と6758の株価トレンドと"
                "決算資料を調査」。または環境変数STOCK_RESEARCH_UNIVERSEに"
                "カンマ区切りの東証4桁コードを設定してください。"
                "全上場銘柄を網羅したスクリーニングではありません。"
            ),
            "blocks": [],
            "stock_research": {
                "status": "configuration_required",
                "required_configuration": "STOCK_RESEARCH_UNIVERSE or explicit 4-digit ticker codes",
            },
        }

    @staticmethod
    def _format_summary(result: Dict[str, Any]) -> str:
        lines = [
            "## 株式調査（明示・設定された銘柄のみ）",
            f"対象: {', '.join(result['universe']['symbols'])}",
            "株価期間: 約3か月。Yahoo Financeの非公式・遅延の可能性があるデータです。",
        ]
        for stock in result["stocks"]:
            symbol = stock["symbol"]
            price = stock["price"]
            if price["status"] == "available":
                lines.append(
                    f"- **{symbol}**: 期間騰落率 {price['change_percent']:+.2f}% "
                    f"({price['period_start']}〜{price['period_end']}, "
                    f"終値 {price['latest_close']:g} {price.get('currency') or ''}); "
                    f"上昇日 {price['up_moves']}・下落日 {price['down_moves']}・"
                    f"方向反転 {price['alternating_moves']}回"
                    f"{'（反復あり）' if price['repeated_alternation'] else ''}。"
                )
            else:
                lines.append(
                    f"- **{symbol}**: 株価データ取得不可 "
                    f"({price.get('reason', '理由不明')})。"
                )
            reports = stock["official_reports"]
            if reports["status"] == "available":
                report_titles = "、".join(
                    item["title"] for item in reports.get("reports", [])[:2]
                )
                lines.append(
                    f"  - 公式開示: {report_titles}。提出情報のみ取得し、"
                    "報告書本文・財務数値は解析していません。"
                )
            else:
                lines.append(
                    f"  - 公式開示: {reports.get('reason', '利用不可')}。"
                )
            lines.append(
                "  - 3か月の業績比較: 利用不可。四半期報告と3か月の株価期間は"
                "別物であり、価格変動から業績を推定していません。"
            )
        lines.extend(
            [
                "",
                "株価出典: Yahoo Finance chart API（各銘柄の構造化結果にURL・基準日を記載）。",
                "対象は指定銘柄のみで、日本の全上場銘柄を網羅するものではありません。",
            ]
        )
        return "\n".join(lines)
