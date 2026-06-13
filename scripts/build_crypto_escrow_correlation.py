#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from statistics import mean, pstdev
import sys
from urllib.parse import urlencode
from urllib.request import Request, urlopen


PRODUCTS = {
    "BTC": "BTC-USD",
    "ETH": "ETH-USD",
    "SOL": "SOL-USD",
}
ASSET_STARTS = {
    "BTC": date(2015, 1, 1),
    "ETH": date(2016, 1, 1),
    "SOL": date(2020, 3, 16),
}
TRANSFER_TERMS = ("DEED", "RECONVEYANCE", "ASSIGNMENT", "ASGT", "SUBSTITUTION", "TRUST", "TRANSFER")


def main() -> int:
    parser = argparse.ArgumentParser(description="Correlate high-risk property transfer dates with crypto market-activity windows.")
    parser.add_argument("--risk-scores", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--slug", default="crypto_escrow_correlation")
    parser.add_argument("--min-score", type=float, default=80.0)
    parser.add_argument("--window-days", type=int, default=45)
    parser.add_argument("--include-non-transfer", action="store_true", help="Include non-transfer-like rows instead of transfer-like records only.")
    args = parser.parse_args()

    events = _load_events(Path(args.risk_scores), args.min_score, transfer_like_only=not args.include_non_transfer)
    modern_events = [event for event in events if event["recording_date"] >= min(ASSET_STARTS.values())]
    unique_dates = sorted({event["recording_date"] for event in modern_events})
    if not unique_dates:
        raise SystemExit("No SOL-era high-score transfer dates found.")

    start = min(unique_dates) - timedelta(days=args.window_days)
    end = max(unique_dates) + timedelta(days=args.window_days)
    candles = {
        asset: _fetch_coinbase_candles(product, max(start, ASSET_STARTS[asset]), end)
        for asset, product in PRODUCTS.items()
        if end >= ASSET_STARTS[asset]
    }

    rows = []
    for event_date in unique_dates:
        documents = [event for event in modern_events if event["recording_date"] == event_date]
        for asset, asset_candles in candles.items():
            if event_date < ASSET_STARTS[asset]:
                continue
            metrics = _window_metrics(asset_candles, event_date, args.window_days)
            rows.append(
                {
                    "event_date": event_date.isoformat(),
                    "asset": asset,
                    "documents_on_date": len(documents),
                    "document_numbers": "|".join(sorted({event["document_number"] for event in documents})),
                    "document_types": "|".join(sorted({event["document_type"] for event in documents})),
                    "party_terms": " | ".join(sorted({event["parties"] for event in documents}))[:500],
                    **metrics,
                    "interpretation": _interpret(metrics),
                }
            )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = out_dir / f"{args.slug}_{stamp}"
    csv_path = Path(f"{base}.csv")
    json_path = Path(f"{base}.summary.json")
    md_path = Path(f"{base}.md")

    _write_csv(csv_path, rows)
    summary = {
        "generated_utc": stamp,
        "risk_scores": str(Path(args.risk_scores)),
        "min_score": args.min_score,
        "transfer_like_only": not args.include_non_transfer,
        "window_days": args.window_days,
        "events_considered": len(modern_events),
        "unique_event_dates": [d.isoformat() for d in unique_dates],
        "assets": PRODUCTS,
        "source": "Coinbase Exchange public product candles",
        "source_url": "https://api.exchange.coinbase.com/products/{product_id}/candles",
        "boundary": "Market-activity correlation only. No wallet addresses or transaction hashes were identified in local evidence.",
    }
    json_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(_render_report(summary, rows), encoding="utf-8")
    print(json.dumps({"csv": str(csv_path), "summary": str(json_path), "report": str(md_path)}, indent=2))
    return 0


def _load_events(path: Path, min_score: float, transfer_like_only: bool) -> list[dict[str, object]]:
    events = []
    seen: set[tuple[str, date]] = set()
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            try:
                score = float(row.get("score", "0"))
            except ValueError:
                continue
            if score < min_score:
                continue
            if transfer_like_only and not any(term in row.get("document_type", "").upper() for term in TRANSFER_TERMS):
                continue
            parsed_date = _parse_date(row.get("recording_date", ""))
            if not parsed_date:
                continue
            key = (row.get("document_number", ""), parsed_date)
            if key in seen:
                continue
            seen.add(key)
            events.append(
                {
                    "recording_date": parsed_date,
                    "document_number": row.get("document_number", ""),
                    "document_type": row.get("document_type", ""),
                    "parties": row.get("parties", ""),
                    "score": score,
                }
            )
    return events


def _fetch_coinbase_candles(product: str, start: date, end: date) -> list[dict[str, float | date]]:
    candles: dict[date, dict[str, float | date]] = {}
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=250), end)
        for row in _fetch_coinbase_candle_chunk(product, cursor, chunk_end):
            candles[row["date"]] = row
        cursor = chunk_end + timedelta(days=1)
    return sorted(candles.values(), key=lambda row: row["date"])


def _fetch_coinbase_candle_chunk(product: str, start: date, end: date) -> list[dict[str, float | date]]:
    params = urlencode(
        {
            "start": f"{start.isoformat()}T00:00:00Z",
            "end": f"{end.isoformat()}T00:00:00Z",
            "granularity": "86400",
        }
    )
    url = f"https://api.exchange.coinbase.com/products/{product}/candles?{params}"
    request = Request(url, headers={"User-Agent": "assessor-fraud-risk-triage/0.1"})
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, list):
        raise RuntimeError(f"Coinbase returned non-list payload for {product}: {payload}")
    candles = []
    for item in payload:
        ts, low, high, open_, close, volume = item
        candles.append(
            {
                "date": datetime.fromtimestamp(int(ts), tz=timezone.utc).date(),
                "low": float(low),
                "high": float(high),
                "open": float(open_),
                "close": float(close),
                "volume": float(volume),
            }
        )
    return sorted(candles, key=lambda row: row["date"])


def _window_metrics(candles: list[dict[str, float | date]], event_date: date, window_days: int) -> dict[str, object]:
    by_date = {row["date"]: row for row in candles}
    volumes = [float(row["volume"]) for row in candles]
    event = by_date.get(event_date)
    if not event:
        return {
            "event_close_usd": "",
            "event_exchange_volume_units": "",
            "event_volume_percentile_in_pull_range": "",
            "event_volume_zscore_in_pull_range": "",
            "window_avg_exchange_volume_units": "",
            "plus_minus_window_days": window_days,
            "window_price_change_pct": "",
            "interpretation": "no_market_data_for_event_date",
        }
    window = [
        row
        for row in candles
        if event_date - timedelta(days=window_days) <= row["date"] <= event_date + timedelta(days=window_days)
    ]
    pre = by_date.get(event_date - timedelta(days=window_days))
    post = by_date.get(event_date + timedelta(days=window_days))
    volume_mean = mean(volumes) if volumes else 0.0
    volume_std = pstdev(volumes) if len(volumes) > 1 else 0.0
    event_volume = float(event["volume"]) if event else 0.0
    event_close = float(event["close"]) if event else 0.0
    percentile = sum(1 for value in volumes if value <= event_volume) / len(volumes) if volumes else 0.0
    zscore = (event_volume - volume_mean) / volume_std if volume_std else 0.0
    window_avg = mean(float(row["volume"]) for row in window) if window else 0.0
    price_change = None
    if pre and post:
        start_close = float(pre["close"])
        end_close = float(post["close"])
        price_change = ((end_close - start_close) / start_close) * 100 if start_close else None
    return {
        "event_close_usd": round(event_close, 4),
        "event_exchange_volume_units": round(event_volume, 6),
        "event_volume_percentile_in_pull_range": round(percentile, 4),
        "event_volume_zscore_in_pull_range": round(zscore, 4),
        "window_avg_exchange_volume_units": round(window_avg, 6),
        "plus_minus_window_days": window_days,
        "window_price_change_pct": round(price_change, 4) if price_change is not None else "",
    }


def _interpret(metrics: dict[str, object]) -> str:
    if metrics.get("interpretation") == "no_market_data_for_event_date":
        return "no_market_data_for_event_date"
    percentile = float(metrics["event_volume_percentile_in_pull_range"])
    zscore = float(metrics["event_volume_zscore_in_pull_range"])
    if percentile >= 0.9 or zscore >= 1.5:
        return "elevated_market_activity_on_recording_date"
    if percentile <= 0.1 or zscore <= -1.5:
        return "suppressed_market_activity_on_recording_date"
    return "ordinary_market_activity_on_recording_date"


def _render_report(summary: dict[str, object], rows: list[dict[str, object]]) -> str:
    counts = Counter(row["interpretation"] for row in rows)
    by_date = defaultdict(list)
    for row in rows:
        by_date[row["event_date"]].append(row)
    lines = [
        "# Crypto Escrow-Window Correlation Report",
        "",
        f"Generated UTC: `{summary['generated_utc']}`",
        "",
        "## Boundary",
        "",
        "This report checks whether high-review property transfer dates coincide with BTC, ETH, and SOL market-activity windows. It does not identify blockchain transactions tied to any person because no wallet addresses or transaction hashes were identified in the local evidence search.",
        "",
        "Coinbase public daily candles are used as a market-activity proxy. This is not the same as wallet-level on-chain transaction attribution.",
        "",
        "## Scope",
        "",
        f"- Risk-score source: `{summary['risk_scores']}`",
        f"- Minimum property score: `{summary['min_score']}`",
        f"- Escrow window: `+/- {summary['window_days']} days`",
        f"- Events considered: `{summary['events_considered']}`",
        f"- Unique event dates: `{', '.join(summary['unique_event_dates'])}`",
        "",
        "## Interpretation Counts",
        "",
    ]
    for label, count in counts.most_common():
        lines.append(f"- `{label}`: {count}")
    lines.extend(["", "## Date Findings", ""])
    lines.append("| Event Date | Asset | Docs | Event Close USD | Event Volume | Volume Percentile | Volume Z | Window Price Change | Interpretation |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---|")
    for event_date in sorted(by_date):
        for row in sorted(by_date[event_date], key=lambda item: item["asset"]):
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(row["event_date"]),
                        str(row["asset"]),
                        str(row["documents_on_date"]),
                        str(row["event_close_usd"]),
                        str(row["event_exchange_volume_units"]),
                        str(row["event_volume_percentile_in_pull_range"]),
                        str(row["event_volume_zscore_in_pull_range"]),
                        str(row["window_price_change_pct"]),
                        str(row["interpretation"]),
                    ]
                )
                + " |"
            )
    lines.extend(
        [
            "",
            "## Next Evidence Needed",
            "",
            "- Wallet addresses, transaction hashes, exchange account records, subpoena returns, or bank/exchange transfer records are required for transaction-level attribution.",
            "- If wallet addresses are found later, run address-specific explorer queries by chain and compare transaction timestamps to the escrow windows in this report.",
            "- For real estate use, compare any crypto liquidation/on-ramp/off-ramp dates to escrow deposit, payoff, reconveyance, substitution, and assignment dates.",
        ]
    )
    return "\n".join(lines) + "\n"


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _parse_date(value: str) -> date | None:
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    return None


if __name__ == "__main__":
    raise SystemExit(main())
