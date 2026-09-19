from __future__ import annotations

import json

from eval.dev_only_c7_loader import load_dev_jsonl


def test_dev_loader_never_materializes_sealed_payload(tmp_path):
    path = tmp_path / "mixed.jsonl"
    rows = [
        {"query_id": "dev-1", "query": "allowed development payload"},
        {"query_id": "sealed-1", "query": "SENTINEL_MUST_NOT_BE_DECODED"},
    ]
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))
    decoded_texts = []

    def audited_decoder(text):
        decoded_texts.append(text)
        return json.loads(text)

    loaded, audit = load_dev_jsonl(path, {"dev-1"}, decoder=audited_decoder)

    assert [row["query_id"] for row in loaded] == ["dev-1"]
    assert [text.rstrip("\n") for text in decoded_texts] == [
        json.dumps(rows[0], sort_keys=True)
    ]
    assert all("SENTINEL_MUST_NOT_BE_DECODED" not in text for text in decoded_texts)
    assert audit.skipped_record_ids == ("sealed-1",)
    assert audit.sealed_payload_accessed is False
