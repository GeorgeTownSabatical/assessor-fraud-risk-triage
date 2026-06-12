# Methodology

This scorer is a deterministic evidence-weighting system. It is intentionally
simple enough for public staff, auditors, and outside reviewers to reproduce.

## Score Bands

- `high_review`: 80-100. Pull official images, verify chain, and route to trained review.
- `medium_review`: 50-79. Review if connected to a current audit, complaint, vulnerable case, or repeated actor.
- `low_context`: 0-49. Retain as context unless later data adds corroboration.

## Weighted Factors

The current default weights favor corroborated patterns over single facts:

- Transfer document: +8.
- Encumbrance, assignment, substitution, or reconveyance document: +10.
- Distress/default/lien/reconveyance indicator: +15.
- LLC/SPE/trust/corporate counterparty: +10.
- Detected chain pattern: +22 each.
- Same-day or near-adjacent instrument burst: +12.
- Vulnerable-population case overlap: +16 to +30.
- Repeated trustee/title/preparer/notary/escrow actor: +6 each, capped at +18.
- Missing or inactive entity registry corroboration: +6 each, capped at +12.
- Key data-quality gaps: +3 to +4 as cautionary review friction, not proof.

Scores are capped at 100.

## Review Doctrine

The tool elevates records because multiple independent signals converge. It
does not determine intent, legality, title validity, or criminality. Every high
lead still needs official document images, assessor parcel history, chain of
title review, and case-by-case legal analysis.

## Extending Metrics

County-specific versions should add fields rather than replace the common
schema. Useful additions include sale price, assessed value delta, exemption
changes, mailing address changes, senior/disabled/veteran exemption flags,
death-date proximity, deed image OCR, preparer address, notary commission,
escrow number, and assessor workflow status.

