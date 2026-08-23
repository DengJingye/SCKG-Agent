from agent.grounded_answer_audit import audit_grounded_answer_v3


def _reference(*, claim_text: str = "Scrublet requires raw count matrices."):
    return {
        "index": 1,
        "tool_name": "Scrublet",
        "source_id": "scrublet-readme",
        "source_span_id": "scrublet-readme:methods:2",
        "claim_text": claim_text,
        "authority": "source_bound",
        "source_bound": True,
    }


def test_v3_records_structural_support_without_claiming_semantic_entailment() -> None:
    audit = audit_grounded_answer_v3(
        "### 已核验证据\nScrublet requires raw count matrices.[1]",
        references=[_reference()],
        execution_request_count=0,
    )

    assert audit.passed is True
    assert audit.structurally_supported_claim_rate == 1.0
    assert audit.semantic_claim_correctness is None
    assert audit.verified_claims[0].semantic_review_status == "not_run"


def test_v3_keeps_unverified_model_knowledge_outside_scientific_authority() -> None:
    audit = audit_grounded_answer_v3(
        "### 已核验证据\nScrublet requires raw count matrices.[1]\n"
        "### 模型通识（尚未核验）\n同型 doublet 通常更难识别。",
        references=[_reference()],
        execution_request_count=0,
    )

    assert audit.passed is True
    assert len(audit.verified_claims) == 1
    assert len(audit.unverified_model_knowledge_claims) == 1
    assert audit.unverified_model_knowledge_claims[0].governance_action == "label_unverified"


def test_v3_rejects_governed_citation_inside_unverified_section() -> None:
    audit = audit_grounded_answer_v3(
        "### 模型通识（尚未核验）\nScrublet is always optimal.[1]",
        references=[_reference()],
        execution_request_count=0,
    )

    assert audit.passed is False
    assert audit.unsupported_claim_count == 1
    assert audit.claims[0].governance_action == "remove"


def test_v3_rejects_benchmark_number_outside_source_scope() -> None:
    audit = audit_grounded_answer_v3(
        "### 已核验证据\nScrublet benchmark AUPRC is 0.99.[1]",
        references=[_reference(claim_text="Scrublet benchmark AUPRC is 0.80.")],
        execution_request_count=0,
    )

    assert audit.passed is False
    assert audit.claims[0].numeric_scope_match == "mismatch"
    assert audit.claims[0].governance_action == "remove"


def test_v3_ignores_reference_list_and_markdown_headings_as_claims() -> None:
    audit = audit_grounded_answer_v3(
        "### 已核验证据\nScrublet requires raw count matrices.[1]\n"
        "### 参考资料\n[1] Scrublet · official README · section:Input",
        references=[_reference()],
        execution_request_count=0,
    )

    assert audit.passed is True
    assert len(audit.claims) == 1
    assert audit.claims[0].claim_text == "Scrublet requires raw count matrices."


def test_v3_does_not_treat_10x_product_name_as_numeric_benchmark_claim() -> None:
    audit = audit_grounded_answer_v3(
        "Scrublet can be applied to 10x scRNA-seq raw counts.[1]",
        references=[_reference(claim_text="Scrublet accepts scRNA-seq raw count matrices.")],
        execution_request_count=0,
    )

    assert audit.claims[0].numeric_scope_match == "not_applicable"


def test_v3_does_not_treat_numbered_list_marker_as_claim_number() -> None:
    audit = audit_grounded_answer_v3(
        "1. Scrublet requires raw count matrices.[1]",
        references=[_reference()],
        execution_request_count=0,
    )

    assert audit.passed is True
    assert audit.claims[0].numeric_scope_match == "not_applicable"
