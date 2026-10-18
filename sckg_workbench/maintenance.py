"""Read-only impact tracing for a source or candidate maintenance decision.

Exposure in a chat context is recorded separately from a verified citation:
the model may have ignored, paraphrased, or misused the supplied evidence.
"""
from __future__ import annotations

from .storage import content_hash


class MaintenanceError(ValueError):
    pass


class MaintenanceService:
    def __init__(self, ledger):
        self.ledger = ledger

    def impact_report(self, kind: str, record_id: str) -> dict:
        if kind not in {"source", "candidate"} or not isinstance(record_id, str) or not record_id.strip():
            raise MaintenanceError("Choose one registered source or candidate")
        with self.ledger.connect() as conn:
            conn.execute("BEGIN")
            target = self.ledger.get_record(kind, record_id, conn=conn)
            if target is None:
                raise MaintenanceError("Unknown maintenance target")
            release_id = self.ledger.get_state("current_release", conn=conn)
            release = self.ledger.get_record("release", release_id, conn=conn) if release_id else None
            governance = self.ledger.get_state("governance_version", 0, conn=conn)
            manifests = (release or {}).get("units", [])
            if kind == "source":
                current_ids = [unit["candidate_id"] for unit in manifests
                               if record_id in self.ledger.get_record("candidate", unit["candidate_id"], conn=conn)["source_ids"]]
            else:
                current_ids = [record_id] if any(u["candidate_id"] == record_id for u in manifests) else []

            exposed_turns = []
            for request in self.ledger.list_records("chat_request", conn=conn):
                context = self.ledger.get_record("chat_context", request["id"], conn=conn)
                if not context:
                    continue
                matching_ids = set()
                for package in context.get("evidence_packages", []):
                    for unit in package.get("units", []):
                        if kind == "candidate" and unit.get("candidate_id") == record_id:
                            matching_ids.add(record_id)
                        elif kind == "source" and any(e.get("source_id") == record_id for e in unit.get("evidence", [])):
                            matching_ids.add(unit["candidate_id"])
                if matching_ids:
                    result = self.ledger.get_record("chat_result", request["id"], conn=conn) or {}
                    exposed_turns.append({"turn_id": request["id"], "conversation_id": request["conversation_id"],
                                          "sequence": request["sequence"], "stored_status": result.get("status", request["status"]),
                                          "candidate_ids": sorted(matching_ids), "relationship": "context_exposed_not_verified_citation"})
            report = {"schema_version": "maintenance-impact-v1", "namespace": self.ledger.workspace.namespace,
                      "target_kind": kind, "target_id": record_id, "release_id": release_id,
                      "governance_version": governance, "current_release_candidate_ids": sorted(current_ids),
                      "exposed_chat_turns": exposed_turns,
                      "interpretation": "Potential impact only; revalidate evidence and rerun affected questions after repair."}
            report["snapshot_hash"] = content_hash(report)
            return report
