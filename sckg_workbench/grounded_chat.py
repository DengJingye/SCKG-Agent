"""Bounded composition of the existing planner, selector and cited answer.

No new model client, queue, semantic audit, repair, fit or automatic retry.
Conversation text is untrusted context, never an independently measured fact.
"""
from __future__ import annotations

from copy import deepcopy
import json
import math

from .contracts import EvidencePackage
from .evidence_answers import generate_evidence_answer
from .evidence_selection import (select_evidence_for_checks, MAX_CARD_CANDIDATES,
    MAX_CANDIDATE_BYTES, MAX_CONTEXT_BYTES, MAX_SELECTION_INPUT_TOKENS,
    MAX_SELECTION_OUTPUT_TOKENS)
from .knowledge import KnowledgeService
from .retrieval_planning import (plan_evidence_queries, retrieve_planned_evidence,
    MAX_PROFILE_BYTES, MAX_QUERY_INPUT_TOKENS, MAX_QUERY_OUTPUT_TOKENS,
    EvidenceSnapshotChanged)
from .storage import content_hash


MAX_MODEL_CALLS = 3
STAGE_CAPS = {
    "planner": {"max_input_tokens": MAX_QUERY_INPUT_TOKENS, "max_output_tokens": MAX_QUERY_OUTPUT_TOKENS},
    "selector": {"max_input_tokens": MAX_SELECTION_INPUT_TOKENS, "max_output_tokens": MAX_SELECTION_OUTPUT_TOKENS},
    "answer": {"max_input_tokens": 16000, "max_output_tokens": 1024},
}


class GroundedChatError(ValueError):
    pass


def _inputs(question, history, budget):
    if not isinstance(question, str) or not question.strip() or len(question) > 8000:
        raise GroundedChatError("invalid_question")
    if not isinstance(history, list) or len(history) % 2:
        raise GroundedChatError("invalid_whole_turn_history")
    for index, message in enumerate(history):
        if (not isinstance(message, dict) or set(message) != {"role", "content"}
                or message["role"] != ("user" if index % 2 == 0 else "assistant")
                or not isinstance(message["content"], str) or not message["content"].strip()):
            raise GroundedChatError("invalid_whole_turn_history")
    profile = {"untrusted_conversation_context": deepcopy(history), "unknowns": []}
    encoded = json.dumps(profile, ensure_ascii=False, allow_nan=False)
    if len(encoded.encode("utf-8")) > MAX_PROFILE_BYTES:
        raise GroundedChatError("history_profile_exceeds_12000_bytes")
    allowed = {"max_input_tokens", "max_output_tokens", "timeout_seconds", "max_cost_usd", "allow_unknown_cost"}
    if not isinstance(budget, dict) or set(budget) - allowed:
        raise GroundedChatError("invalid_budget")
    for key in ("max_input_tokens", "max_output_tokens"):
        if type(budget.get(key)) is not int or not 1 <= budget[key] <= 2_000_000:
            raise GroundedChatError("invalid_budget")
    timeout = budget.get("timeout_seconds")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 600:
        raise GroundedChatError("invalid_budget")
    cost = budget.get("max_cost_usd")
    if cost is not None and (isinstance(cost, bool) or not isinstance(cost, (int, float)) or not math.isfinite(cost) or cost <= 0):
        raise GroundedChatError("invalid_budget")
    if "allow_unknown_cost" in budget and type(budget["allow_unknown_cost"]) is not bool:
        raise GroundedChatError("invalid_budget")
    return profile, deepcopy(budget)


def _markdown(run):
    """Render validated structure; reference labels come from its server manifest."""
    answer = run["answer"]
    aliases = {row["candidate_id"]: row["alias"] for row in run["alias_manifest"]["bindings"]}
    parts = []
    if answer.get("derived_reported_premises"):
        parts.append("已提供的前提（模型从用户文本提取，尚未独立测量核验）：")
        for premise in answer["derived_reported_premises"]:
            parts.append(f"{premise['premise_id']}：{premise['quote']}")
    scope = answer.get("decision_scope")
    if isinstance(scope, dict):
        core = [row["question"] for row in scope.get("checks", []) if row.get("role") == "core"]
        if core:
            parts.append("本次优先核对的问题（模型划分，未独立验证覆盖范围）：" + "；".join(core))
        else:
            parts.append("模型未声明核心问题范围；不能据此认定问题已完整回答。")
    parts.append(answer["decision"])
    for index, step in enumerate(answer["steps"], 1):
        citations = " ".join("[" + aliases[cid] + "]" for cid in step["evidence_ids"])
        text = " ".join(x for x in (step["factual_claim"], citations, step["instruction"]) if x)
        parts.append(f"{index}. {text}")
        if step["preconditions"]:
            parts.append("前提：" + "；".join(step["preconditions"]))
    if "typed_missing" in answer:
        labels = {"not_supplied": "尚未提供的输入", "independent_verification_missing": "用户报告尚未独立核验",
                  "source_evidence_missing": "仍缺来源依据"}
        for item in answer["typed_missing"]:
            parts.append(labels[item["kind"]] + "：" + item["text"])
    elif answer["missing"]:
        parts.append("仍缺少：" + "；".join(answer["missing"]))
    return "\n\n".join(parts)


def run_grounded_chat(ledger, models, *, question, history, profile_id, purpose,
                      budget, passphrase):
    """Use one explicit chat profile for at most three existing model calls."""
    receipts, trace, stage_budgets = [], [], {}
    entered_stages, uncertain_stages = [], []
    plan = retrieval = selection = answer_run = evidence_package = None
    history_used = []
    total_tokens, total_cost, cost_known = 0, 0.0, True
    token_cap, selected_budget, stage = 0, {}, "preflight"

    def output(status, *, reason=None):
        normalized = deepcopy(answer_run["answer"]) if status == "succeeded" else None
        return {"status": status, "answer": _markdown(answer_run) if normalized is not None else None,
            "normalized_answer": normalized, "receipt": deepcopy(receipts[-1]) if receipts else None,
            "receipts": deepcopy(receipts), "stage_trace": deepcopy(trace),
            "agent_budget": {"max_model_calls": MAX_MODEL_CALLS, "model_calls": len(receipts),
                "actual_receipted_call_count": len(receipts), "actual_call_count_lower": len(receipts),
                "actual_call_count_upper": len(receipts) + len(uncertain_stages),
                "dispatch_unknown": bool(uncertain_stages), "uncertain_stages": list(uncertain_stages),
                "stage_function_attempts": len(entered_stages),
                "per_request_ceiling": deepcopy(selected_budget), "stage_caps": deepcopy(STAGE_CAPS),
                "stage_budgets": deepcopy(stage_budgets), "max_total_token_reservation": token_cap,
                "charged_or_reserved_tokens": total_tokens, "cost_known": cost_known,
                "cost_usd": total_cost if cost_known else None, "max_cost_usd": selected_budget.get("max_cost_usd"),
                "timeout_seconds_per_stage": min(selected_budget.get("timeout_seconds", 60), 60),
                "selection_limits": {"candidate_limit": MAX_CARD_CANDIDATES, "candidate_budget_utf8_bytes": MAX_CANDIDATE_BYTES,
                    "context_budget_utf8_bytes": MAX_CONTEXT_BYTES, "per_query_limit": 20, "candidate_mode": "scoped_required_entries"}},
            "plan": deepcopy(plan), "retrieval": deepcopy(retrieval), "selection": deepcopy(selection),
            "answer_run": deepcopy(answer_run), "evidence_package": deepcopy(evidence_package),
            "required_evidence": deepcopy((selection or {}).get("required_evidence")),
            "decision_scope": deepcopy((selection or {}).get("decision_scope")),
            "citation_manifest": deepcopy(answer_run["alias_manifest"]) if answer_run else None,
            "history_used": deepcopy(history_used), "history_omitted_by_grounded_chat": 0,
            "semantic_support": "not_assessed", "scientific_facts_verified": False,
            "execution_status": "not_run", "auto_retry": False,
            "error": None if reason is None else {"type": "GroundedChatStopped", "reason_code": reason,
                "stage": stage, "message": "本轮有来源问答已停止；未补调用、未评定科学正确性。"}}

    def call_budget(name):
        if len(receipts) >= MAX_MODEL_CALLS:
            raise GroundedChatError("model_call_limit")
        cap = STAGE_CAPS[name]
        value = {**selected_budget,
            "max_input_tokens": min(selected_budget["max_input_tokens"], cap["max_input_tokens"]),
            "max_output_tokens": min(selected_budget["max_output_tokens"], cap["max_output_tokens"]),
            "timeout_seconds": min(selected_budget["timeout_seconds"], 60)}
        if selected_budget.get("max_cost_usd") is not None:
            if not cost_known:
                raise GroundedChatError("cost_unknown_with_monetary_cap")
            remaining = selected_budget["max_cost_usd"] - total_cost
            if remaining <= 0:
                raise GroundedChatError("cost_cap_exhausted")
            value["max_cost_usd"] = remaining
        if total_tokens + value["max_input_tokens"] + value["max_output_tokens"] > token_cap:
            raise GroundedChatError("cumulative_token_cap")
        stage_budgets[name] = deepcopy(value)
        return value

    def record(receipt, name):
        nonlocal total_tokens, total_cost, cost_known
        if not isinstance(receipt, dict) or not receipt.get("call_id"):
            return
        if any(r["call_id"] == receipt["call_id"] for r in receipts):
            return
        receipts.append(deepcopy(receipt))
        usage = receipt.get("usage") or {}
        counts = [usage.get("input_tokens"), usage.get("output_tokens")]
        reserved = sum(stage_budgets[name][k] for k in ("max_input_tokens", "max_output_tokens"))
        total_tokens += sum(counts) if all(type(v) is int and v >= 0 for v in counts) else reserved
        cost = receipt.get("cost_usd")
        if (receipt.get("cost_known") is True and not isinstance(cost, bool)
                and isinstance(cost, (int, float)) and math.isfinite(cost) and cost >= 0):
            total_cost += cost
        else:
            cost_known = False
        trace.append({"stage": name, "call_id": receipt["call_id"], "status": receipt.get("status"),
                      "receipt_index": len(receipts) - 1, "budget": deepcopy(stage_budgets[name])})

    try:
        dataset_profile, selected_budget = _inputs(question, history, budget)
        history_used = deepcopy(history)
        token_cap = MAX_MODEL_CALLS * (selected_budget["max_input_tokens"] + selected_budget["max_output_tokens"])
        if purpose not in {"explanation", "recommendation"}:
            raise GroundedChatError("invalid_purpose")
        if (models.workspace.namespace != ledger.workspace.namespace
                or models.ledger.workspace.namespace != ledger.workspace.namespace):
            raise GroundedChatError("model_workspace_mismatch")
        profile = ledger.get_record("model_profile", profile_id) if isinstance(profile_id, str) else None
        if not profile or profile.get("purpose") != "chat":
            raise GroundedChatError("explicit_chat_profile_required")
        price_known = all(profile.get(k) is not None for k in ("input_usd_per_million", "output_usd_per_million"))
        if selected_budget.get("max_cost_usd") is not None and not price_known:
            raise GroundedChatError("pricing_unknown_with_monetary_cap")
        if not price_known and selected_budget.get("allow_unknown_cost") is not True:
            raise GroundedChatError("unknown_cost_not_authorized")
        knowledge = KnowledgeService(ledger)
        baseline = knowledge.resolve([], purpose=purpose)
        if baseline.release_id is None:
            evidence_package = baseline.model_dump(mode="json")
            return output("blocked", reason="no_published_evidence")
        stage = "planner"
        bounded = call_budget(stage)
        entered_stages.append(stage)
        plan = plan_evidence_queries(models, question, dataset_profile, profile_id=profile_id,
            budget=bounded, outbound_authorized=True, passphrase=passphrase)
        record(plan["call_receipt"], stage)
        stage = "retrieval"
        retrieval = retrieve_planned_evidence(knowledge, plan, purpose=purpose, per_query_limit=20,
            context_budget_bytes=MAX_CONTEXT_BYTES)
        if not retrieval["retrieved_units"]:
            evidence_package = EvidencePackage(**{k: retrieval[k] for k in
                ("namespace", "release_id", "governance_version", "purpose", "units", "gaps")},
                retrieval={"method": "planned_no_evidence", "absence_is_not_impossibility": True}).model_dump(mode="json")
            return output("blocked", reason="no_retrieved_evidence")
        stage = "selector"
        bounded = call_budget(stage)
        entered_stages.append(stage)
        selection = select_evidence_for_checks(models, knowledge, retrieval, profile_id=profile_id,
            budget=bounded, outbound_authorized=True, passphrase=passphrase,
            context_budget_bytes=MAX_CONTEXT_BYTES, candidate_budget_bytes=MAX_CANDIDATE_BYTES,
            candidate_limit=MAX_CARD_CANDIDATES, candidate_mode="scoped_required_entries")
        record(selection["selection_run"]["call_receipt"], stage)
        evidence_package = EvidencePackage(**{k: selection[k] for k in
            ("namespace", "release_id", "governance_version", "purpose", "units", "gaps")},
            retrieval={"method": "planned+selected", "semantic_support": "not_assessed"}).model_dump(mode="json")
        if selection["required_evidence"]["status"] == "missing":
            # This is a deterministic pre-answer stop, not an uncertain model
            # dispatch: optional mechanism evidence cannot replace the declared
            # necessary source units when the complete set exceeds the budget.
            return output("blocked", reason="required_final_evidence_missing")
        stage = "answer"
        bounded = call_budget(stage)
        entered_stages.append(stage)
        answer_run = generate_evidence_answer(models, knowledge, selection, profile_id=profile_id,
            budget=bounded, outbound_authorized=True, passphrase=passphrase, protocol="compact_v4")
        record(answer_run["call_receipt"], stage)
        if total_tokens > token_cap or (selected_budget.get("max_cost_usd") is not None
                and (not cost_known or total_cost > selected_budget["max_cost_usd"])):
            return output("partial", reason="final_usage_exceeds_or_cannot_verify_budget")
        return output("succeeded")
    except Exception as error:
        receipt = getattr(error, "receipt", None)
        if receipt is None and getattr(error, "call_id", None):
            try:
                receipt = ledger.get_record("model_call", error.call_id)
            except Exception:
                pass
        if receipt is not None and stage in stage_budgets:
            record(receipt, stage)
        no_dispatch = getattr(error, "confirmed_no_dispatch", False) is True
        if no_dispatch and stage in entered_stages and not any(row["stage"] == stage for row in trace):
            trace.append({"stage": stage, "status": "not_dispatched", "confirmed_no_dispatch": True,
                          "budget": deepcopy(stage_budgets[stage])})
        elif stage in entered_stages and not any(row["stage"] == stage for row in trace):
            # A stage may have dispatched before receipt persistence failed. A
            # preflight rejection can also arrive without a receipt; report the
            # conservative interval rather than inventing a zero or a call.
            uncertain_stages.append(stage)
            total_tokens += sum(stage_budgets[stage][k] for k in ("max_input_tokens", "max_output_tokens"))
            cost_known = False
            trace.append({"stage": stage, "status": "dispatch_unknown", "dispatch_unknown": True,
                          "budget": deepcopy(stage_budgets[stage])})
        if isinstance(error, GroundedChatError):
            return output("blocked" if not receipts else "partial", reason=str(error))
        if no_dispatch:
            return output("blocked", reason=stage + "_preflight_stopped")
        return output("blocked" if isinstance(error, EvidenceSnapshotChanged) else "failed",
                      reason=stage + "_failed")
