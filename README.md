# Assessor Fraud Risk Triage

Explainable, CSV-first scoring for recorder and assessor offices that need to
prioritize potential property-transfer fraud review across large databases.

This project does not make fraud findings. It produces triage leads with
auditable factors, confidence bands, and data-quality notes so trained public
staff can decide what warrants official review.

## What It Looks For

- Rapid conveyance, trust deed, assignment, substitution, and reconveyance chains.
- Same-day or near-adjacent instrument-number bursts.
- Transfers near probate, conservatorship, guardianship, LPS, or other vulnerable-population case events.
- Repeated title, trustee, preparer, notary, or escrow actors across elevated records.
- Distress indicators such as defaults, liens, abstracts, substitutions, trustee sales, and reconveyances.
- Entity-recipient risk, including SPE/LLC/trust counterparties and missing or inactive registry corroboration.
- Data gaps that should block overclaiming and route the record to document pull or manual review.

## Quick Start

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
assessor-fraud-risk-triage score \
  --instruments examples/instruments.csv \
  --cases examples/cases.csv \
  --entities examples/entities.csv \
  --out out
```

Outputs:

- `out/risk_scores.csv`: one row per instrument with score, band, and factors.
- `out/chain_flags.csv`: APN/address clusters and detected sequence patterns.
- `out/entity_graph_edges.csv`: party-to-party transfer and encumbrance edges.
- `out/summary.json`: run metadata and band counts.

## Input Philosophy

The tool accepts ordinary CSV exports. If your office has richer fields, include
them; if not, the scorer degrades gracefully and records data-quality cautions.
See [docs/DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md).

## Governance Guardrails

- Use as a review-prioritization system, not an automated enforcement system.
- Keep protected personal information in the assessor environment.
- Publish only aggregate metrics or redacted case packets.
- Treat high scores as "pull the official documents and inspect," not "fraud occurred."

## Development

```bash
python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m assessor_fraud_risk_triage.cli score \
  --instruments examples/instruments.csv \
  --cases examples/cases.csv \
  --entities examples/entities.csv \
  --out out/dev
```
