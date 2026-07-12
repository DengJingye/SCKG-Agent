import json

from core.trace_context import TraceCollector, TraceContext
from observability.dashboard.services import EvidenceRecoveryService, TraceService


def test_dashboard_service_extracts_kg_gate_summary(tmp_path):
    trace_path = tmp_path / "traces.jsonl"
    trace = TraceContext(
        trace_type="agent_run",
        metadata={"query": "doublet benchmark", "force_offline_graph": True},
    )
    trace.record_stage(
        "kg_hard_filter",
        method="unit_test",
        output_summary={
            "provider": "offline_graph",
            "raw_candidate_count": 2,
            "candidate_tool_count": 1,
            "tool_candidate_count": 1,
            "retrieval_result_count": 1,
            "admitted_candidate_tools": ["Scrublet"],
            "raw_candidate_tools": ["Scrublet", "DoubletFinder"],
            "blocked_reason_counts": {"qualitative_benchmark_only": 1},
            "candidate_diagnostics": [
                {
                    "tool_name": "DoubletFinder",
                    "gate_status": "blocked",
                    "gate_reasons": ["qualitative_benchmark_only"],
                }
            ],
        },
        elapsed_ms=3.0,
    )
    TraceCollector(trace_path).collect(trace)

    summary = TraceService(trace_path).kg_gate_summary()

    assert summary["provider"] == "offline_graph"
    assert summary["raw_candidate_count"] == 2
    assert summary["candidate_tool_count"] == 1
    assert summary["admitted_candidate_tools"] == ["Scrublet"]
    assert summary["blocked_reason_counts"] == {"qualitative_benchmark_only": 1}
    assert summary["candidate_diagnostics"][0]["tool_name"] == "DoubletFinder"


def test_evidence_recovery_service_loads_core_source_coverage(tmp_path):
    manifest = tmp_path / "core_manifest.tsv"
    manifest.write_text(
        "source_id\tevidence_kind\ttool_name\trecord_id\tsource_title\tsource_url\tdoi_or_pmid\t"
        "preferred_source_type\tlocal_text_path\tfetch_status\tfetch_priority\tnotes\n"
        f"SRC1\tdocs\tScanpy\tREC1\tScanpy README\thttps://github.com/theislab/scanpy\t\t"
        f"github_readme\t{tmp_path / 'scanpy.txt'}\tfetched_github_readme\t1\tretrieval-only\n"
        f"SRC2\tdocs\tMOFA2\tREC2\tMOFA2 docs\thttps://biofam.github.io/MOFA2/\t\t"
        f"official_docs_html\t{tmp_path / 'missing.txt'}\tnot_fetched\t2\tretrieval-only\n",
        encoding="utf-8",
    )
    (tmp_path / "scanpy.txt").write_text("Scanpy source text", encoding="utf-8")
    audit = tmp_path / "audit.tsv"
    audit.write_text(
        "tool_name\tsource_chunk_count\tdense_vector_chunk_count\treview_status\tquality_flags\n"
        "Scanpy\t3\t0\tsource_bound_profile\tdense_embedding_missing\n"
        "MOFA2\t0\t0\tlow_source_coverage\tlow_source_coverage,dense_embedding_missing\n",
        encoding="utf-8",
    )
    algorithm_summary = tmp_path / "summary.json"
    algorithm_summary.write_text(
        json.dumps({"tools_with_source_chunks": 1, "tools_without_source_chunks": 1}),
        encoding="utf-8",
    )

    coverage = EvidenceRecoveryService(
        core_source_manifest_path=manifest,
        algorithm_audit_path=audit,
        algorithm_summary_path=algorithm_summary,
        evidence_chunks_path=tmp_path / "missing_chunks.jsonl",
    ).load_source_coverage()

    assert coverage["summary"]["core_tools"] == 2
    assert coverage["summary"]["covered_tools"] == 1
    assert coverage["summary"]["missing_tools"] == 1
    by_tool = {row["tool_name"]: row for row in coverage["rows"]}
    assert by_tool["Scanpy"]["coverage_status"] == "covered"
    assert by_tool["Scanpy"]["local_text_available"] == 1
    assert by_tool["MOFA2"]["coverage_status"] == "needs_source"


def test_evidence_recovery_service_loads_literature_source_coverage(tmp_path):
    coverage_tsv = tmp_path / "literature.tsv"
    coverage_tsv.write_text(
        "priority\tcoverage_status\taction\ttool_name\tevidence_kind\trecord_id\tsource_title\t"
        "doi_or_pmid\tsource_url\tfetch_status\tpdf_status\tlocal_text_path\tpdf_path\t"
        "suggested_pdf_path\tselected_pdf_url\tprimary_candidate_urls\tnotes\n"
        "1\tmissing_source_text\tmanual_search_required\tScrublet\tpublication\tREC1\tTitle\t"
        "10.1/x\thttps://doi.org/10.1/x\tnot_fetched\tmissing_pdf\t\t\t"
        "data/evidence_sources/pdfs/Scrublet_REC1.pdf\t\t\tmanual\n",
        encoding="utf-8",
    )
    summary_json = tmp_path / "literature.json"
    summary_json.write_text(
        json.dumps({"rows": 1, "source_text_available": 0, "missing_source_text": 1}),
        encoding="utf-8",
    )

    coverage = EvidenceRecoveryService(
        literature_coverage_tsv_path=coverage_tsv,
        literature_coverage_summary_path=summary_json,
    ).load_literature_source_coverage()

    assert coverage["summary"]["missing_source_text"] == 1
    assert coverage["rows"][0]["tool_name"] == "Scrublet"
    assert coverage["rows"][0]["action"] == "manual_search_required"


def test_evidence_recovery_service_loads_source_registry_status(tmp_path):
    registry = tmp_path / "source_registry.tsv"
    registry.write_text(
        "source_id\tsource_status\tvalidation_status\tcanonical_title\treferring_tool_names\n"
        "SRC1\tsource_metadata_mismatch\tsource_metadata_mismatch\tWrong DOI\tCellTypist; SingleR\n",
        encoding="utf-8",
    )
    candidates = tmp_path / "pdf_candidates.tsv"
    candidates.write_text(
        "source_id\trecord_id\tcandidate_url\tvalidation_status\tquarantine\n"
        "SRC1\tREC1\thttps://example.org/wrong.pdf\tsource_metadata_mismatch\ttrue\n",
        encoding="utf-8",
    )
    validation = tmp_path / "validation.tsv"
    validation.write_text(
        "source_id\trecommended_action\tvalidation_status\n"
        "SRC1\tcorrect_doi_or_replace_source\tsource_metadata_mismatch\n",
        encoding="utf-8",
    )
    acquisition = tmp_path / "acquisition.json"
    acquisition.write_text(json.dumps({"source_records": 1, "candidate_quarantine_rows": 1}), encoding="utf-8")
    extraction = tmp_path / "extraction.json"
    extraction.write_text(json.dumps({"source_metadata_mismatch": 1}), encoding="utf-8")

    status = EvidenceRecoveryService(
        source_registry_path=registry,
        pdf_candidate_registry_path=candidates,
        source_validation_report_path=validation,
        source_acquisition_summary_path=acquisition,
        source_extraction_summary_path=extraction,
    ).load_source_registry_status()

    assert status["registry_rows"][0]["source_status"] == "source_metadata_mismatch"
    assert status["candidate_rows"][0]["quarantine"] == "true"
    assert status["validation_rows"][0]["recommended_action"] == "correct_doi_or_replace_source"
    assert status["acquisition_summary"]["candidate_quarantine_rows"] == 1


def test_evidence_recovery_service_loads_decision_workflow_demo(tmp_path):
    demo_path = tmp_path / "decision_demo.json"
    demo_path.write_text(
        json.dumps(
            {
                "demo": "decision_workflow_demo_v1",
                "global_evidence_coverage": {"workflow_steps": 7},
                "workflow_steps": [{"step_id": "input_qc"}],
            }
        ),
        encoding="utf-8",
    )

    demo = EvidenceRecoveryService(decision_workflow_demo_path=demo_path).load_decision_workflow_demo()

    assert demo["demo"] == "decision_workflow_demo_v1"
    assert demo["global_evidence_coverage"]["workflow_steps"] == 7
