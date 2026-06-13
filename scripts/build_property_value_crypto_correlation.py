#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path


DTT_RATE_PER_1000 = 1.10


def main() -> int:
    parser = argparse.ArgumentParser(description="Join transfer-value metadata to crypto escrow-window correlation rows.")
    parser.add_argument("--crypto-csv", required=True)
    parser.add_argument("--detail-csv", action="append", default=[])
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--slug", default="property_value_crypto_correlation")
    args = parser.parse_args()

    detail_by_doc = {}
    for path in args.detail_csv:
        detail_by_doc.update(_load_detail_rows(Path(path)))

    rows = []
    with Path(args.crypto_csv).open(newline="", encoding="utf-8-sig") as handle:
        for crypto_row in csv.DictReader(handle):
            docs = [doc for doc in crypto_row["document_numbers"].split("|") if doc]
            for doc in docs:
                detail = detail_by_doc.get(doc, {})
                value = _value_from_detail(detail)
                notional = _crypto_notional_usd(crypto_row)
                rows.append(
                    {
                        "event_date": crypto_row["event_date"],
                        "asset": crypto_row["asset"],
                        "document_number": doc,
                        "document_type_cluster": crypto_row["document_types"],
                        "parties_cluster": crypto_row["party_terms"],
                        "crypto_interpretation": crypto_row["interpretation"],
                        "crypto_event_close_usd": crypto_row["event_close_usd"],
                        "crypto_event_volume_units": crypto_row["event_exchange_volume_units"],
                        "crypto_daily_notional_usd_est": _round_money(notional),
                        "crypto_volume_percentile": crypto_row["event_volume_percentile_in_pull_range"],
                        "crypto_volume_zscore": crypto_row["event_volume_zscore_in_pull_range"],
                        "transfer_tax_amount": value["transfer_tax_amount"],
                        "estimated_net_consideration_from_transfer_tax": value["estimated_net_consideration"],
                        "value_basis": value["basis"],
                        "value_to_crypto_daily_notional_ratio": _ratio(value["estimated_net_consideration"], notional),
                        "city": detail.get("city_detail", ""),
                        "tract_no": detail.get("tract_no", ""),
                        "lot_no": detail.get("lot_no", ""),
                        "canonical_apn": detail.get("canonical_apn", ""),
                        "normalized_apn": detail.get("normalized_apn", ""),
                        "matched_site_address": detail.get("matched_site_address", ""),
                        "pages": detail.get("pages", ""),
                        "grantors": detail.get("grantors", ""),
                        "grantees": detail.get("grantees", ""),
                        "value_correlation_signal": _signal(crypto_row["interpretation"], value["basis"]),
                        "evidence_boundary": _boundary(value["basis"]),
                    }
                )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = out_dir / f"{args.slug}_{stamp}"
    csv_path = Path(f"{base}.csv")
    md_path = Path(f"{base}.md")
    summary_path = Path(f"{base}.summary.json")

    _write_csv(csv_path, rows)
    summary = {
        "generated_utc": stamp,
        "crypto_csv": args.crypto_csv,
        "detail_csvs": args.detail_csv,
        "rows": len(rows),
        "documents_with_transfer_tax_value": sum(1 for row in rows if row["value_basis"] == "recorder_transfer_tax_amount"),
        "documents_missing_value": sum(1 for row in rows if row["value_basis"] == "value_unavailable_in_current_index"),
        "dtt_formula": "estimated_net_consideration = transfer_tax_amount / 1.10 * 1000",
        "boundary": "Transfer-tax-derived consideration is an estimate of net consideration, not market value or total equity. Official deed images and assessor value history are still required.",
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(_render(summary, rows), encoding="utf-8")
    print(json.dumps({"csv": str(csv_path), "summary": str(summary_path), "report": str(md_path)}, indent=2))
    return 0


def _load_detail_rows(path: Path) -> dict[str, dict[str, str]]:
    by_doc = {}
    if not path.exists():
        return by_doc
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            doc = row.get("document_number", "")
            if doc:
                by_doc[doc] = row
    return by_doc


def _value_from_detail(row: dict[str, str]) -> dict[str, object]:
    pairs = _detail_pairs(row)
    transfer_tax = _float(pairs.get("Transfer Tax Amount", ""))
    if transfer_tax is not None:
        return {
            "transfer_tax_amount": transfer_tax,
            "estimated_net_consideration": round((transfer_tax / DTT_RATE_PER_1000) * 1000, 2),
            "basis": "recorder_transfer_tax_amount",
        }
    return {
        "transfer_tax_amount": "",
        "estimated_net_consideration": "",
        "basis": "value_unavailable_in_current_index",
    }


def _detail_pairs(row: dict[str, str]) -> dict[str, str]:
    raw = row.get("detail_pairs_json", "")
    if not raw:
        return {}
    try:
        return {item.get("caption", ""): item.get("value", "") for item in json.loads(raw)}
    except json.JSONDecodeError:
        return {}


def _crypto_notional_usd(row: dict[str, str]) -> float | None:
    close = _float(row.get("event_close_usd", ""))
    volume = _float(row.get("event_exchange_volume_units", ""))
    if close is None or volume is None:
        return None
    return close * volume


def _signal(crypto_interpretation: str, value_basis: str) -> str:
    crypto_elevated = "elevated" in crypto_interpretation
    value_present = value_basis == "recorder_transfer_tax_amount"
    if crypto_elevated and value_present:
        return "elevated_crypto_with_transfer_tax_value"
    if crypto_elevated and not value_present:
        return "elevated_crypto_but_property_value_missing"
    if value_present:
        return "property_value_present_crypto_not_elevated"
    return "property_value_missing_crypto_not_elevated"


def _boundary(value_basis: str) -> str:
    if value_basis == "recorder_transfer_tax_amount":
        return "Estimated from transfer tax. Verify with deed image, declaration, liens/encumbrances, and assessor value history."
    return "No value/APN/address in current index row. Pull official image and assessor parcel history before valuation claims."


def _render(summary: dict[str, object], rows: list[dict[str, object]]) -> str:
    elevated = [row for row in rows if "elevated_crypto" in row["value_correlation_signal"]]
    valued = [row for row in rows if row["value_basis"] == "recorder_transfer_tax_amount"]
    lines = [
        "# Property Value and Crypto Escrow-Window Correlation",
        "",
        f"Generated UTC: `{summary['generated_utc']}`",
        "",
        "## Boundary",
        "",
        "This report correlates property-value indicators with crypto market activity around transfer dates. It does not prove fraud, consideration, equity, wallet ownership, or transaction attribution.",
        "",
        "Transfer-tax-derived values estimate net consideration only. They are not full market value and can exclude liens or encumbrances depending on the declaration.",
        "",
        "## Summary",
        "",
        f"- Correlation rows: `{summary['rows']}`",
        f"- Rows with transfer-tax-derived value: `{summary['documents_with_transfer_tax_value']}`",
        f"- Rows missing value in current index: `{summary['documents_missing_value']}`",
        f"- Formula used: `{summary['dtt_formula']}`",
        "",
        "## Elevated Crypto Rows With Value Status",
        "",
        "| Date | Asset | Doc | Parties | Crypto Signal | Transfer Tax | Est. Net Consideration | Value/Notional Ratio | Value Signal |",
        "|---|---|---|---|---|---:|---:|---:|---|",
    ]
    for row in elevated:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["event_date"]),
                    str(row["asset"]),
                    str(row["document_number"]),
                    _esc(str(row["parties_cluster"])[:140]),
                    str(row["crypto_interpretation"]),
                    str(row["transfer_tax_amount"]),
                    str(row["estimated_net_consideration_from_transfer_tax"]),
                    str(row["value_to_crypto_daily_notional_ratio"]),
                    str(row["value_correlation_signal"]),
                ]
            )
            + " |"
        )
    lines.extend(["", "## Rows With Computed Property-Value Signal", ""])
    lines.append("| Date | Asset | Doc | City | Tract | Lot | Transfer Tax | Est. Net Consideration | Crypto Signal |")
    lines.append("|---|---|---|---|---|---|---:|---:|---|")
    for row in valued:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["event_date"]),
                    str(row["asset"]),
                    str(row["document_number"]),
                    str(row["city"]),
                    str(row["tract_no"]),
                    str(row["lot_no"]),
                    str(row["transfer_tax_amount"]),
                    str(row["estimated_net_consideration_from_transfer_tax"]),
                    str(row["crypto_interpretation"]),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Granular Next Pulls",
            "",
            "- Pull official images for every elevated crypto row where `value_correlation_signal` is `elevated_crypto_but_property_value_missing`.",
            "- For `2024000290531`, verify the transfer-tax declaration, legal description, APN, and whether continuing liens/encumbrances were excluded.",
            "- For Center Street assignment clusters, image pulls are required because the current index rows expose pages/parties but not APN, address, consideration, or loan amount.",
            "- If bank/exchange records or wallet addresses are later obtained, correlate exact crypto transaction timestamps to escrow deposit, payoff, substitution, assignment, and reconveyance dates.",
        ]
    )
    return "\n".join(lines) + "\n"


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else [])
        writer.writeheader()
        writer.writerows(rows)


def _ratio(value: object, notional: float | None) -> object:
    if value == "" or notional in (None, 0):
        return ""
    return round(float(value) / float(notional), 8)


def _round_money(value: float | None) -> object:
    return "" if value is None else round(value, 2)


def _float(value: object) -> float | None:
    try:
        if value == "":
            return None
        return float(str(value).replace("$", "").replace(",", ""))
    except ValueError:
        return None


def _esc(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


if __name__ == "__main__":
    raise SystemExit(main())

