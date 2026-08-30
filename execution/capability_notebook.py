from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Protocol

from core.execution_models import WorkflowPlan
from core.research_workspace_models import StepContract


class NotebookRenderer(Protocol):
    renderer_id: str
    language_name: str
    kernel_name: str
    kernel_display_name: str

    def bootstrap(self, context: dict[str, Any]) -> list[dict[str, Any]]: ...

    def render(
        self,
        step: StepContract,
        parameters: dict[str, Any],
        *,
        parameter_provenance: list[Any] | None = None,
    ) -> list[dict[str, Any]]: ...


class NotebookRendererRegistry:
    def __init__(self, renderers: list[NotebookRenderer] | None = None) -> None:
        self._renderers: dict[str, NotebookRenderer] = {}
        for renderer in renderers or []:
            self.register(renderer)

    def register(self, renderer: NotebookRenderer) -> None:
        if renderer.renderer_id in self._renderers:
            raise ValueError(f"duplicate notebook renderer: {renderer.renderer_id}")
        self._renderers[renderer.renderer_id] = renderer

    def get(self, renderer_id: str) -> NotebookRenderer:
        try:
            return self._renderers[renderer_id]
        except KeyError as exc:
            raise KeyError(f"notebook renderer is not registered: {renderer_id}") from exc


class GenericNotebookCompiler:
    """Compile reviewed step renderers into an editable, never auto-executed notebook."""

    def __init__(self, renderer_registry: NotebookRendererRegistry) -> None:
        self.renderer_registry = renderer_registry

    def compile(
        self,
        *,
        plan: WorkflowPlan,
        step_contracts: dict[str, StepContract],
        output_path: Path,
        title: str,
        notebook_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if plan.execution_eligible:
            raise ValueError("generic notebook compilation accepts dry-run plans only")
        output_path = Path(output_path)
        cells = [_markdown_cell(f"# {title}\n\nEditable shadow notebook. Compilation does not execute code.", "overview")]
        source_digests: dict[str, str] = {}
        languages: set[str] = set()
        renderers: dict[str, NotebookRenderer] = {}
        for node in plan.steps:
            step = step_contracts.get(node.operation)
            if step is None:
                raise KeyError(f"step contract is not registered: {node.operation}")
            renderer_id = step.notebook_renderer_id or ""
            renderers.setdefault(renderer_id, self.renderer_registry.get(renderer_id))
        context = dict(notebook_context or {})
        context.setdefault("notebook_path", str(output_path))
        context.setdefault(
            "output_dir",
            str(
                output_path.parent
                / ".sckg_notebook_artifacts"
                / output_path.stem
            ),
        )
        for renderer in renderers.values():
            bootstrap = getattr(renderer, "bootstrap", None)
            if callable(bootstrap):
                cells.extend(bootstrap(context))
        for node in plan.steps:
            step = step_contracts.get(node.operation)
            if step is None:
                raise KeyError(f"step contract is not registered: {node.operation}")
            renderer = self.renderer_registry.get(step.notebook_renderer_id or "")
            languages.add(getattr(renderer, "language_name", "python"))
            rendered = renderer.render(
                step,
                dict(node.parameters),
                parameter_provenance=list(node.parameter_provenance),
            )
            if not rendered:
                raise ValueError(f"renderer produced no cells: {step.method_id}")
            cells.extend(rendered)
        for index, cell in enumerate(cells):
            cell.setdefault("id", f"cell-{index:03d}")
            cell.setdefault("metadata", {})
            source = cell.get("source", "")
            digest = hashlib.sha256(str(source).encode("utf-8")).hexdigest()
            source_digests[cell["id"]] = digest
            cell["metadata"].setdefault("sckg", {})["source_digest"] = digest
        kernel_specs = {
            (
                str(getattr(renderer, "kernel_name", "")),
                str(getattr(renderer, "kernel_display_name", "")),
                str(getattr(renderer, "language_name", "python")),
            )
            for renderer in renderers.values()
            if getattr(renderer, "kernel_name", "")
        }
        notebook_metadata: dict[str, Any] = {
            "language_info": {
                "name": next(iter(languages)) if len(languages) == 1 else "mixed"
            },
            "sckg": {
                "schema_version": "sckg-generic-notebook-v1",
                "plan_id": plan.plan_id,
                "execution_request_count": 0,
                "editable_not_trusted_execution": True,
                "trusted_code_source": "maintainer_step_template",
                "cell_source_digests": source_digests,
            },
        }
        if len(kernel_specs) == 1:
            kernel_name, display_name, language = next(iter(kernel_specs))
            notebook_metadata["kernelspec"] = {
                "name": kernel_name,
                "display_name": display_name or kernel_name,
                "language": language,
            }
        payload = {
            "cells": cells,
            "metadata": notebook_metadata,
            "nbformat": 4,
            "nbformat_minor": 5,
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
        return {
            "path": str(output_path),
            "sha256": _sha256(output_path),
            "cell_count": len(cells),
            "execution_request_count": 0,
        }


class MaintainerTemplateRenderer:
    def __init__(
        self,
        templates: dict[str, str],
        *,
        renderer_id: str = "generic_step_renderer",
        language_name: str = "python",
        kernel_name: str = "",
        kernel_display_name: str = "",
    ) -> None:
        if not renderer_id:
            raise ValueError("renderer_id is required")
        self.renderer_id = renderer_id
        self.language_name = language_name
        self.kernel_name = kernel_name
        self.kernel_display_name = kernel_display_name
        self.templates = dict(templates)

    def bootstrap(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        return []

    def render(
        self,
        step: StepContract,
        parameters: dict[str, Any],
        *,
        parameter_provenance: list[Any] | None = None,
    ) -> list[dict[str, Any]]:
        try:
            source = self.templates[step.operation]
        except KeyError as exc:
            raise KeyError(f"reviewed template missing for operation: {step.operation}") from exc
        provenance_lines = _parameter_provenance_lines(parameter_provenance or [])
        heading = _markdown_cell(
            f"## {step.operation.replace('_', ' ').title()}\n\n"
            f"Consumes: `{', '.join(item.representation_id for item in step.consumes)}`  \n"
            f"Produces: `{', '.join(item.representation_id for item in step.produces)}`"
            + (
                "\n\nResolved parameters and provenance:\n" + "\n".join(provenance_lines)
                if provenance_lines
                else ""
            ),
            _safe_cell_id(f"{step.method_id}-description"),
        )
        code = _code_cell(
            "STEP_PARAMETERS = " + json.dumps(parameters, sort_keys=True) + "\n" + source,
            _safe_cell_id(f"{step.method_id}-code"),
        )
        return [heading, code]


def _parameter_provenance_lines(values: list[Any]) -> list[str]:
    lines: list[str] = []
    for value in values:
        payload = (
            value.model_dump(mode="json")
            if hasattr(value, "model_dump")
            else dict(value)
            if isinstance(value, dict)
            else {}
        )
        parameter_name = str(payload.get("parameter_name") or "")
        if not parameter_name:
            continue
        rendered_value = json.dumps(payload.get("value_or_range"), sort_keys=True)
        origin = str(payload.get("origin_type") or "unknown")
        source_id = str(payload.get("source_id") or "reviewed_contract")
        policy = str(payload.get("policy_rule_id") or "")
        explanation = f"`{parameter_name}={rendered_value}` — `{origin}` from `{source_id}`"
        if policy:
            explanation += f"; rule `{policy}`"
        lines.append(f"- {explanation}")
    return lines


def _markdown_cell(source: str, cell_id: str) -> dict[str, Any]:
    return {"cell_type": "markdown", "id": cell_id, "metadata": {}, "source": source}


def _code_cell(source: str, cell_id: str) -> dict[str, Any]:
    return {
        "cell_type": "code",
        "id": cell_id,
        "metadata": {},
        "execution_count": None,
        "outputs": [],
        "source": source,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_cell_id(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-")
    return clean or "cell"
