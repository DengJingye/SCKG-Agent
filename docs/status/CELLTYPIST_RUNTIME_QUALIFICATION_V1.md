# CellTypist Runtime Qualification v1

## Result

`CELLTYPIST_RUNTIME_QUALIFICATION_V1 = PASS`

This checkpoint qualifies one bounded runtime/reference combination. It does not make CellTypist planning-ready or execution-enabled.

## Qualified identity

- Contract alias: `celltypist-immune-all-low-v1`
- Explicitly resolved artifact: `Immune_All_Low.pkl`, official version `v2`
- Official source: `https://celltypist.cog.sanger.ac.uk/models/Pan_Immune_CellTypist/v2/Immune_All_Low.pkl`
- SHA-256: `290874d35dac039d4c9218c343fde4aac1077709b72a331ce7266f6828c36502`
- Size: 2,824,990 bytes
- Species: human
- Scope: pan-immune
- Features: 6,639 human gene symbols
- Labels: 98 model-native labels

The legacy-looking `-v1` suffix is retained as the existing ToolContract alias. It is not interpreted as the upstream artifact version. The qualification crosswalk binds that unchanged alias to the immutable v2 artifact digest. The ToolContract itself was not rewritten.

## Isolated runtime

The model was loaded and executed in an isolated macOS arm64 environment with:

- Python 3.9.23
- CellTypist 1.7.1
- scikit-learn 0.24.1
- Scanpy 1.10.3
- AnnData 0.10.9
- NumPy 1.26.4

The explicit Conda lock digest is `e6ff7414478ea0fdd3dce111a52b64ed65bbd78d8b69e9ec692df619bf3ecc42`. Model loading emitted no scikit-learn serialization-version warning. The current general environment's scikit-learn 1.7.0 load was not accepted as qualification evidence.

An initial Python 3.8 solve was rejected during smoke because the selected Scanpy build used syntax not accepted by that interpreter. Python 3.9 retained scikit-learn 0.24.1 while providing a valid import/runtime combination.

## Runtime and compatibility checks

The existing production CellTypist wrapper was exercised twice with a fixed eight-cell synthetic qualification fixture and the local verified artifact. Both runs succeeded and produced identical label, score, parameter, and metadata digests.

The existing `AnnotationDataProfiler` reported:

- compatible input: 6,639/6,639 model features, overlap rate 1.0, no blockers;
- incompatible input: 0/6,639 model features and `reference_gene_overlap_insufficient`.

The wrapper used a local model path and the manifest prohibited runtime network use. A third execution ran with socket connection functions replaced by a fail-closed qualification guard; it completed without a network attempt and reproduced the same four output digests.

## Local reference pack

The qualified binary, ordered gene list, manifest, explicit alias crosswalk, runtime lock and raw qualification result are retained locally under:

`.sckg_exec/reference-packs/celltypist-runtime-qualification-v1/`

The local pack is intentionally excluded from Git because it contains the upstream pickle and host-local manifest paths. Its asset and runtime identities are frozen in `data/evaluation/celltypist_runtime_qualification_v1/manifest.json`.

## Boundaries

- No Scientific KG claim changed.
- No RAG corpus or index changed.
- No benchmark gold changed.
- No ToolContract changed.
- No Capability Pack was created.
- No Planner binding was created.
- No canonical promotion occurred.
- Execution remains disabled.

The result does not establish biological annotation accuracy and does not widen the model beyond human pan-immune use. Model-specific redistribution terms and external label-ontology mapping remain non-blocking gaps for this local qualification, but must be resolved before distributing the asset.
