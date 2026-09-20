# Midterm Scientific Knowledge Studio Demo v1

Target duration: 90–120 seconds.

1. Open **Admin · Scientific KG** and point out the frozen current state: live snapshot counts, not hard-coded values.
2. Open **Candidate Studio**. Read the banner: **PREVIEW ONLY · Scientific KG unchanged**.
3. Upload one PDF. For the frozen demo, use the local `soupx-1.6.2-manual.pdf`; do not upload multiple files.
4. Show the eight steps: Upload → Source → Parse → Evidence → Extract → Resolve → Validate → Preview.
5. Select one EvidenceSpanProposal. Show its page, stable segment ID, exact text, offsets, and highlighted source binding.
6. In the Proposal Graph, identify an existing Scientific KG identity, the candidate proposal, its claim, and the supporting evidence edge. Explain that existing-KG inference is visually distinct from PDF-extracted support.
7. Open **Current Scientific KG vs Proposed Delta**. Say “If accepted, proposed delta would be…”, then show +1 entity, +0 relation, +8 claim, and +16 evidence proposals.
8. Re-emphasize: KG mutation disabled; ReviewDecision and canonical promotion unavailable.
9. Show the Run Trace and the recorded PDF/parser/proposal hashes.

Close with:

> 自动抽取得到的是有证据绑定和本体约束的 Candidate Proposal，而不是直接写入受信知识图谱。

The real run used local deterministic extraction and records `REAL_LLM_EXTRACTION=NOT_RUN`; do not describe it as an LLM result.

The bounded user-supplied sanity review is not a formal benchmark. It flags claim atomization and EvidenceSpan boundaries as the next quality targets, with final PDF-page confirmation still pending.
