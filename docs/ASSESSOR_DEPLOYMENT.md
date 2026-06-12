# Assessor Deployment Guide

## Recommended Workflow

1. Export recorder instruments for the review period.
2. Join APN and situs address from the assessor parcel system.
3. Add optional court/probate/conservatorship context if legally available.
4. Add entity registry status for LLC/SPE/corporate counterparties if available.
5. Run scoring in an internal environment.
6. Pull official document images only for high-review and priority medium-review leads.
7. Record reviewer decisions separately from the score outputs.

## Privacy Controls

- Do not upload protected assessor, court, or medical-adjacent records to public systems.
- Keep raw exports on county-controlled storage.
- Redact names before publishing aggregate methodology examples.
- Maintain an audit log of who ran the scorer, input hashes, config, and output hashes.

## Operational Notes

- Scores are sensitive to data quality. Missing APNs and party sides reduce chain resolution.
- Repeated actors are dataset-relative. Run by consistent periods, such as quarter or year.
- Document images remain decisive for preparer, notary, escrow, signature, and stamp analysis.
- The output should be reviewed by trained staff before referral or public release.

## Integration Pattern

For a whole-database run, schedule monthly or quarterly batches:

```bash
assessor-fraud-risk-triage score \
  --instruments recorder_export.csv \
  --cases vulnerable_context.csv \
  --entities entity_registry.csv \
  --out scoring_run_YYYY_QQ
```

Store `summary.json`, input hashes, and reviewer disposition in the office audit
system. Use `risk_scores.csv` as a queue, not as an enforcement decision.

