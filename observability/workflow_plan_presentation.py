"""Read-only presentation of existing plan provenance; no inferred citations."""
import json
from urllib.parse import urlsplit


def parameter_source_rows(steps):
    rows = []
    for number, step in enumerate(steps, 1):
        for provenance in step.parameter_provenance:
            source = str(provenance.source_id or "")
            try:
                url = urlsplit(source)
                link = source if (url.scheme in {"https", "http"} and url.hostname
                                  and not url.username and not url.password
                                  and not any(ord(c) < 32 for c in source)) else None
            except ValueError:
                link = None
            rows.append({
                "step": number, "method": step.operation,
                "parameter": provenance.parameter_name,
                "value": json.dumps(provenance.value_or_range, ensure_ascii=False),
                "origin": provenance.origin_type, "source_type": provenance.source_type,
                "source_id": source or "未登记来源",
                "source_url": link,
                "locator": provenance.source_span or "未登记精确位置",
                "version": provenance.tool_version or "未登记版本",
                "scope": provenance.applicable_scope,
                "rule": provenance.policy_rule_id or "",
                "limitations": "；".join(provenance.limitations),
            })
    return rows


def runtime_probe_display(probe):
    """Do not confuse a manifest signature, installed size and runtime readiness."""
    state = getattr(probe.state, "value", probe.state)
    source = getattr(probe.source, "value", probe.source)
    return {
        "state": str(state),
        "source": "未发现已登记环境" if source == "none" else str(source),
        "说明": ("未发现该 pack 的可用环境；0 B 不是数据大小或有效性评分"
                 if state == "missing" else "环境状态与安装占用；不代表分析或科学验证已完成"),
    }
