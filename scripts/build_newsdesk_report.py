#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from assessor_fraud_risk_triage.io import read_csv, write_csv, write_json
from assessor_fraud_risk_triage.scoring import result_rows, score_records


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a versioned newsdesk triage report from scored recorder data.")
    parser.add_argument("--instruments", action="append", required=True, help="Instrument CSV. Repeatable.")
    parser.add_argument("--cases", action="append", default=[], help="Case-context CSV. Repeatable.")
    parser.add_argument("--entities", action="append", default=[], help="Entity registry CSV. Repeatable.")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--slug", default="newsdesk_assessor_metrics")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = out_dir / f"{args.slug}_{stamp}"

    instruments = _merge_csvs(args.instruments)
    cases = _dedupe_cases(_merge_csvs(args.cases))
    entities = _merge_csvs(args.entities)
    results, chains, edges, summary = score_records(instruments, cases=cases, entities=entities)
    rows = result_rows(results)
    rows.sort(key=lambda row: (-float(row["score"]), row["recording_date"], row["document_number"]))
    unique_rows = _unique_documents(rows)

    scored_csv = f"{base}_risk_scores.csv"
    chains_csv = f"{base}_chain_flags.csv"
    edges_csv = f"{base}_entity_graph_edges.csv"
    summary_json = f"{base}.summary.json"
    report_md = f"{base}.md"

    write_csv(scored_csv, rows, list(rows[0].keys()) if rows else [])
    write_csv(chains_csv, chains, ["cluster_key", "pattern", "days_between", "document_numbers", "recording_dates", "document_types", "status"])
    write_csv(edges_csv, edges, ["source", "target", "relationship", "document_number", "recording_date", "apn"])

    top_rows = unique_rows[:50]
    band_counts = Counter(row["band"] for row in rows)
    factor_counts = Counter()
    for row in rows:
        for factor in str(row["factors"]).split("; "):
            if factor:
                factor_counts[factor.split(":")[0]] += 1

    source_hashes = {path: _sha256(Path(path)) for path in args.instruments + args.cases + args.entities}
    summary.update(
        {
            "generated_utc": stamp,
            "source_files": source_hashes,
            "report_md": str(report_md),
            "risk_scores_csv": str(scored_csv),
            "chain_flags_csv": str(chains_csv),
            "entity_graph_edges_csv": str(edges_csv),
            "top_score": rows[0]["score"] if rows else None,
            "top_document": rows[0]["document_number"] if rows else None,
            "unique_documents": len(unique_rows),
        }
    )
    write_json(summary_json, summary)
    Path(report_md).write_text(_render_report(stamp, summary, band_counts, factor_counts, top_rows, chains[:30]), encoding="utf-8")
    print(json.dumps({"report": report_md, "summary": summary_json, "risk_scores": scored_csv, "records": len(rows)}, indent=2))
    return 0


def _merge_csvs(paths: list[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in paths:
        for row in read_csv(path):
            row = dict(row)
            row.setdefault("source_file", path)
            rows.append(row)
    return rows


def _dedupe_cases(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str, str, str]] = set()
    deduped: list[dict[str, str]] = []
    for row in rows:
        key = (
            row.get("case_number", ""),
            row.get("filing_date", ""),
            row.get("case_type", ""),
            row.get("related_party_name", "") or row.get("party", "") or row.get("name", ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _unique_documents(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    by_doc: dict[str, dict[str, object]] = {}
    cases_by_doc: dict[str, set[str]] = {}
    for row in rows:
        doc = str(row.get("document_number", ""))
        if not doc:
            continue
        cases_by_doc.setdefault(doc, set())
        if row.get("case_number"):
            cases_by_doc[doc].add(str(row["case_number"]))
        current = by_doc.get(doc)
        if current is None or float(row["score"]) > float(current["score"]):
            by_doc[doc] = dict(row)
    for doc, row in by_doc.items():
        row["case_number"] = ";".join(sorted(cases_by_doc.get(doc, set()))) or row.get("case_number", "")
    return sorted(by_doc.values(), key=lambda row: (-float(row["score"]), str(row["recording_date"]), str(row["document_number"])))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _render_report(
    stamp: str,
    summary: dict[str, object],
    band_counts: Counter[str],
    factor_counts: Counter[str],
    top_rows: list[dict[str, object]],
    chain_rows: list[dict[str, object]],
) -> str:
    lines = [
        "# Newsdesk Fraud-Risk Triage Report",
        "",
        f"Generated UTC: `{stamp}`",
        "",
        "## Scope and Caveat",
        "",
        "This is an updated triage report using the assessor-style confidence metrics. It is not a fraud finding, legal conclusion, title opinion, or accusation. High scores mean the record should be prioritized for official document pulls and trained review.",
        "",
        "## Run Summary",
        "",
        f"- Records scored: `{summary.get('records_scored', 0)}`",
        f"- Unique documents represented: `{summary.get('unique_documents', 0)}`",
        f"- High-review leads: `{band_counts.get('high_review', 0)}`",
        f"- Medium-review leads: `{band_counts.get('medium_review', 0)}`",
        f"- Low-context records: `{band_counts.get('low_context', 0)}`",
        f"- Chain flags: `{summary.get('chain_flags', 0)}`",
        f"- Entity graph edges: `{summary.get('graph_edges', 0)}`",
        f"- Top document: `{summary.get('top_document')}` with score `{summary.get('top_score')}`",
        "",
        "## Most Common Elevated Factors",
        "",
    ]
    for factor, count in factor_counts.most_common(20):
        lines.append(f"- `{factor}`: {count}")
    lines.extend(["", "## Top Review Leads", ""])
    lines.append("| Rank | Score | Band | Document | Case(s) | Date | Type | APN | Parties | Factors |")
    lines.append("|---:|---:|---|---|---|---|---|---|---|---|")
    for idx, row in enumerate(top_rows, 1):
        lines.append(
            "| "
            + " | ".join(
                [
                    str(idx),
                    str(row["score"]),
                    _esc(row["band"]),
                    _esc(row["document_number"]),
                    _esc(row.get("case_number", ""))[:120],
                    _esc(row["recording_date"]),
                    _esc(row["document_type"]),
                    _esc(row["apn"]),
                    _esc(row["parties"])[:160],
                    _esc(row["factors"])[:220],
                ]
            )
            + " |"
        )
    lines.extend(["", "## Chain Patterns Requiring Document Pull", ""])
    lines.append("| Pattern | Days | Documents | Dates | Types |")
    lines.append("|---|---:|---|---|---|")
    for row in chain_rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    _esc(row["pattern"]),
                    str(row["days_between"]),
                    _esc(row["document_numbers"]),
                    _esc(row["recording_dates"]),
                    _esc(row["document_types"]),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Practical Next Pulls",
            "",
            "1. Pull official images for all high-review documents before describing any conduct as suspicious beyond triage language.",
            "2. For each high-review chain, verify APN, legal description, notary, preparer, escrow number, mailing address changes, and related instrument references.",
            "3. Compare title/trustee/preparer/notary recurrence against countywide baseline before treating repetition as probative.",
            "4. Preserve source file hashes and generated CSVs with any public or newsdesk packet.",
            "",
            "## Output Files",
            "",
            f"- Risk scores CSV: `{summary.get('risk_scores_csv')}`",
            f"- Chain flags CSV: `{summary.get('chain_flags_csv')}`",
            f"- Entity graph edges CSV: `{summary.get('entity_graph_edges_csv')}`",
            f"- Summary JSON: `{summary.get('report_md', '').replace('.md', '.summary.json')}`",
        ]
    )
    return "\n".join(lines) + "\n"


def _esc(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


if __name__ == "__main__":
    raise SystemExit(main())
