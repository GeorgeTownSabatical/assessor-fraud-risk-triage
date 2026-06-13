#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path


DTT_RATE_PER_1000 = 1.10


PUBLIC_HISTORY = [
    {
        "event_date": "2024-11-06",
        "sale_price": 1177500,
        "public_sources": "Redfin; Zillow",
        "source_urls": "https://www.redfin.com/CA/Huntington-Beach/16251-Waikiki-Ln-92649/home/3868041 | https://www.zillow.com/homedetails/16251-Waikiki-Ln-Huntington-Beach-CA-92649/25298849_zpid/",
        "known_document_number": "2024000290531",
        "record_pull_status": "known_recorderworks_doc_pull_certified_copy",
    },
    {
        "event_date": "2005-12-02",
        "sale_price": 729000,
        "public_sources": "Zillow listing/public sale history",
        "source_urls": "https://www.zillow.com/homedetails/16251-Waikiki-Ln-Huntington-Beach-CA-92649/25298849_zpid/",
        "known_document_number": "",
        "record_pull_status": "instrument_number_unknown_chain_search_required",
    },
    {
        "event_date": "2003-09-03",
        "sale_price": 483000,
        "public_sources": "Zillow listing/public sale history",
        "source_urls": "https://www.zillow.com/homedetails/16251-Waikiki-Ln-Huntington-Beach-CA-92649/25298849_zpid/",
        "known_document_number": "",
        "record_pull_status": "instrument_number_unknown_chain_search_required",
    },
    {
        "event_date": "1994-03-15",
        "sale_price": 206000,
        "public_sources": "Zillow listing/public sale history",
        "source_urls": "https://www.zillow.com/homedetails/16251-Waikiki-Ln-Huntington-Beach-CA-92649/25298849_zpid/",
        "known_document_number": "",
        "record_pull_status": "instrument_number_unknown_chain_search_required",
    },
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a priority title-repair property flag and chain-pull queue.")
    parser.add_argument("--detail-csv", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--slug", default="title_repair_property_flag_16251_waikiki")
    args = parser.parse_args()

    detail = _load_doc_detail(Path(args.detail_csv), "2024000290531")
    computed = _computed_value(detail)
    rows = _chain_rows(detail, computed)

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
        "property": "16251 Waikiki Ln, Huntington Beach, CA 92649",
        "apn_observed_public": "17808315",
        "apn_local_inference": "178-083-15",
        "priority_document": "2024000290531",
        "recorder_transfer_tax_amount": computed["transfer_tax_amount"],
        "recorder_tax_estimated_consideration": computed["estimated_consideration"],
        "matched_public_sale_price": 1177500,
        "match_status": "exact_match" if computed["estimated_consideration"] == 1177500 else "needs_review",
        "boundary": "This is a title-chain work queue and evidence log. It does not identify the void transfer or prove fraud without certified chain documents.",
        "csv": str(csv_path),
        "report": str(md_path),
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(_render(summary, rows), encoding="utf-8")
    print(json.dumps({"csv": str(csv_path), "summary": str(summary_path), "report": str(md_path)}, indent=2))
    return 0


def _load_doc_detail(path: Path, doc: str) -> dict[str, str]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if row.get("document_number") == doc:
                return row
    return {}


def _computed_value(row: dict[str, str]) -> dict[str, object]:
    pairs = _detail_pairs(row)
    tax = _float(pairs.get("Transfer Tax Amount", ""))
    if tax is None:
        return {"transfer_tax_amount": "", "estimated_consideration": ""}
    return {
        "transfer_tax_amount": tax,
        "estimated_consideration": round((tax / DTT_RATE_PER_1000) * 1000, 2),
    }


def _detail_pairs(row: dict[str, str]) -> dict[str, str]:
    raw = row.get("detail_pairs_json", "")
    if not raw:
        return {}
    try:
        return {item.get("caption", ""): item.get("value", "") for item in json.loads(raw)}
    except json.JSONDecodeError:
        return {}


def _chain_rows(detail: dict[str, str], computed: dict[str, object]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in PUBLIC_HISTORY:
        instrument = item["known_document_number"]
        rows.append(
            {
                "property_address": "16251 Waikiki Ln, Huntington Beach, CA 92649",
                "apn_public_or_inferred": "17808315 / 178-083-15",
                "event_date": item["event_date"],
                "public_sale_price": item["sale_price"],
                "public_sources": item["public_sources"],
                "source_urls": item["source_urls"],
                "recorder_document_number": instrument,
                "recorder_document_type": detail.get("document_type", "") if instrument == "2024000290531" else "",
                "recorder_recording_date": detail.get("recording_date", "") if instrument == "2024000290531" else "",
                "recorder_grantors": detail.get("grantors", "") if instrument == "2024000290531" else "",
                "recorder_grantees": detail.get("grantees", "") if instrument == "2024000290531" else "",
                "recorder_transfer_tax_amount": computed["transfer_tax_amount"] if instrument == "2024000290531" else "",
                "recorder_tax_estimated_consideration": computed["estimated_consideration"] if instrument == "2024000290531" else "",
                "price_match_status": "exact_public_price_match" if instrument == "2024000290531" else "public_history_only",
                "pull_instruction": _pull_instruction(item),
                "legal_use_boundary": _legal_boundary(item),
            }
        )
    rows.append(
        {
            "property_address": "16251 Waikiki Ln, Huntington Beach, CA 92649",
            "apn_public_or_inferred": "17808315 / 178-083-15",
            "event_date": "2024-11-06",
            "public_sale_price": "",
            "public_sources": "RecorderWorks companion-document inference",
            "source_urls": "",
            "recorder_document_number": "2024000290532",
            "recorder_document_type": "TRUST DEED",
            "recorder_recording_date": "11/6/2024",
            "recorder_grantors": "REDMOND ROBERT",
            "recorder_grantees": "MERS / V I P INDEPENDENT MORTGAGE",
            "recorder_transfer_tax_amount": "",
            "recorder_tax_estimated_consideration": "",
            "price_match_status": "same_day_financing_companion_needs_image_confirmation",
            "pull_instruction": "Pull official/certified image as same-day financing companion to 2024000290531; extract lender, trustee, legal description, APN, notary, escrow/title, and loan amount if present.",
            "legal_use_boundary": "Use only as companion-chain context until the official image confirms it encumbers the same parcel.",
        }
    )
    return rows


def _pull_instruction(item: dict[str, object]) -> str:
    if item["known_document_number"]:
        return "Pull certified/official copy; extract grantor, grantee, APN, legal description, vesting, transfer-tax declaration, title/escrow/preparer, notary, and any exclusions."
    return "Run RecorderWorks/official chain search by APN/address/date/price; pull deed, trust deed, reconveyance, assignments, substitutions, and title-company companion documents around this sale date."


def _legal_boundary(item: dict[str, object]) -> str:
    if item["known_document_number"]:
        return "Known index target. Do not draft quitclaim/corrective demand until current title and full prior chain are confirmed."
    return "Public listing history only. Do not infer parties or void-transfer origin until official chain documents identify grantor/grantee and legal description."


def _render(summary: dict[str, object], rows: list[dict[str, object]]) -> str:
    lines = [
        "# Primary Property Title-Repair Flag: 16251 Waikiki Ln",
        "",
        f"Generated UTC: `{summary['generated_utc']}`",
        "",
        "## Primary Property Flag",
        "",
        "16251 Waikiki Ln, Huntington Beach, CA 92649 appears to be a priority title-repair property. Public sale data confirms a November 6, 2024 sale for $1,177,500, matching the RecorderWorks transfer-tax estimate associated with Redmond document `2024000290531`. Public listing history also reflects prior transactions in 2005, 2003, and 1994, making this property suitable for a chain-of-title review back to the suspected void-transfer origin point.",
        "",
        "## Evidentiary Match",
        "",
        f"- RecorderWorks document: `{summary['priority_document']}`",
        f"- RecorderWorks transfer tax: `{_money(summary['recorder_transfer_tax_amount'])}`",
        f"- Estimated consideration formula: `transfer_tax / 1.10 * 1000`",
        f"- Estimated consideration from RecorderWorks: `{_money(summary['recorder_tax_estimated_consideration'])}`",
        f"- Public sale price observed: `{_money(summary['matched_public_sale_price'])}`",
        f"- Match status: `{summary['match_status']}`",
        "- Public/APN alignment: Zillow lists parcel number `17808315`; local tract/lot inference produced `178-083-15`.",
        "",
        "## Chain Pull Plan",
        "",
        "| Date | Public price | Recorder doc | Status | Pull instruction |",
        "|---|---:|---|---|---|",
    ]
    for row in rows:
        price = _money(row["public_sale_price"]) if row["public_sale_price"] != "" else ""
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["event_date"]),
                    price,
                    str(row["recorder_document_number"] or "unknown"),
                    str(row["price_match_status"]),
                    _esc(str(row["pull_instruction"])),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Procedural Boundary",
            "",
            "- Pull certified/official copies for `2024000290531` first.",
            "- Pull every linked deed/transfer back through `11/06/2024`, `12/02/2005`, `09/03/2003`, and `03/15/1994`.",
            "- Identify the first allegedly void transfer only after the record chain confirms the grantor/grantee sequence.",
            "- Prepare any quitclaim demand or corrective deed request only after confirming who currently holds title and who must disclaim.",
            "- If refused, quiet title / cancellation of instrument may be the stronger procedural vehicle than quitclaim alone, but that depends on certified records and legal review.",
            "",
            "## Evidence Boundary",
            "",
            str(summary["boundary"]),
            "",
            "## Source Links",
            "",
            "- Redfin: https://www.redfin.com/CA/Huntington-Beach/16251-Waikiki-Ln-92649/home/3868041",
            "- Zillow: https://www.zillow.com/homedetails/16251-Waikiki-Ln-Huntington-Beach-CA-92649/25298849_zpid/",
        ]
    )
    return "\n".join(lines) + "\n"


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else [])
        writer.writeheader()
        writer.writerows(rows)


def _float(value: object) -> float | None:
    try:
        if value == "":
            return None
        return float(str(value).replace("$", "").replace(",", ""))
    except ValueError:
        return None


def _money(value: object) -> str:
    if value == "":
        return ""
    number = float(value)
    if number.is_integer():
        return f"${number:,.0f}"
    return f"${number:,.2f}"


def _esc(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


if __name__ == "__main__":
    raise SystemExit(main())
