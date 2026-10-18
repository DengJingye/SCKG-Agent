"""Provisional identities and proposed relationships, not scientific conclusions.

Labels, attributes and relationships are assertions awaiting identity review.
Neither matching labels nor a ``same_as`` link merges records. A proposed
``independent_of`` link does not establish evidence independence. Work, study,
experiment, observation and software identities remain distinct; a tool profile
must be derived from these records and their later reviewed evidence, never from
an authoritative tool-summary field maintained by this service.
"""
from __future__ import annotations

import json
from typing import Any

from .storage import Ledger, canonical_json, new_id, utcnow


IDENTITY_KINDS = frozenset({"method", "project", "software_version", "work", "work_revision",
                            "study", "experiment", "observation", "concept"})
REFERENCE_KINDS = IDENTITY_KINDS | {"source", "candidate", "assessment", "review"}
_PARENTS = {"software_version": ("parent_id", "project"), "work_revision": ("parent_id", "work"),
            "experiment": ("study_id", "study"), "observation": ("experiment_id", "experiment")}
_RESERVED_ATTRIBUTES = frozenset({
    "id", "identity_id", "namespace", "kind", "status", "trust_status", "review_status",
    "approved", "is_approved", "is_trusted", "canonical_id", "merged_into", "authoritative",
    "authoritative_summary", "canonical_summary", "trusted_summary", "tool_summary",
})


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _attributes(value: Any) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("attributes must be a JSON object")

    def validate(item):
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str):
                    raise ValueError("attribute keys must be strings")
                normalized = key.strip().casefold().replace("-", "_").replace(" ", "_")
                if normalized in _RESERVED_ATTRIBUTES or "summary" in normalized:
                    raise ValueError("identity attributes cannot override governance or contain authoritative summaries")
                validate(child)
        elif isinstance(item, list):
            for child in item:
                validate(child)

    validate(value)
    try:
        return json.loads(canonical_json(value))
    except (TypeError, ValueError) as exc:
        raise ValueError("attributes must contain finite JSON data") from exc


class IdentityService:
    """One namespace-local ledger; every identity is provisional, every link proposed.

    Versions require ``attributes.parent_id`` and ``attributes.version``. An
    experiment requires ``attributes.study_id``; an observation requires
    ``attributes.experiment_id``. Work revisions need at least one registered
    source in provenance_ids. Unknown semantic categories fit a concept identity
    with descriptive ``proposed_type``/``definition`` attributes; they are not
    silently mapped to a known scientific type.
    """

    def __init__(self, ledger: Ledger):
        self.ledger = ledger
        self.namespace = ledger.workspace.namespace

    def _reference(self, kind: str, identifier: str, *, conn) -> dict:
        if not isinstance(kind, str) or kind not in REFERENCE_KINDS:
            raise ValueError("unsupported reference kind")
        identifier = _text(identifier, "reference id")
        storage_kind = "identity" if kind in IDENTITY_KINDS else kind
        record = self.ledger.get_record(storage_kind, identifier, conn=conn)
        if record is None:
            raise ValueError(f"{kind} reference does not exist in this workspace")
        if record.get("id") != identifier:
            raise ValueError("reference identity is inconsistent")
        if kind in IDENTITY_KINDS and record.get("kind") != kind:
            raise ValueError("reference kind does not match the stored identity")
        namespace = record.get("namespace") if kind in IDENTITY_KINDS else record.get("namespace", self.namespace)
        if namespace != self.namespace:
            raise ValueError("reference belongs to a different namespace")
        return record

    def create(self, kind: str, label: str, attributes: dict | None = None,
               provenance_ids: list[str] | None = None) -> dict:
        if not isinstance(kind, str) or kind not in IDENTITY_KINDS:
            raise ValueError("unsupported identity kind; use concept for a proposed semantic type")
        label, attributes = _text(label, "label"), _attributes(attributes)
        if provenance_ids is None:
            provenance_ids = []
        if not isinstance(provenance_ids, list):
            raise ValueError("provenance_ids must be a list of registered source IDs")
        provenance = list(dict.fromkeys(_text(identifier, "provenance id") for identifier in provenance_ids))
        if kind in {"software_version", "work_revision"}:
            attributes["version"] = _text(attributes.get("version"), "version")
        if kind == "work_revision" and not provenance:
            raise ValueError("work_revision requires at least one registered source carrier")
        with self.ledger.transaction() as conn:
            for identifier in provenance:
                self._reference("source", identifier, conn=conn)
            if kind in _PARENTS:
                field, parent_kind = _PARENTS[kind]
                parent_id = _text(attributes.get(field), field)
                self._reference(parent_kind, parent_id, conn=conn)
                attributes[field] = parent_id
            record = {"id": new_id(kind), "namespace": self.namespace, "kind": kind,
                      "label": label, "attributes": attributes, "provenance_ids": provenance,
                      "status": "provisional", "created_at": utcnow()}
            self.ledger.put_record("identity", record["id"], record, conn=conn)
            self.ledger.append_event("identity_created", record["id"],
                                     {"kind": kind, "status": "provisional"}, conn=conn)
            return record

    def link(self, left_kind: str, left_id: str, relation: str, right_kind: str,
             right_id: str, *, rationale: str, actor: str | None = None) -> dict:
        relation, rationale = _text(relation, "relation"), _text(rationale, "rationale")
        left_id, right_id = _text(left_id, "left_id"), _text(right_id, "right_id")
        if actor is not None:
            actor = _text(actor, "actor")
        with self.ledger.transaction() as conn:
            self._reference(left_kind, left_id, conn=conn)
            self._reference(right_kind, right_id, conn=conn)
            record = {"id": new_id("identity-link"), "namespace": self.namespace,
                      "left_kind": left_kind, "left_id": left_id, "relation": relation,
                      "right_kind": right_kind, "right_id": right_id,
                      "rationale": rationale, "actor": actor, "status": "proposed",
                      "created_at": utcnow()}
            self.ledger.put_record("identity_link", record["id"], record, conn=conn)
            self.ledger.append_event("identity_link_proposed", record["id"],
                                     {"left_id": left_id, "right_id": right_id, "relation": relation}, conn=conn)
            return record

    def list(self, kind: str | None = None) -> list[dict]:
        if kind is not None and (not isinstance(kind, str) or kind not in IDENTITY_KINDS):
            raise ValueError("unsupported identity kind")
        rows = self.ledger.list_records("identity")
        return [row for row in rows if row["namespace"] == self.namespace and (kind is None or row["kind"] == kind)]

    def list_links(self) -> list[dict]:
        return [row for row in self.ledger.list_records("identity_link") if row["namespace"] == self.namespace]
