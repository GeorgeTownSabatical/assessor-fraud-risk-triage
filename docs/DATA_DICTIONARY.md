# Data Dictionary

## Instruments CSV

Required:

- `document_number`: Recorder instrument number.
- `recording_date`: Recording date. Supports `YYYY-MM-DD`, `MM/DD/YYYY`, `Mon DD, YYYY`, and `YYYYMMDD`.
- `document_type`: Recorder document type.

Strongly recommended:

- `apn`: Assessor parcel number.
- `address`: Site or situs address.
- `grantors`: From-party names.
- `grantees`: To-party names.

Optional enrichment fields:

- `title_trustee`
- `preparer`
- `notary`
- `escrow`

Aliases such as `instrument_number`, `recorded_date`, `doc_type`, `parcel`, and
`site_address` are accepted.

## Cases CSV

Optional. Used to add vulnerable-population context.

- `case_number`
- `filing_date` or `event_date`
- `case_type`
- `related_party_name`

Case types containing probate, conservator, guardian, LPS, mental, elder, or
dependent terms are treated as vulnerable-context records.

## Entities CSV

Optional. Used to corroborate entity counterparties.

- `entity_name`
- `status`
- `jurisdiction`

Inactive, suspended, or dissolved statuses add review weight when the entity is
present in an instrument.

