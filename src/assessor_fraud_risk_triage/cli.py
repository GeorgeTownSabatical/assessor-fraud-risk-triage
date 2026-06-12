from __future__ import annotations

import argparse
from pathlib import Path

from .io import read_csv, write_csv, write_json
from .scoring import result_rows, score_records


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="assessor-fraud-risk-triage",
        description="Score recorder/assessor records for explainable fraud-risk triage.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    score = subparsers.add_parser("score", help="Score instrument records.")
    score.add_argument("--instruments", required=True, help="Recorder or assessor instrument CSV.")
    score.add_argument("--cases", help="Optional court/probate/vulnerable-context CSV.")
    score.add_argument("--entities", help="Optional entity registry CSV.")
    score.add_argument("--out", required=True, help="Output directory.")
    score.add_argument("--vulnerable-window-days", type=int, default=180)
    score.add_argument("--adjacency-window", type=int, default=2)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "score":
        out_dir = Path(args.out)
        results, chains, edges, summary = score_records(
            read_csv(args.instruments),
            cases=read_csv(args.cases),
            entities=read_csv(args.entities),
            vulnerable_window_days=args.vulnerable_window_days,
            adjacency_window=args.adjacency_window,
        )
        write_csv(
            out_dir / "risk_scores.csv",
            result_rows(results),
            [
                "document_number",
                "recording_date",
                "document_type",
                "case_number",
                "related_party_name",
                "apn",
                "address",
                "parties",
                "score",
                "band",
                "status",
                "factors",
                "cautions",
            ],
        )
        write_csv(
            out_dir / "chain_flags.csv",
            chains,
            ["cluster_key", "pattern", "days_between", "document_numbers", "recording_dates", "document_types", "status"],
        )
        write_csv(
            out_dir / "entity_graph_edges.csv",
            edges,
            ["source", "target", "relationship", "document_number", "recording_date", "apn"],
        )
        write_json(out_dir / "summary.json", summary)
        print(f"scored={summary['records_scored']} high={summary['band_counts'].get('high_review', 0)} out={out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
