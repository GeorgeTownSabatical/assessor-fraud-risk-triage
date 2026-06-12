from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
import re
from typing import Iterable


ENTITY_TERMS = ("LLC", "L.L.C", "SPE", "CORP", "INC", "LP", "LLP", "TRUST", "HOLDING")
DISTRESS_TERMS = (
    "DEFAULT",
    "LIEN",
    "ABSTRACT",
    "TRUSTEE SALE",
    "SUBSTITUTION",
    "RECONVEYANCE",
    "FORECLOSURE",
    "DELINQUENT",
)
TRANSFER_TERMS = ("GRANT DEED", "QUITCLAIM", "TRANSFER", "AFFIDAVIT DEATH", "DEED")
ENCUMBRANCE_TERMS = ("TRUST DEED", "DEED OF TRUST", "ASGT TRUST", "ASSIGNMENT", "SUBSTITUTION", "RECONVEYANCE")
VULNERABLE_CASE_TERMS = ("PROBATE", "CONSERVATOR", "GUARDIAN", "LPS", "MENTAL", "ELDER", "DEPENDENT")


@dataclass
class ScoreResult:
    document_number: str
    recording_date: str
    document_type: str
    apn: str
    address: str
    parties: str
    score: float
    band: str
    factors: list[str] = field(default_factory=list)
    cautions: list[str] = field(default_factory=list)
    status: str = "triage_lead_not_fraud_finding"


def score_records(
    instruments: list[dict[str, str]],
    cases: list[dict[str, str]] | None = None,
    entities: list[dict[str, str]] | None = None,
    vulnerable_window_days: int = 180,
    adjacency_window: int = 2,
) -> tuple[list[ScoreResult], list[dict[str, object]], list[dict[str, object]], dict[str, object]]:
    cases = cases or []
    entities = entities or []
    normalized = [_normalize_instrument(row) for row in instruments]
    registry = _build_entity_registry(entities)
    actor_counts = _actor_counts(normalized)
    cluster_rows = _cluster_rows(normalized)
    chain_flags = _detect_chains(cluster_rows)
    adjacency = _detect_adjacency(normalized, adjacency_window)
    graph_edges = _build_graph_edges(normalized)

    chain_by_doc = defaultdict(list)
    for flag in chain_flags:
        for doc in str(flag["document_numbers"]).split("|"):
            chain_by_doc[doc].append(str(flag["pattern"]))

    results: list[ScoreResult] = []
    for row in normalized:
        score = 0.0
        factors: list[str] = []
        cautions: list[str] = []
        doc_type = row["document_type_norm"]
        parties_norm = row["parties_norm"]

        if any(term in doc_type for term in TRANSFER_TERMS):
            score += 8
            factors.append("transfer_document")
        if any(term in doc_type for term in ENCUMBRANCE_TERMS):
            score += 10
            factors.append("encumbrance_or_lien_chain_document")
        if any(term in doc_type for term in DISTRESS_TERMS):
            score += 15
            factors.append("distress_default_lien_or_reconveyance_indicator")
        if _has_entity_party(parties_norm):
            score += 10
            factors.append("entity_counterparty_llc_spe_trust_or_corporation")

        for pattern in chain_by_doc.get(row["document_number"], []):
            score += 22
            factors.append(f"chain_pattern:{pattern}")

        if row["document_number"] in adjacency:
            score += 12
            factors.append("instrument_number_adjacency_or_same_day_burst")

        vulnerable_hits = _vulnerable_case_hits(row, cases, vulnerable_window_days)
        if vulnerable_hits:
            score += min(30, 16 + 4 * len(vulnerable_hits))
            factors.append("vulnerable_population_case_overlap:" + "|".join(vulnerable_hits[:3]))

        repeated_actors = _repeated_actors(row, actor_counts)
        if repeated_actors:
            score += min(18, 6 * len(repeated_actors))
            factors.append("repeated_title_trustee_preparer_notary_or_escrow:" + "|".join(repeated_actors[:4]))

        entity_warnings = _entity_registry_warnings(row, registry)
        if entity_warnings:
            score += min(12, 6 * len(entity_warnings))
            factors.extend(entity_warnings)

        if not row["apn"] and not row["address_norm"]:
            cautions.append("missing_apn_and_address_limits_chain_resolution")
            score += 4
        if not row["grantors_norm"] or not row["grantees_norm"]:
            cautions.append("missing_party_side_limits_directional_analysis")
            score += 3

        score = round(min(score, 100.0), 1)
        results.append(
            ScoreResult(
                document_number=row["document_number"],
                recording_date=row["recording_date"],
                document_type=row["document_type"],
                apn=row["apn"],
                address=row["address"],
                parties=row["parties"],
                score=score,
                band=_band(score),
                factors=sorted(set(factors)),
                cautions=sorted(set(cautions)),
            )
        )

    summary = _summary(results, chain_flags, graph_edges)
    return results, chain_flags, graph_edges, summary


def result_rows(results: Iterable[ScoreResult]) -> list[dict[str, object]]:
    return [
        {
            "document_number": result.document_number,
            "recording_date": result.recording_date,
            "document_type": result.document_type,
            "apn": result.apn,
            "address": result.address,
            "parties": result.parties,
            "score": result.score,
            "band": result.band,
            "status": result.status,
            "factors": "; ".join(result.factors),
            "cautions": "; ".join(result.cautions),
        }
        for result in results
    ]


def _normalize_instrument(row: dict[str, str]) -> dict[str, str]:
    grantors = _first(row, "grantors", "grantor", "from_party")
    grantees = _first(row, "grantees", "grantee", "to_party")
    combined = _first(row, "parties", "grantor_grantees", "names")
    if not combined:
        combined = " | ".join(part for part in (grantors, grantees) if part)
    return {
        **row,
        "document_number": _first(row, "document_number", "instrument_number", "doc_number", "recording_number"),
        "recording_date": _first(row, "recording_date", "recorded_date", "date"),
        "recording_date_obj": _parse_date(_first(row, "recording_date", "recorded_date", "date")),
        "document_type": _first(row, "document_type", "doc_type", "type"),
        "document_type_norm": _norm(_first(row, "document_type", "doc_type", "type")),
        "apn": _first(row, "apn", "parcel", "parcel_number"),
        "address": _first(row, "address", "site_address", "property_address"),
        "address_norm": _norm(_first(row, "address", "site_address", "property_address")),
        "grantors_norm": _norm(grantors),
        "grantees_norm": _norm(grantees),
        "parties": combined,
        "parties_norm": _norm(combined),
        "title_trustee": _first(row, "title_trustee", "trustee", "title_company"),
        "preparer": _first(row, "preparer", "prepared_by"),
        "notary": _first(row, "notary"),
        "escrow": _first(row, "escrow", "escrow_company"),
    }


def _cluster_rows(rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    clusters: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        key = row["apn"] or row["address_norm"] or row["parties_norm"][:48]
        clusters[key].append(row)
    for grouped in clusters.values():
        grouped.sort(key=lambda item: (item["recording_date_obj"] or date.min, item["document_number"]))
    return clusters


def _detect_chains(clusters: dict[str, list[dict[str, str]]]) -> list[dict[str, object]]:
    flags: list[dict[str, object]] = []
    for key, rows in clusters.items():
        for i, first in enumerate(rows):
            for second in rows[i + 1 : i + 6]:
                days = _days_between(first, second)
                if days is None or days > 540:
                    continue
                first_type = first["document_type_norm"]
                second_type = second["document_type_norm"]
                if any(term in first_type for term in TRANSFER_TERMS) and "TRUST DEED" in second_type and days <= 7:
                    flags.append(_chain_flag(key, "rapid_transfer_to_trust_deed", [first, second], days))
                if "TRUST DEED" in first_type and any(term in second_type for term in ("ASGT", "ASSIGNMENT", "SUBSTITUTION", "RECONVEYANCE")):
                    flags.append(_chain_flag(key, "trust_deed_assignment_substitution_or_reconveyance", [first, second], days))
                if any(term in first_type for term in ("SUBSTITUTION", "DEFAULT")) and "RECONVEYANCE" in second_type and days <= 45:
                    flags.append(_chain_flag(key, "default_substitution_reconveyance_sequence", [first, second], days))
    return flags


def _chain_flag(key: str, pattern: str, rows: list[dict[str, str]], days: int) -> dict[str, object]:
    return {
        "cluster_key": key,
        "pattern": pattern,
        "days_between": days,
        "document_numbers": "|".join(row["document_number"] for row in rows),
        "recording_dates": "|".join(row["recording_date"] for row in rows),
        "document_types": "|".join(row["document_type"] for row in rows),
        "status": "triage_pattern_not_fraud_finding",
    }


def _detect_adjacency(rows: list[dict[str, str]], window: int) -> set[str]:
    by_date = defaultdict(list)
    for row in rows:
        by_date[row["recording_date"]].append(row)
    flagged: set[str] = set()
    for same_day in by_date.values():
        parsed = [(row, _parse_int(row["document_number"])) for row in same_day]
        for row, number in parsed:
            if number is None:
                continue
            for other, other_number in parsed:
                if row is other or other_number is None:
                    continue
                if abs(number - other_number) <= window and _party_overlap(row, other):
                    flagged.add(row["document_number"])
                    flagged.add(other["document_number"])
    return flagged


def _build_graph_edges(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    edges: list[dict[str, object]] = []
    for row in rows:
        grantors = _split_names(row["grantors_norm"])
        grantees = _split_names(row["grantees_norm"])
        if not grantors or not grantees:
            continue
        for grantor in grantors[:8]:
            for grantee in grantees[:8]:
                edges.append(
                    {
                        "source": grantor,
                        "target": grantee,
                        "relationship": row["document_type"],
                        "document_number": row["document_number"],
                        "recording_date": row["recording_date"],
                        "apn": row["apn"],
                    }
                )
    return edges


def _vulnerable_case_hits(row: dict[str, str], cases: list[dict[str, str]], window_days: int) -> list[str]:
    hits: list[str] = []
    for case in cases:
        case_type = _norm(_first(case, "case_type", "type"))
        if not any(term in case_type for term in VULNERABLE_CASE_TERMS):
            continue
        name = _norm(_first(case, "related_party_name", "party", "name"))
        if name and not _token_overlap(name, row["parties_norm"]):
            continue
        case_date = _parse_date(_first(case, "filing_date", "event_date", "date"))
        row_date = row["recording_date_obj"]
        if case_date and row_date and abs((row_date - case_date).days) > window_days:
            continue
        hits.append(_first(case, "case_number", "id") or case_type or "vulnerable_case")
    return hits


def _actor_counts(rows: list[dict[str, str]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in rows:
        for field in ("title_trustee", "preparer", "notary", "escrow"):
            value = _norm(row.get(field, ""))
            if value:
                counts[f"{field}:{value}"] += 1
    return counts


def _repeated_actors(row: dict[str, str], counts: Counter[str], threshold: int = 3) -> list[str]:
    repeated = []
    for field in ("title_trustee", "preparer", "notary", "escrow"):
        value = _norm(row.get(field, ""))
        key = f"{field}:{value}"
        if value and counts[key] >= threshold:
            repeated.append(f"{field}={value}")
    return repeated


def _build_entity_registry(entities: list[dict[str, str]]) -> dict[str, str]:
    registry: dict[str, str] = {}
    for entity in entities:
        name = _norm(_first(entity, "entity_name", "name"))
        if name:
            registry[name] = _norm(_first(entity, "status", "entity_status")) or "UNKNOWN"
    return registry


def _entity_registry_warnings(row: dict[str, str], registry: dict[str, str]) -> list[str]:
    if not registry or not _has_entity_party(row["parties_norm"]):
        return []
    warnings = []
    for name in _split_names(row["parties_norm"]):
        if not _has_entity_party(name):
            continue
        status = registry.get(name)
        if status is None:
            warnings.append("entity_registry_missing_match")
        elif "INACTIVE" in status or "SUSPEND" in status or "DISSOL" in status:
            warnings.append("entity_registry_inactive_or_suspended")
    return sorted(set(warnings))


def _summary(results: list[ScoreResult], chains: list[dict[str, object]], edges: list[dict[str, object]]) -> dict[str, object]:
    bands = Counter(result.band for result in results)
    return {
        "status": "triage_summary_not_fraud_finding",
        "records_scored": len(results),
        "band_counts": dict(sorted(bands.items())),
        "chain_flags": len(chains),
        "graph_edges": len(edges),
        "high_review_threshold": 80,
        "medium_review_threshold": 50,
        "method": "deterministic_weighted_rules_v0.1.0",
    }


def _band(score: float) -> str:
    if score >= 80:
        return "high_review"
    if score >= 50:
        return "medium_review"
    return "low_context"


def _days_between(first: dict[str, str], second: dict[str, str]) -> int | None:
    a = first["recording_date_obj"]
    b = second["recording_date_obj"]
    if not a or not b:
        return None
    return abs((b - a).days)


def _party_overlap(first: dict[str, str], second: dict[str, str]) -> bool:
    return _token_overlap(first["parties_norm"], second["parties_norm"]) or (
        first["apn"] and first["apn"] == second["apn"]
    )


def _token_overlap(a: str, b: str) -> bool:
    a_tokens = {token for token in a.split() if len(token) > 2}
    b_tokens = {token for token in b.split() if len(token) > 2}
    return bool(a_tokens & b_tokens)


def _has_entity_party(text: str) -> bool:
    return any(re.search(rf"(^| ){re.escape(term)}($| )", text) for term in ENTITY_TERMS)


def _split_names(text: str) -> list[str]:
    separators = ["|", ";", " AND ", " / "]
    names = [text]
    for separator in separators:
        names = [part for name in names for part in name.split(separator)]
    return [name.strip(" ,") for name in names if name.strip(" ,")]


def _first(row: dict[str, str], *keys: str) -> str:
    lower = {key.lower(): value for key, value in row.items()}
    for key in keys:
        value = lower.get(key.lower())
        if value:
            return value.strip()
    return ""


def _parse_date(value: str) -> date | None:
    value = value.strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%b %d, %Y", "%Y%m%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    return None


def _parse_int(value: str) -> int | None:
    digits = "".join(char for char in value if char.isdigit())
    return int(digits) if digits else None


def _norm(value: str) -> str:
    return " ".join(value.upper().replace(",", " ").split())
