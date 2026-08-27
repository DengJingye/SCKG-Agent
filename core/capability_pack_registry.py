from __future__ import annotations

import hashlib
import json
from pathlib import Path

from core.capability_pack_models import (
    CapabilityDiscoveryRecord,
    CapabilityPackGateResult,
    CapabilityPackManifest,
    CapabilityReadiness,
)
from core.settings import PROJECT_ROOT


DEFAULT_CAPABILITY_PACK_ROOT = PROJECT_ROOT / "capability_packs"


class CapabilityPackRegistry:
    """Load immutable capability manifests and evaluate static readiness gates."""

    def __init__(self, root: Path = DEFAULT_CAPABILITY_PACK_ROOT) -> None:
        self.root = Path(root)

    def load(self, pack_id: str, pack_version: str) -> CapabilityPackManifest:
        path = self.root / pack_id / pack_version / "manifest.json"
        if not path.is_file():
            raise KeyError(f"capability pack is not registered: {pack_id}:{pack_version}")
        manifest = CapabilityPackManifest.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        if (manifest.pack_id, manifest.pack_version) != (pack_id, pack_version):
            raise ValueError("capability pack path and manifest identity differ")
        return manifest

    def load_all(self) -> list[CapabilityPackManifest]:
        if not self.root.exists():
            return []
        manifests: list[CapabilityPackManifest] = []
        for path in sorted(self.root.glob("*/*/manifest.json")):
            manifests.append(
                CapabilityPackManifest.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
            )
        return manifests

    def gate(self, manifest: CapabilityPackManifest) -> CapabilityPackGateResult:
        blockers: list[str] = []
        warnings: list[str] = []
        digest_valid = manifest.content_digest == manifest_digest(manifest)
        if not digest_valid:
            blockers.append("capability_pack_digest_mismatch")

        capability_ids = {item.capability_id for item in manifest.capabilities}
        representation_ids = {
            item.representation_id for item in manifest.representation_contracts
        }
        for target in manifest.workspace_targets:
            if target not in representation_ids:
                blockers.append(f"unknown_workspace_target:{target}")
        evidence_ids = {item.evidence_id for item in manifest.evidence_bindings}
        gold_ids = {item.case_id for item in manifest.gold_case_bindings}
        adapter_ids = {item.adapter_id for item in manifest.execution_adapters}
        renderer_ids = {item.renderer_id for item in manifest.notebook_renderers}
        step_refs: set[str] = set()

        for method in manifest.methods:
            if method.capability_id not in capability_ids:
                blockers.append(f"unknown_capability:{method.method_id}")
            for requirement in method.consumes:
                if requirement.representation_id not in representation_ids:
                    blockers.append(
                        f"unknown_consumed_representation:{method.method_id}:"
                        f"{requirement.representation_id}"
                    )
            for production in method.produces:
                if production.representation_id not in representation_ids:
                    blockers.append(
                        f"unknown_produced_representation:{method.method_id}:"
                        f"{production.representation_id}"
                    )
            for evidence_id in method.evidence_ids:
                if evidence_id not in evidence_ids:
                    blockers.append(f"unknown_evidence:{method.method_id}:{evidence_id}")
            for case_id in method.gold_case_ids:
                if case_id not in gold_ids:
                    blockers.append(f"unknown_gold_case:{method.method_id}:{case_id}")
            if method.execution_adapter_id and method.execution_adapter_id not in adapter_ids:
                blockers.append(f"unknown_adapter:{method.method_id}")
            if method.notebook_renderer_id and method.notebook_renderer_id not in renderer_ids:
                blockers.append(f"unknown_renderer:{method.method_id}")
            step_path = self.root / manifest.pack_id / manifest.pack_version / method.step_contract_ref
            if not step_path.is_file():
                blockers.append(f"missing_step_contract:{method.method_id}")
            else:
                step_refs.add(method.step_contract_ref)

        method_ids = {item.method_id for item in manifest.methods}
        for binding in manifest.composed_actions:
            unknown_methods = sorted(set(binding.method_ids) - method_ids)
            blockers.extend(
                f"unknown_composed_method:{binding.binding_id}:{method_id}"
                for method_id in unknown_methods
            )
        for binding in manifest.implementation_bindings:
            if binding.method_id not in method_ids:
                blockers.append(
                    f"unknown_implementation_method:{binding.binding_id}:"
                    f"{binding.method_id}"
                )
            for evidence_id in binding.evidence_ids:
                if evidence_id not in evidence_ids:
                    blockers.append(
                        f"unknown_implementation_evidence:{binding.binding_id}:"
                        f"{evidence_id}"
                    )
            if binding.execution_eligible and binding.status != "qualified":
                blockers.append(
                    f"unqualified_implementation_execution_claim:{binding.binding_id}"
                )

        reviewed_evidence = {
            item.evidence_id
            for item in manifest.evidence_bindings
            if item.review_status == "reviewed"
        }
        missing_review = sorted(
            method.method_id
            for method in manifest.methods
            if not method.evidence_ids
            or not set(method.evidence_ids) <= reviewed_evidence
        )
        if missing_review:
            warnings.extend(f"evidence_review_incomplete:{item}" for item in missing_review)

        readiness = [CapabilityReadiness.DISCOVERED]
        static_valid = digest_valid and not blockers
        if static_valid and not missing_review:
            readiness.append(CapabilityReadiness.PLANNING_READY)
        if (
            CapabilityReadiness.PLANNING_READY in readiness
            and all(item.maintainer_reviewed for item in manifest.notebook_renderers)
        ):
            readiness.append(CapabilityReadiness.NOTEBOOK_READY)
        if (
            CapabilityReadiness.NOTEBOOK_READY in readiness
            and all(
                method.validation_pipeline.generic_primitives
                and method.validation_pipeline.scientific_validator_id
                for method in manifest.methods
            )
        ):
            readiness.append(CapabilityReadiness.VALIDATION_READY)

        qualification_claimed = manifest.status == "qualified"
        if qualification_claimed:
            allowed_adapters = all(item.allowlisted for item in manifest.execution_adapters)
            if CapabilityReadiness.VALIDATION_READY in readiness and allowed_adapters:
                readiness.append(CapabilityReadiness.QUALIFICATION_PASSED)
            else:
                blockers.append("qualification_claim_without_complete_gates")
        execution_eligible = (
            CapabilityReadiness.QUALIFICATION_PASSED in readiness
            and all(item.allowlisted for item in manifest.execution_adapters)
        )
        if execution_eligible:
            readiness.append(CapabilityReadiness.EXECUTION_ELIGIBLE)
        return CapabilityPackGateResult(
            pack_id=manifest.pack_id,
            pack_version=manifest.pack_version,
            readiness=readiness,
            passed=static_valid,
            blockers=sorted(set(blockers)),
            warnings=sorted(set(warnings)),
            content_digest_valid=digest_valid,
            execution_eligible=execution_eligible,
            qualification_claimed=qualification_claimed,
        )

    def discover(self, *, capability_id: str | None = None) -> list[CapabilityDiscoveryRecord]:
        records: list[CapabilityDiscoveryRecord] = []
        for manifest in self.load_all():
            gate = self.gate(manifest)
            for capability in manifest.capabilities:
                if capability_id and capability.capability_id != capability_id:
                    continue
                records.append(
                    CapabilityDiscoveryRecord(
                        pack_id=manifest.pack_id,
                        pack_version=manifest.pack_version,
                        capability_id=capability.capability_id,
                        method_ids=[
                            item.method_id
                            for item in manifest.methods
                            if item.capability_id == capability.capability_id
                        ],
                        readiness=gate.readiness,
                        execution_eligible=gate.execution_eligible,
                        blockers=gate.blockers + gate.warnings,
                    )
                )
        return records

    def load_step_contracts(
        self, manifest: CapabilityPackManifest
    ) -> dict[str, "StepContract"]:
        from core.research_workspace_models import StepContract

        contracts: dict[str, StepContract] = {}
        loaded_paths: dict[str, object] = {}
        for method in manifest.methods:
            if method.step_contract_ref not in loaded_paths:
                path = self.root / manifest.pack_id / manifest.pack_version / method.step_contract_ref
                payload = json.loads(path.read_text(encoding="utf-8"))
                loaded_paths[method.step_contract_ref] = payload
            payload = loaded_paths[method.step_contract_ref]
            candidates = payload if isinstance(payload, list) else [payload]
            for item in candidates:
                contract = StepContract.model_validate(item)
                contracts[contract.method_id] = contract
        missing = sorted({item.method_id for item in manifest.methods} - set(contracts))
        if missing:
            raise ValueError("step contracts missing methods: " + ", ".join(missing))
        return contracts


def manifest_digest(manifest: CapabilityPackManifest) -> str:
    payload = manifest.model_dump(mode="json")
    payload["content_digest"] = ""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
