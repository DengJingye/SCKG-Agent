"""Release-bound semantic navigation, never an additional scientific approval.

An external model supplies entity identities and relation interpretations explicitly.
Exact claim membership and provenance are checked mechanically. Every read resolves
current evidence eligibility; this derived index grants no recommendation rights.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from itertools import combinations
import hashlib
import json
from typing import Literal

from pydantic import Field

from .contracts import Contract
from .knowledge import KnowledgeError, KnowledgeService
from .storage import canonical_json, content_hash, new_id, utcnow


EntityKind = Literal["method", "tool", "task", "modality", "data_type", "dataset", "metric", "organism", "technology", "concept", "workflow", "software_version", "benchmark", "experiment", "representation"]


class NavigationEntity(Contract):
    id: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z][A-Za-z0-9_.:-]*$")
    label: str = Field(min_length=1, max_length=240)
    kind: EntityKind
    aliases: list[str] = Field(default_factory=list, max_length=40)


class ClaimMembership(Contract):
    candidate_id: str = Field(min_length=1)
    entity_ids: list[str] = Field(default_factory=list, max_length=25)
    unassigned_reason: str | None = Field(default=None, max_length=2000)
    # Reading aid only: mentioning a task may describe a limitation or future work,
    # and does not establish that the method currently implements the task.
    scope_note: str | None = Field(default=None, max_length=2000)


class NavigationRelation(Contract):
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    predicate: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=240)
    candidate_ids: list[str] = Field(min_length=1, max_length=3000)
    rationale: str = Field(min_length=1, max_length=4000)
    kind: Literal["source_assertion", "navigation"]


class NavigationAnnotations(Contract):
    schema_version: Literal["semantic-navigation-v1"] = "semantic-navigation-v1"
    entities: list[NavigationEntity] = Field(default_factory=list, max_length=1000)
    memberships: list[ClaimMembership] = Field(min_length=1, max_length=3000)
    relations: list[NavigationRelation] = Field(default_factory=list, max_length=6000)


class NetworkService:
    MAX_CLAIMS = 3000

    def __init__(self, ledger):
        self.ledger = ledger
        self.knowledge = KnowledgeService(ledger)

    def prepare(self, *, profile_id, agent_id, instructions, expected_release_id=None):
        """Freeze every published claim before external semantic annotation."""
        if not isinstance(agent_id, str) or not agent_id.strip() or not isinstance(instructions, str) or not instructions.strip():
            raise KnowledgeError("Explicit agent identity and annotation instructions are required")
        release = self.knowledge.current_release()
        if not release or not release["units"]:
            raise KnowledgeError("A nonempty current published release is required")
        if expected_release_id is not None and expected_release_id != release["id"]:
            raise KnowledgeError("Release changed before network preparation")
        if len(release["units"]) > self.MAX_CLAIMS:
            raise KnowledgeError("Release exceeds bounded navigation preparation limit")
        ids = [row["candidate_id"] for row in release["units"]]
        package = self.knowledge.resolve(ids, purpose="explanation")
        if package.release_id != release["id"] or len(package.units) != len(ids):
            raise KnowledgeError("Every frozen published claim must currently be eligible for explanation")
        with self.ledger.transaction() as conn:
            if (self.ledger.get_state("current_release", conn=conn) != release["id"] or
                    self.ledger.get_state("governance_version", 0, conn=conn) != package.governance_version):
                raise KnowledgeError("Release or governance changed during network preparation")
            profile = self.knowledge._required("external_model_profile", profile_id, conn)
            claims = []
            units = {row["candidate_id"]: row for row in package.units}
            for manifest in release["units"]:
                cid = manifest["candidate_id"]
                candidate = self.knowledge._required("candidate", cid, conn)
                assessment = self.knowledge._required("assessment", manifest["assessment_id"], conn)
                claims.append({**manifest, "candidate_record_hash": content_hash(candidate),
                               "assessment_hash": content_hash(assessment),
                               "claim": units[cid]["claim"], "evidence": units[cid]["evidence"],
                               "assessment": units[cid]["assessment"],
                               "latest_review_id": self.ledger.get_state("review:" + cid, conn=conn)})
            snapshot = {"schema_version": "semantic-navigation-input-v1", "namespace": self.ledger.workspace.namespace,
                        "release_id": release["id"], "release_hash": content_hash(release),
                        "governance_version": package.governance_version, "claims": claims,
                        "instructions": instructions, "purpose": "derived_navigation_only"}
            run = {"id": new_id("network-run"), "input_snapshot": snapshot, "input_hash": content_hash(snapshot),
                   "external_profile_id": profile_id, "profile_snapshot": profile, "agent_id": agent_id,
                   "created_at": utcnow(), "usage_known": False, "usage": None, "cost_known": False,
                   "cost_usd": None, "provider_receipt_available": False}
            self.ledger.put_record("network_run", run["id"], run, conn=conn)
            self.ledger.append_event("network_annotation_prepared", run["id"],
                                     {"release_id": release["id"], "input_hash": run["input_hash"], "claim_count": len(claims)}, conn=conn)
        return run

    @staticmethod
    def _distinct(values, label):
        if len(values) != len(set(values)):
            raise KnowledgeError(f"Duplicate {label}")

    @staticmethod
    def _projection_integrity(projection):
        payload = {k: v for k, v in projection.items() if k != "projection_hash"}
        if (content_hash(payload) != projection.get("projection_hash") or
                content_hash(projection.get("annotations")) != projection.get("annotation_hash") or
                hashlib.sha256(projection.get("raw_json", "").encode()).hexdigest() != projection.get("raw_sha256")):
            raise KnowledgeError("Navigation projection hash mismatch")

    def import_annotations(self, run_id, output, *, expected_input_hash):
        """Import an explicit semantic map without changing claims or approvals."""
        if isinstance(output, str):
            if len(output.encode()) > 16_000_000:
                raise KnowledgeError("Annotation JSON exceeds the bounded import size")
            raw = output
            parsed = json.loads(raw)
        elif isinstance(output, dict):
            parsed = output
            raw = canonical_json(output)
            if len(raw.encode()) > 16_000_000:
                raise KnowledgeError("Annotation JSON exceeds the bounded import size")
        else:
            raise KnowledgeError("Annotations must be an explicit JSON object or text")
        value = NavigationAnnotations.model_validate(parsed).model_dump(mode="json")
        raw_sha = hashlib.sha256(raw.encode()).hexdigest()
        run = self.knowledge._required("network_run", run_id)
        snapshot = run["input_snapshot"]
        if expected_input_hash != run["input_hash"] or content_hash(snapshot) != expected_input_hash:
            raise KnowledgeError("Annotation output must bind the exact prepared input hash")
        ids = [c["candidate_id"] for c in snapshot["claims"]]
        package = self.knowledge.resolve(ids, purpose="explanation")
        with self.ledger.transaction() as conn:
            if snapshot["namespace"] != self.ledger.workspace.namespace:
                raise KnowledgeError("Navigation run belongs to a different namespace")
            profile = self.knowledge._required("external_model_profile", run["external_profile_id"], conn)
            if profile != run["profile_snapshot"]:
                raise KnowledgeError("External profile snapshot mismatch")
            current_release = self.ledger.get_state("current_release", conn=conn)
            if current_release != snapshot["release_id"] or package.release_id != current_release:
                raise KnowledgeError("Navigation annotation is stale for the current release")
            release = self.knowledge._required("release", current_release, conn)
            if content_hash(release) != snapshot["release_hash"]:
                raise KnowledgeError("Frozen release integrity mismatch")
            if (self.ledger.get_state("governance_version", 0, conn=conn) != snapshot["governance_version"] or
                    package.governance_version != snapshot["governance_version"] or len(package.units) != len(ids)):
                raise KnowledgeError("Evidence governance changed; prepare a fresh annotation run")
            for frozen in snapshot["claims"]:
                cid = frozen["candidate_id"]
                candidate = self.knowledge._required("candidate", cid, conn)
                assessment = self.knowledge._required("assessment", frozen["assessment_id"], conn)
                if (content_hash(candidate) != frozen["candidate_record_hash"] or
                        candidate["content_hash"] != frozen["candidate_hash"] or
                        content_hash(assessment) != frozen["assessment_hash"] or
                        self.ledger.get_state("review:" + cid, conn=conn) != frozen["latest_review_id"]):
                    raise KnowledgeError("Frozen claim, assessment or review changed")
            entities = {entity["id"]: entity for entity in value["entities"]}
            self._distinct([e["id"] for e in value["entities"]], "entity identities")
            if set(entities) & (set(ids) | {e["source_id"] for c in snapshot["claims"] for e in c["evidence"]}):
                raise KnowledgeError("Entity IDs must not impersonate claim or source IDs")
            for entity in value["entities"]:
                if not entity["label"].strip() or any(not alias.strip() or len(alias) > 240 for alias in entity["aliases"]):
                    raise KnowledgeError("Entity labels and aliases must be nonblank and bounded")
                self._distinct(entity["aliases"], "entity aliases")
            self._distinct([m["candidate_id"] for m in value["memberships"]], "claim memberships")
            memberships = {m["candidate_id"]: m for m in value["memberships"]}
            if set(memberships) != set(ids):
                raise KnowledgeError("Memberships must cover exactly every frozen published claim")
            assigned_entities = set()
            for member in value["memberships"]:
                self._distinct(member["entity_ids"], "membership entities")
                if not set(member["entity_ids"]) <= set(entities):
                    raise KnowledgeError("Membership references an unknown entity")
                if not member["entity_ids"] and not (member["unassigned_reason"] or "").strip():
                    raise KnowledgeError("Unassigned claims require an explicit reason")
                assigned_entities.update(member["entity_ids"])
            if set(entities) != assigned_entities:
                raise KnowledgeError("Every entity needs membership in at least one frozen claim")
            relation_digests = []
            for relation in value["relations"]:
                if (relation["source"] not in entities or relation["target"] not in entities or
                        relation["source"] == relation["target"]):
                    raise KnowledgeError("Relation endpoints must be distinct known entities")
                if any(not relation[k].strip() for k in ("predicate", "label", "rationale")):
                    raise KnowledgeError("Relation semantics and rationale must be explicit")
                self._distinct(relation["candidate_ids"], "relation evidence IDs")
                for cid in relation["candidate_ids"]:
                    if cid not in memberships or not {relation["source"], relation["target"]} <= set(memberships[cid]["entity_ids"]):
                        raise KnowledgeError("Each relation evidence claim must belong to the release and explicitly mention both endpoints")
                relation_digests.append(content_hash(relation))
            self._distinct(relation_digests, "identical semantic relations")
            projection_id = "network-projection-" + content_hash([run_id, content_hash(value)])
            prior_ref = self.ledger.get_state("network_output:" + run_id, conn=conn)
            if prior_ref:
                prior = self.knowledge._required("network_projection", prior_ref, conn)
                self._projection_integrity(prior)
                if prior["raw_sha256"] != raw_sha:
                    raise KnowledgeError("Run already has a different immutable annotation output")
                return prior
            projection = {"id": projection_id, "schema_version": "semantic-navigation-projection-v1",
                          "namespace": self.ledger.workspace.namespace, "release_id": current_release,
                          "release_hash": snapshot["release_hash"], "run_id": run_id,
                          "input_hash": expected_input_hash, "annotation_hash": content_hash(value),
                          "annotations": value, "raw_json": raw, "raw_sha256": raw_sha,
                          "external_profile_id": run["external_profile_id"], "profile_snapshot": profile,
                          "agent_id": run["agent_id"], "created_at": utcnow(),
                          "authority": "derived_navigation_pending_review", "grants_scientific_approval": False,
                          "usage_known": False, "usage": None, "cost_known": False, "cost_usd": None,
                          "provider_receipt_available": False}
            projection["projection_hash"] = content_hash(projection)
            self.ledger.put_record("network_projection", projection_id, projection, conn=conn)
            self.ledger.set_state("network_output:" + run_id, projection_id, conn=conn)
            self.ledger.set_state("network_projection:" + current_release, projection_id, conn=conn)
            self.ledger.set_state("latest_network_projection", projection_id, conn=conn)
            self.ledger.append_event("network_projection_imported", projection_id,
                                     {"release_id": current_release, "input_hash": expected_input_hash,
                                      "projection_hash": projection["projection_hash"], "entity_count": len(entities),
                                      "authority": projection["authority"]}, conn=conn)
        return projection

    def current(self):
        """Return immutable projection metadata for this release, not live eligibility.

        Consumers must use view() for eligible graph nodes and evidence.
        """
        with self.ledger.connect() as conn:
            rid = self.ledger.get_state("current_release", conn=conn)
            ref = self.ledger.get_state("network_projection:" + str(rid), conn=conn) if rid else None
            if not ref:
                return None
            projection = self.knowledge._required("network_projection", ref, conn)
            self._projection_integrity(projection)
            release = self.knowledge._required("release", rid, conn)
            if projection["release_id"] != rid or projection["release_hash"] != content_hash(release):
                raise KnowledgeError("Projection is not bound to the current release")
            return projection

    @staticmethod
    def _components(nodes, edges):
        adjacency = {node["id"]: set() for node in nodes}
        for edge in edges:
            if edge["source"] in adjacency and edge["target"] in adjacency:
                adjacency[edge["source"]].add(edge["target"])
                adjacency[edge["target"]].add(edge["source"])
        seen, sizes = set(), []
        for nid in adjacency:
            if nid in seen:
                continue
            queue, size = [nid], 0
            seen.add(nid)
            while queue:
                here = queue.pop()
                size += 1
                for neighbor in adjacency[here] - seen:
                    seen.add(neighbor)
                    queue.append(neighbor)
            sizes.append(size)
        return sorted(sizes, reverse=True)

    def view(self, *, query="", entity_id=None, hops=1, include_claims=False,
             include_sources=False, max_nodes=500, max_edges=2000):
        """Resolve all claims, then return a bounded semantic entity neighborhood.

        Shared claim co-occurrence is navigation, never compatibility, superiority,
        causal evidence, or another reviewed scientific assertion.
        """
        if (not isinstance(query, str) or len(query) > 2000 or type(hops) is not int or not 0 <= hops <= 2 or
                type(max_nodes) is not int or not 1 <= max_nodes <= 1500 or
                type(max_edges) is not int or not 1 <= max_edges <= 6000 or
                type(include_claims) is not bool or type(include_sources) is not bool or
                (entity_id is not None and (not isinstance(entity_id, str) or len(entity_id) > 160))):
            raise KnowledgeError("Invalid or unbounded navigation view request")
        # The shared resolver takes a consistent release/governance snapshot. Check
        # its identity once more after lookup; never mix a graph from another release.
        for attempt in range(2):
            projection = self.current()
            release = self.knowledge.current_release()
            if projection is None:
                return {"status": "missing_projection", "release_id": release["id"] if release else None,
                        "projection_id": None, "input_hash": None, "governance_version": self.ledger.get_state("governance_version", 0),
                        "nodes": [], "edges": [], "claims": [], "facets": {}, "stats": {},
                        "gaps": ["当前知识版本尚未建立语义导航索引。"], "provenance": None}
            ids = [m["candidate_id"] for m in projection["annotations"]["memberships"]]
            package = self.knowledge.resolve(ids, purpose="explanation")
            with self.ledger.connect() as conn:
                stable = (self.ledger.get_state("current_release", conn=conn) == package.release_id == projection["release_id"] and
                          self.ledger.get_state("governance_version", 0, conn=conn) == package.governance_version)
            if stable:
                break
        else:
            raise KnowledgeError("Knowledge changed during navigation lookup; retry")
        annotation = projection["annotations"]
        by_claim = {u["candidate_id"]: u for u in package.units}
        memberships = {m["candidate_id"]: m for m in annotation["memberships"] if m["candidate_id"] in by_claim}
        entity_claims = defaultdict(list)
        for cid, member in memberships.items():
            for eid in member["entity_ids"]:
                entity_claims[eid].append(cid)
        nodes = []
        for entity in annotation["entities"]:
            if entity["id"] not in entity_claims:
                continue
            cids = sorted(entity_claims[entity["id"]])
            sids = sorted({e["source_id"] for cid in cids for e in by_claim[cid]["evidence"]})
            nodes.append({**entity, "candidate_ids": cids, "claim_ids": cids, "source_ids": sids,
                          "governance": "derived_navigation_pending_review"})
        edges, explicit_pairs = [], set()
        for relation in annotation["relations"]:
            # All cited premises are required: do not retain a multi-premise
            # interpretation after one premise has been suspended or withdrawn.
            if not set(relation["candidate_ids"]) <= set(by_claim):
                continue
            edge = {**relation, "id": "relation-" + content_hash(relation),
                    "claim_ids": relation["candidate_ids"], "relation": relation["predicate"],
                    "governance": "derived_navigation_pending_review", "scientific_approval": False}
            edges.append(edge)
            explicit_pairs.add(frozenset((relation["source"], relation["target"])))
        co_mentions = defaultdict(list)
        for cid, member in memberships.items():
            for left, right in combinations(sorted(member["entity_ids"]), 2):
                if frozenset((left, right)) not in explicit_pairs:
                    co_mentions[(left, right)].append(cid)
        for (left, right), cids in sorted(co_mentions.items()):
            edges.append({"id": "co-mentioned-" + content_hash([left, right]), "source": left, "target": right,
                          "predicate": "co_mentioned", "relation": "co_mentioned", "label": "共同涉及",
                          "kind": "navigation", "candidate_ids": cids, "claim_ids": cids,
                          "rationale": "这些实体由模型关联到同一条知识，仅供导航，不代表可组合、兼容或优劣。",
                          "governance": "derived_navigation_pending_review", "scientific_approval": False})
        component_sizes = self._components(nodes, edges)
        facets = dict(Counter(n["kind"] for n in nodes))
        total_sources = {e["source_id"] for u in package.units for e in u["evidence"]}
        stats = {"total_entities": len(nodes), "total_claims": len(by_claim), "total_sources": len(total_sources),
                 "total_edges": len(edges), "connected_components": len(component_sizes), "component_sizes": component_sizes,
                 "excluded_claims": len(ids) - len(by_claim), "unassigned_claims": sum(not m["entity_ids"] for m in memberships.values())}
        node_map = {node["id"]: node for node in nodes}
        selected = set(node_map)
        if entity_id is not None or query.strip():
            needle = query.casefold().strip()
            selected = {entity_id} & set(node_map) if entity_id is not None else {
                node["id"] for node in nodes if any(needle in text.casefold() for text in [node["label"], *node["aliases"]])}
            if entity_id is None:
                for cid, unit in by_claim.items():
                    if needle in unit["claim"]["proposition"].casefold():
                        selected.update(memberships[cid]["entity_ids"])
            frontier = set(selected)
            adjacency = defaultdict(set)
            for edge in edges:
                adjacency[edge["source"]].add(edge["target"])
                adjacency[edge["target"]].add(edge["source"])
            for _ in range(hops):
                frontier = {neighbor for nid in frontier for neighbor in adjacency[nid]} - selected
                selected.update(frontier)
        selected_nodes = sorted((node_map[nid] for nid in selected), key=lambda n: (n["id"] != entity_id, n["kind"], n["label"], n["id"]))
        visible_nodes = selected_nodes[:max_nodes]
        visible_entity_ids = {node["id"] for node in visible_nodes}
        visible_claim_ids = {cid for eid in visible_entity_ids for cid in entity_claims[eid]}
        if not query.strip() and entity_id is None:
            visible_claim_ids.update(cid for cid, member in memberships.items() if not member["entity_ids"])
        visible_edges = [edge for edge in edges if edge["source"] in visible_entity_ids and edge["target"] in visible_entity_ids]
        if include_claims or include_sources:
            for cid in sorted(visible_claim_ids):
                if len(visible_nodes) >= max_nodes:
                    break
                unit = by_claim[cid]
                visible_nodes.append({"id": cid, "kind": "claim", "label": unit["claim"]["proposition"],
                                      "candidate_ids": [cid], "claim_ids": [cid]})
                for eid in memberships[cid]["entity_ids"]:
                    if eid in visible_entity_ids:
                        visible_edges.append({"id": "membership-" + content_hash([cid, eid]), "source": eid, "target": cid,
                                              "predicate": "mentions", "relation": "mentions", "label": "涉及",
                                              "kind": "membership", "candidate_ids": [cid], "claim_ids": [cid],
                                              "governance": "derived_navigation_pending_review"})
            if include_sources:
                represented = {n["id"] for n in visible_nodes}
                for cid in sorted(visible_claim_ids & represented):
                    for evidence in by_claim[cid]["evidence"]:
                        sid = evidence["source_id"]
                        if sid not in represented:
                            if len(visible_nodes) >= max_nodes:
                                continue
                            source = self.knowledge._required("source", sid)
                            visible_nodes.append({"id": sid, "kind": "source", "label": source.get("metadata", {}).get("title") or evidence["filename"],
                                                  "candidate_ids": [], "claim_ids": []})
                            represented.add(sid)
                        edge_id = "citation-" + content_hash([sid, cid])
                        if not any(edge["id"] == edge_id for edge in visible_edges):
                            visible_edges.append({"id": edge_id, "source": sid, "target": cid, "predicate": "cites",
                                                  "relation": "cites", "label": "原文依据", "kind": "citation",
                                                  "candidate_ids": [cid], "claim_ids": [cid], "governance": "original_claim_evidence"})
        represented_ids = {node["id"] for node in visible_nodes}
        omitted_evidence_nodes = bool((include_claims or include_sources) and not visible_claim_ids <= represented_ids)
        if include_sources:
            expected_sources = {e["source_id"] for cid in visible_claim_ids for e in by_claim[cid]["evidence"]}
            omitted_evidence_nodes = omitted_evidence_nodes or not expected_sources <= represented_ids
        truncated = len(selected_nodes) > len(visible_entity_ids) or len(visible_edges) > max_edges or omitted_evidence_nodes
        visible_edges = visible_edges[:max_edges]
        stats.update({"visible_nodes": len(visible_nodes), "visible_edges": len(visible_edges), "visible_claims": len(visible_claim_ids),
                      "truncated": truncated, "visible_components": len(self._components(visible_nodes, visible_edges))})
        claims = [{**by_claim[cid], "entity_ids": memberships[cid]["entity_ids"],
                   "unassigned_reason": memberships[cid]["unassigned_reason"],
                   "navigation_scope_note": memberships[cid].get("scope_note")} for cid in sorted(visible_claim_ids)]
        gaps = list(package.gaps)
        if truncated:
            gaps.append("当前视图已按显示上限裁剪；全库统计使用完整可用索引。可选实体查看局部关系。")
        return {"status": "ready", "release_id": package.release_id, "governance_version": package.governance_version,
                "projection_id": projection["id"], "input_hash": projection["input_hash"],
                "projection_hash": projection["projection_hash"], "nodes": visible_nodes, "edges": visible_edges,
                "claims": claims, "facets": facets, "stats": stats, "gaps": gaps,
                "provenance": {"authority": projection["authority"], "scientific_approval": False,
                               "external_profile_id": projection["external_profile_id"], "profile": projection["profile_snapshot"],
                               "created_at": projection["created_at"], "agent_id": projection["agent_id"],
                               "cost_usd": None, "usage": None}}
