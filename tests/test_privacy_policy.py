import json

from core.privacy_policy import OutboundDisclosureService, PrivacyMode


def test_strict_offline_blocks_external_calls_and_audit_stores_no_plaintext(tmp_path):
    audit = tmp_path / "audit.jsonl"
    service = OutboundDisclosureService(audit_path=audit)
    prepared = service.prepare(
        {
            "query": "compare doublet tools",
            "input_path": "/Users/private/secret/input.h5ad",
            "matrix": [[1, 2]],
            "metadata": {"note": "see /Users/private/secret/file.txt"},
        },
        purpose="planning",
        provider="example.invalid",
    )
    assert "input_path" not in prepared.payload
    assert "matrix" not in prepared.payload
    assert "/Users/" not in json.dumps(prepared.payload)
    decision = service.authorize(
        mode=PrivacyMode.STRICT_OFFLINE,
        disclosure_hash=prepared.disclosure.disclosure_hash,
        session_id="session-a",
        consent_id=None,
    )
    assert decision.allowed is False
    assert "strict_offline_blocks_external_network" in decision.reasons
    audit_text = audit.read_text(encoding="utf-8")
    assert "compare doublet tools" not in audit_text
    assert "/Users/" not in audit_text


def test_local_hybrid_requires_bound_consent_and_once_cannot_replay():
    service = OutboundDisclosureService()
    prepared = service.prepare({"query": "safe metadata"}, purpose="planning", provider="x")
    missing = service.authorize(
        mode=PrivacyMode.LOCAL_HYBRID,
        disclosure_hash=prepared.disclosure.disclosure_hash,
        session_id="session-a",
        consent_id=None,
    )
    assert missing.allowed is False
    consent = service.grant(
        disclosure_hash=prepared.disclosure.disclosure_hash,
        session_id="session-a",
        scope="once",
    )
    assert service.authorize(
        mode=PrivacyMode.LOCAL_HYBRID,
        disclosure_hash=prepared.disclosure.disclosure_hash,
        session_id="session-a",
        consent_id=consent.consent_id,
    ).allowed
    replay = service.authorize(
        mode=PrivacyMode.LOCAL_HYBRID,
        disclosure_hash=prepared.disclosure.disclosure_hash,
        session_id="session-a",
        consent_id=consent.consent_id,
    )
    assert replay.allowed is False
    assert "outbound_consent_consumed" in replay.reasons
