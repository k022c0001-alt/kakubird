# Stock research

The stock research handler is available through the existing chat interface.
Ask about Japanese-listed shares using four-digit TSE codes, for example:

> `7203と6758の株価トレンドと決算資料を調査`

The handler examines only codes in the message or the comma-separated
`STOCK_RESEARCH_UNIVERSE` environment variable. It does not claim coverage of
all Japanese listings and rejects more than 12 symbols in one request. If both
an explicit list and a configured universe exist, the explicit list takes
precedence.

## Data sources and limits

- Daily closing prices are fetched from Yahoo Finance's public chart endpoint
  for an approximate 100-calendar-day window. This endpoint is unofficial,
  may be delayed, and may become unavailable or change. Each result includes
  its retrieval timestamp, last observed trading date, and source URL.
- Alternating price movements count direction changes between successive
  non-flat daily close-to-close moves. A repeated alternation means at least
  two such changes; it is not a prediction or investment recommendation.
- Quarterly business-performance comparisons are explicitly unavailable:
  the current implementation does not parse company financial statements or
  infer financial results from share prices. A three-month price window is not
  equivalent to the issuer's fiscal quarter; Japanese issuers also differ in
  quarterly/semiannual disclosure cadence.
- Official EDINET filing metadata can optionally be retrieved when
  `EDINET_API_KEY` is configured. The API key must be treated as a secret and
  must not be placed in the frontend. `STOCK_RESEARCH_EDINET_LOOKBACK_DAYS`
  controls the search window (1–90 days; default 30). Filing titles and
  submission/period dates are metadata only: the current provider does not
  download or interpret XBRL/PDF filing contents, so it does not summarize
  reported financial performance. Without an EDINET key, this capability
  returns an explicit unavailable state.

Provider boundaries are in
`backend/api/services/handlers/stock_research/providers.py`; price calculations
are isolated in `analysis.py`. The output includes structured per-symbol
availability and provenance fields so missing or unsupported information
cannot be mistaken for a successful financial analysis.
