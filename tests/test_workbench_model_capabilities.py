"""Offline exact-format contracts; no credential, ledger, provider or fit use."""
from copy import deepcopy

import pytest

from sckg_workbench import model_capabilities as impl
from sckg_workbench.storage import content_hash


KNOWN_FORMAT = {"type": "json_schema", "json_schema": {
    "name": "known_synthetic", "strict": True, "schema": {
        "type": "object", "properties": {"answer": {"type": "string"}},
        "required": ["answer"], "additionalProperties": False}}}


def declaration(formats=None, hashes=None):
    return {"schema_version": impl.CAPABILITIES_VERSION, "api_family": "chat_completions",
            "response_formats": ["json_schema"] if formats is None else formats,
            "json_schema_format_hashes": [content_hash(KNOWN_FORMAT)] if hashes is None else hashes}


def profile(capabilities=None):
    return {"id": "synthetic-profile", "wire_capabilities":
            declaration() if capabilities is None else capabilities}


def test_valid_declaration_is_detached_without_normalizing_the_original():
    original = declaration(["text", "json_schema"])
    before = deepcopy(original)
    validated = impl.validate_wire_capabilities(original)
    assert validated == original and validated is not original
    validated["response_formats"].append("json_object")
    validated["json_schema_format_hashes"].append("1" * 64)
    assert original == before


@pytest.mark.parametrize("value", [None, False, [], "json_schema", {},
    dict(declaration(), schema_version="unsupported-version"),
    dict(declaration(), api_family="responses"),
    dict(declaration(), unexpected="not-a-real-private-value"),
    {key: value for key, value in declaration().items() if key != "api_family"},
    dict(declaration(), response_formats=False),
    dict(declaration(), response_formats="json_schema"),
    dict(declaration(), response_formats=("json_schema",)),
    dict(declaration(), response_formats=[]),
    dict(declaration(), response_formats=["JSON_SCHEMA"]),
    dict(declaration(), response_formats=[True]),
    dict(declaration(), response_formats=["json_schema", "json_schema"]),
    dict(declaration(), json_schema_format_hashes=False),
    dict(declaration(), json_schema_format_hashes="1" * 64),
    dict(declaration(), json_schema_format_hashes=("1" * 64,)),
    dict(declaration(), json_schema_format_hashes=[]),
    dict(declaration(), json_schema_format_hashes=[None]),
    dict(declaration(), json_schema_format_hashes=[True]),
    dict(declaration(), json_schema_format_hashes=["A" * 64]),
    dict(declaration(), json_schema_format_hashes=["f" * 63]),
    dict(declaration(), json_schema_format_hashes=["f" * 65]),
    dict(declaration(), json_schema_format_hashes=["g" * 64]),
    dict(declaration(), json_schema_format_hashes=["1" * 64, "1" * 64]),
    declaration(["text"], ["1" * 64]),
    declaration(["json_object"], ["1" * 64]),
])
def test_malformed_or_ambiguous_declarations_raise_only_safe_error(value):
    with pytest.raises(ValueError) as error:
        impl.validate_wire_capabilities(value)
    assert str(error.value) == "Invalid wire capabilities declaration"
    assert "not-a-real-private-value" not in str(error.value)


def test_hash_list_supports_exactly_the_declared_bounded_maximum():
    hashes = [f"{index:064x}" for index in range(64)]
    assert impl.validate_wire_capabilities(declaration(hashes=hashes))["json_schema_format_hashes"] == hashes
    with pytest.raises(ValueError):
        impl.validate_wire_capabilities(declaration(hashes=[*hashes, "f" * 64]))


@pytest.mark.parametrize("requested", [None, {"type": "json_object"}, KNOWN_FORMAT])
def test_legacy_loose_and_strict_are_distinct_and_never_modify_the_profile(requested):
    legacy = {"id": "legacy-profile", "model": "synthetic-model"}
    before = deepcopy(legacy)
    loose = impl.preflight_wire(legacy, requested)
    strict = impl.preflight_wire(legacy, requested, require_declared=True)
    assert loose["capabilities_status"] == strict["capabilities_status"] == "legacy_unqualified"
    assert loose["dispatch_allowed"] is True and strict["dispatch_allowed"] is False
    assert loose["reason"] == "legacy_unqualified" and strict["reason"] == "declaration_required"
    assert loose["remotely_verified"] is strict["remotely_verified"] is False
    assert loose["capabilities_hash"] is strict["capabilities_hash"] is None
    assert legacy == before and "wire_capabilities" not in legacy


def test_an_explicit_null_is_invalid_not_a_legacy_declaration():
    with pytest.raises(ValueError):
        impl.preflight_wire({"id": "invalid", "wire_capabilities": None}, KNOWN_FORMAT)


def test_exact_format_admission_reports_only_operator_declared_limits():
    owner, requested = profile(), deepcopy(KNOWN_FORMAT)
    before = deepcopy((owner, requested))
    result = impl.preflight_wire(owner, requested, require_declared=True)
    assert result == {"schema_version": "model-wire-preflight-v1", "profile_id": "synthetic-profile",
        "api_family": "chat_completions", "requested_format": "json_schema",
        "response_format_hash": content_hash(requested), "capabilities_status": "declared_within_limits",
        "dispatch_allowed": True, "reason": "within_declared_limits", "remotely_verified": False,
        "capabilities_hash": content_hash(owner["wire_capabilities"])}
    assert (owner, requested) == before


@pytest.mark.parametrize("change", ["name", "strict", "schema_version", "cross_field", "unique_items"])
def test_a_changed_complete_format_cannot_reuse_the_known_exact_hash(change):
    changed = deepcopy(KNOWN_FORMAT)
    if change == "name":
        changed["json_schema"]["name"] = "another_version"
    elif change == "strict":
        changed["json_schema"]["strict"] = False
    elif change == "schema_version":
        changed["json_schema"]["schema"]["$id"] = "synthetic-schema-v2"
    elif change == "cross_field":
        changed["json_schema"]["schema"]["anyOf"] = [
            {"properties": {"answer": {"const": "synthetic"}}, "required": ["answer"]}]
    else:
        changed["json_schema"]["schema"]["properties"]["values"] = {"type": "array", "uniqueItems": True}
    before = deepcopy(changed)
    report = impl.preflight_wire(profile(), changed)
    assert report["capabilities_status"] == "declared_unsupported" and report["dispatch_allowed"] is False
    assert report["reason"] == "json_schema_format_hash_not_declared"
    assert report["response_format_hash"] == content_hash(changed) and changed == before


def test_real_explicit_missing_v2_does_not_inherit_the_legacy_workflow_schema_hash():
    from sckg_workbench.workflow_chat import EXPLICIT_MISSING_VERSION, workflow_format
    legacy = workflow_format(initial=True, answer_contract_version=None)
    explicit = workflow_format(initial=True, answer_contract_version=EXPLICIT_MISSING_VERSION)
    owner = profile(declaration(hashes=[content_hash(legacy)]))
    assert impl.preflight_wire(owner, legacy)["dispatch_allowed"] is True
    assert impl.preflight_wire(owner, explicit)["dispatch_allowed"] is False
    assert explicit["json_schema"]["schema"]["$defs"]["CompactMissingV3"]["properties"]["p"]["uniqueItems"] is True
    owner = profile(declaration(hashes=[content_hash(explicit)]))
    assert impl.preflight_wire(owner, explicit, require_declared=True)["dispatch_allowed"] is True
    assert impl.preflight_wire(owner, explicit)["remotely_verified"] is False


def test_canonical_key_order_does_not_change_the_complete_format_hash():
    reordered = {"json_schema": {"schema": deepcopy(KNOWN_FORMAT["json_schema"]["schema"]),
        "strict": True, "name": "known_synthetic"}, "type": "json_schema"}
    assert impl.preflight_wire(profile(), reordered)["dispatch_allowed"] is True
    assert content_hash(reordered) == content_hash(KNOWN_FORMAT)


def test_format_presence_is_explicit_and_json_object_is_not_a_schema_guarantee():
    schema_only = profile()
    for request in (None, {"type": "json_object"}):
        rejected = impl.preflight_wire(schema_only, request)
        assert rejected["dispatch_allowed"] is False and rejected["reason"] == "response_format_not_declared"
    object_only = profile(declaration(["json_object"], []))
    result = impl.preflight_wire(object_only, {"type": "json_object"})
    assert result["dispatch_allowed"] is True and result["remotely_verified"] is False
    assert "canonical_validation_passed" not in result
    assert impl.preflight_wire(object_only, KNOWN_FORMAT)["dispatch_allowed"] is False
    text_only = profile(declaration(["text"], []))
    assert impl.preflight_wire(text_only)["dispatch_allowed"] is True


@pytest.mark.parametrize("requested", [False, "json_schema", [], {"type": []}, {"type": {}},
    {"type": "unknown"}, {"type": "text"},
    {"type": "json_schema", "extra": float("nan")}])
def test_invalid_request_format_is_rejected_without_echoing_its_contents(requested):
    with pytest.raises(ValueError) as error:
        impl.preflight_wire(profile(), requested)
    assert str(error.value) == "Invalid wire request format"


@pytest.mark.parametrize("required", [None, 0, 1, "true"])
def test_strict_requirement_is_not_truthy_coercion(required):
    with pytest.raises(ValueError, match="Invalid wire declaration requirement"):
        impl.preflight_wire(profile(), KNOWN_FORMAT, require_declared=required)


def test_receipt_binding_is_fingerprinting_not_a_new_dispatch_admission(monkeypatch):
    owner = profile()
    changed = deepcopy(KNOWN_FORMAT)
    changed["json_schema"]["name"] = "unlisted"
    def forbidden(*args, **kwargs):
        raise AssertionError("Receipt replay may not run the current admission policy")
    monkeypatch.setattr(impl, "preflight_wire", forbidden)
    binding = impl.wire_receipt_binding(owner, changed)
    assert binding == {"wire_capabilities_hash": content_hash(owner["wire_capabilities"]),
                       "wire_response_format_hash": content_hash(changed)}
    assert impl.wire_receipt_matches(owner, binding, changed) is True


def test_optional_new_receipt_markers_detect_each_removed_or_altered_side():
    owner = profile()
    binding = impl.wire_receipt_binding(owner, KNOWN_FORMAT)
    assert impl.wire_receipt_matches(owner, dict(binding, status="succeeded"), KNOWN_FORMAT)
    for key in binding:
        missing = {k: v for k, v in binding.items() if k != key}
        assert impl.wire_receipt_matches(owner, missing, KNOWN_FORMAT) is False
        assert impl.wire_receipt_matches(owner, dict(binding, **{key: "0" * 64}), KNOWN_FORMAT) is False
    assert impl.wire_receipt_matches(owner, {}, KNOWN_FORMAT) is False
    legacy = {"id": owner["id"]}
    assert impl.wire_receipt_matches(legacy, binding, KNOWN_FORMAT) is False
    altered_profile = deepcopy(owner)
    altered_profile["wire_capabilities"]["response_formats"].append("text")
    assert impl.wire_receipt_matches(altered_profile, binding, KNOWN_FORMAT) is False
    changed_format = deepcopy(KNOWN_FORMAT)
    changed_format["json_schema"]["strict"] = False
    assert impl.wire_receipt_matches(owner, binding, changed_format) is False


def test_truly_marker_free_legacy_receipts_retain_original_compatibility():
    legacy = {"id": "legacy"}
    assert impl.wire_receipt_binding(legacy, KNOWN_FORMAT) == {}
    assert impl.wire_receipt_matches(legacy, {"status": "succeeded"}, KNOWN_FORMAT) is True
    assert impl.wire_receipt_matches(legacy, {"wire_capabilities_hash": None}, KNOWN_FORMAT) is False
    assert impl.wire_receipt_matches(legacy, {"wire_response_format_hash": None}, KNOWN_FORMAT) is False


@pytest.mark.parametrize("owner,receipt", [(None, {}), ({}, None), ({"wire_capabilities": None}, {})])
def test_receipt_match_is_a_boolean_for_malformed_inputs(owner, receipt):
    assert impl.wire_receipt_matches(owner, receipt, KNOWN_FORMAT) is False


def test_functions_need_no_ledger_workspace_credentials_or_transport(monkeypatch):
    from sckg_workbench import storage
    def forbidden(*args, **kwargs):
        raise AssertionError("Pure capability functions must not construct persistence")
    monkeypatch.setattr(storage, "Ledger", forbidden)
    monkeypatch.setattr(storage, "Workspace", forbidden)
    owner, requested = profile(), deepcopy(KNOWN_FORMAT)
    before = deepcopy((owner, requested))
    first = impl.preflight_wire(owner, requested)
    second = impl.preflight_wire(owner, requested)
    binding = impl.wire_receipt_binding(owner, requested)
    assert first == second and impl.wire_receipt_matches(owner, binding, requested)
    assert (owner, requested) == before
