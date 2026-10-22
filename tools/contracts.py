"""Conformance harness V1: pure checks over synthetic messages, no product runtime."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.exceptions import NoSuchResource

ROOT = Path(__file__).resolve().parents[1]
MAX_BODY = 1_048_576
MAX_DEPTH = 32
FORMATS = FormatChecker()


class ContractError(ValueError):
    """Only stable code/path are exposed; never include document contents."""

    def __init__(self, code: str, field: str = "") -> None:
        self.code, self.field = code, field
        super().__init__(f"{code}:{field}")


def instant(value: str) -> datetime:
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})",
        value,
    ):
        raise ContractError("INVALID_PUBLICATION")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if abs(result.utcoffset().total_seconds()) > 14 * 3600:
            raise ValueError
        return result.astimezone(timezone.utc)
    except (ValueError, OverflowError) as exc:
        raise ContractError("INVALID_PUBLICATION") from exc


@FORMATS.checks("careerbrain-instant", raises=(ValueError, TypeError))
def valid_instant(value: object) -> bool:
    if not isinstance(value, str):
        return True
    instant(value)
    return True


def public_https(value: str) -> bool:
    try:
        url = urlsplit(value)
        if (
            url.scheme != "https" or not url.hostname or url.username or url.password
            or url.fragment or url.port not in (None, 443)
            or any(c.isspace() or ord(c) < 32 for c in value)
            or "\\" in value
        ):
            return False
        host = url.hostname.lower()
        try:
            if not ipaddress.ip_address(host).is_global:
                return False
        except ValueError:
            if (
                "." not in host or host.endswith((".local", ".internal", ".localhost"))
                or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host)
                or any(not label or len(label) > 63 or label.startswith("-")
                       or label.endswith("-") for label in host.split("."))
                or host.replace(".", "").isdigit()
            ):
                return False
        return not any(re.search(r"token|secret|password|authorization|api.?key", key, re.I)
                       for key, _ in parse_qsl(url.query))
    except (ValueError, TypeError):
        return False


@FORMATS.checks("public-https")
def valid_https(value: object) -> bool:
    return not isinstance(value, str) or public_https(value)


@FORMATS.checks("official-email")
def valid_email(value: object) -> bool:
    if not isinstance(value, str):
        return True
    return bool(re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", value))


def no_remote_reference(uri: str) -> Resource:
    raise NoSuchResource(ref=uri)


SCHEMAS = {
    path.stem.removesuffix(".schema"): json.loads(path.read_text())
    for path in sorted((ROOT / "contracts/v1").glob("*.schema.json"))
}
REGISTRY = Registry(retrieve=no_remote_reference).with_resources(
    (value["$id"], Resource.from_contents(value)) for value in SCHEMAS.values()
)


def validate(name: str, value: object) -> None:
    validator = Draft202012Validator(SCHEMAS[name], registry=REGISTRY, format_checker=FORMATS)
    error = next(validator.iter_errors(value), None)
    if error:
        raise ContractError("SCHEMA_INVALID", "/".join(map(str, error.absolute_path)))
    # JSON Schema minLength permits whitespace; V1 explicitly rejects it.
    def visit(item: object, path: str = "") -> None:
        if isinstance(item, str) and not item.strip():
            raise ContractError("SCHEMA_INVALID", path)
        if isinstance(item, dict):
            for key, child in item.items():
                visit(child, f"{path}/{key}")
        if isinstance(item, list):
            for i, child in enumerate(item):
                visit(child, f"{path}/{i}")
    visit(value)


def strict_load(raw: bytes) -> dict:
    if len(raw) > MAX_BODY:
        raise ContractError("PAYLOAD_TOO_LARGE")

    def pairs(items: list[tuple]) -> dict:
        result = {}
        for key, value in items:
            if key in result:
                raise ContractError("SCHEMA_INVALID")
            result[key] = value
        return result

    def reject_constant(_: str) -> None:
        raise ContractError("SCHEMA_INVALID")

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                           parse_constant=reject_constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ContractError("SCHEMA_INVALID") from exc

    def depth(item: object, level: int = 0) -> None:
        if level > MAX_DEPTH:
            raise ContractError("SCHEMA_INVALID")
        children = item.values() if isinstance(item, dict) else item if isinstance(item, list) else []
        for child in children:
            depth(child, level + 1)
    depth(value)
    if not isinstance(value, dict):
        raise ContractError("SCHEMA_INVALID")
    return value


def digest(value: dict) -> str:
    body = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def replay_decision(existing: str | None, candidate: str, committed: bool = True) -> str:
    """Protocol oracle only; persistence/locks are deliberately absent in pass 01."""
    if existing is None:
        return "NEW"
    if existing != candidate:
        raise ContractError("IDEMPOTENCY_CONFLICT")
    if not committed:
        raise ContractError("BATCH_IN_PROGRESS")
    return "REPLAY"


@dataclass(frozen=True)
class Producer:
    producer_id: str
    sources: frozenset[str]
    evidence: dict[str, dict]
    official_contacts: frozenset[str]


def ingestion(raw: bytes, *, key: str, now: str, producer: Producer,
              known_events: dict[tuple[str, str], dict] | None = None) -> dict:
    value = strict_load(raw)
    validate("ingestion-batch", value)
    if key != value["batch_id"]:
        raise ContractError("SCHEMA_INVALID", "batch_id")
    known = known_events or {}
    seen = {}
    for i, record in enumerate(value["records"]):
        publish = record["operation"] == "publish"
        vacancy = record["vacancy"] if publish else record
        source, external = vacancy["source_id"], vacancy["source_vacancy_id"]
        event = vacancy["event"] if publish else record
        event_key = (source, event["source_event_id"])
        proof = event["provenance"]
        trusted = producer.evidence.get(proof["evidence_id"])
        if source not in producer.sources or trusted is None or any(
            trusted.get(field) != expected for field, expected in {
                "producer_id": producer.producer_id, "source_id": source,
                "authorization_id": proof["authorization_id"],
                "evidence_sha256": proof["evidence_sha256"],
                "evidence_kind": proof["evidence_kind"],
                "source_event_id": event["source_event_id"],
            }.items()
        ):
            raise ContractError("SOURCE_NOT_AUTHORIZED", f"records/{i}")
        observed = instant(proof["observed_at"])
        if observed > instant(now):
            raise ContractError("INVALID_PUBLICATION", f"records/{i}")
        if publish:
            published = instant(event["published_at"])
            if published > observed or published > instant(now) or published != instant(trusted["published_at"]):
                raise ContractError("INVALID_PUBLICATION", f"records/{i}")
            access = vacancy["access"]["value"]
            if access not in producer.official_contacts:
                raise ContractError("INVALID_CONTACT", f"records/{i}")
            if event["kind"] == "republication":
                previous = known.get((source, event["previous_source_event_id"]))
                if (not previous or previous["source_vacancy_id"] != external
                    or instant(previous["published_at"]) >= published
                    or previous["evidence_id"] == proof["evidence_id"]):
                    raise ContractError("INVALID_PUBLICATION", f"records/{i}")
            existing = known.get(event_key)
            if existing and existing["content_digest"] != digest(vacancy):
                raise ContractError("EVENT_CONFLICT", f"records/{i}")
        else:
            existing = known.get(event_key)
            if not existing or existing["source_vacancy_id"] != external:
                raise ContractError("EVENT_CONFLICT", f"records/{i}")
            if record["operation"] == "correct" and "access" in record["correction"]:
                if record["correction"]["access"]["value"] not in producer.official_contacts:
                    raise ContractError("INVALID_CONTACT", f"records/{i}")
        record_digest = digest(record)
        if event_key in seen and seen[event_key] != record_digest:
            raise ContractError("EVENT_CONFLICT", f"records/{i}")
        seen[event_key] = record_digest
    return value


def eligible(published_at: str, account_created_at: str, active: bool = True) -> bool:
    """Temporal conformance oracle, not the matching service."""
    return active and instant(published_at) >= instant(account_created_at)


def validate_evidence(source: str, result: dict, *, schema: str) -> None:
    validate(schema, result)
    for attribute in result["attributes"]:
        if attribute["basis"] == "explicit" and not attribute["evidence"]:
            raise ContractError("INSUFFICIENT_CONTENT", "attributes/evidence")
        for proof in attribute["evidence"]:
            if proof["end"] <= proof["start"] or source[proof["start"]:proof["end"]] != proof["quote"]:
                raise ContractError("INSUFFICIENT_CONTENT", "attributes/evidence")


def validate_requirement_evidence(source: str, proof: dict) -> None:
    """Verify the quoted, version-identified source slice before it is retained."""
    evidence = proof.get("evidence") if isinstance(proof, dict) else None
    if not isinstance(evidence, dict):
        raise ContractError("INSUFFICIENT_CONTENT", "requirement/evidence")
    start, end, quote = evidence.get("start"), evidence.get("end"), evidence.get("quote")
    if (not isinstance(start, int) or not isinstance(end, int) or not isinstance(quote, str)
            or end <= start or source[start:end] != quote):
        raise ContractError("INSUFFICIENT_CONTENT", "requirement/evidence")


def validate_page(page: dict, *, after: int = 0) -> None:
    validate("sync-page", page)
    sequences = [item["sequence"] for item in page["items"]]
    if (sequences != sorted(set(sequences)) or any(
        n <= after or n > page["snapshot_high_watermark"] for n in sequences
    ) or page["has_more"] and (not sequences or page["next_cursor"] is None)
            or page["next_cursor"] is None):
        raise ContractError("CURSOR_INVALID")


def may_save_profile(*, account_state: str, current_generation: int,
                     job_generation: int, current_epoch: int, job_epoch: int) -> bool:
    """State-transition oracle; SQL CAS and cancellation are gates of 06/08."""
    return (account_state == "ACTIVE" and current_generation == job_generation
            and current_epoch == job_epoch)
