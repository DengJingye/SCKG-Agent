"""Stdlib-only, private framed-RPC guest for frozen scientific operations.

The AST policy is defense in depth. The parent must also establish the OS
boundary before starting this script; importing this module executes no guest.
"""
from __future__ import annotations

import ast
import contextlib
import hashlib
import io
import json
import math
import struct
import sys

MAX_SOURCE_BYTES = 16384
MAX_AST_NODES = 2000
MAX_FRAME_BYTES = 65536
MAX_LOG_BYTES = 16384
MAX_TOOL_MESSAGES = 8
OPERATIONS = frozenset({"inspect_dataset", "run_scrublet"})
SAFE_BUILTINS = {
    "abs": abs, "all": all, "any": any, "bool": bool, "dict": dict,
    "enumerate": enumerate, "float": float, "int": int, "len": len,
    "list": list, "max": max, "min": min, "range": range, "reversed": reversed,
    "round": round, "set": set, "sorted": sorted, "str": str, "sum": sum,
    "tuple": tuple, "zip": zip, "print": print,
    "TypeError": TypeError, "ValueError": ValueError, "KeyError": KeyError,
    "IndexError": IndexError, "ZeroDivisionError": ZeroDivisionError,
    "RuntimeError": RuntimeError, "AssertionError": AssertionError,
}
_METHODS = frozenset({"get", "items", "keys", "values", "append", "extend", "count", "index"})
_NODES = frozenset({
    ast.Module, ast.Assign, ast.AugAssign, ast.Expr, ast.If, ast.For, ast.While,
    ast.Break, ast.Continue, ast.Pass, ast.Assert, ast.Raise, ast.Try,
    ast.ExceptHandler, ast.Name, ast.Load, ast.Store, ast.Constant, ast.List,
    ast.Tuple, ast.Set, ast.Dict, ast.Subscript, ast.Slice, ast.BinOp, ast.UnaryOp,
    ast.BoolOp, ast.Compare, ast.IfExp, ast.Call, ast.keyword, ast.Attribute,
    ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp, ast.comprehension,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
    ast.USub, ast.UAdd, ast.Not, ast.And, ast.Or, ast.Eq, ast.NotEq, ast.Lt,
    ast.LtE, ast.Gt, ast.GtE, ast.Is, ast.IsNot, ast.In, ast.NotIn,
})


class CodePolicyError(ValueError):
    """Source is outside the small orchestration language."""

    def __init__(self, message, *, node=None):
        super().__init__(message)
        # No source snippets, local paths or literal values enter this error.
        self.node_type = type(node).__name__ if node is not None else None
        self.lineno = getattr(node, "lineno", None)
        self.col_offset = getattr(node, "col_offset", None)

    def diagnostic(self):
        return {"type": "CodePolicyError", "rule": "bounded_python_source_policy",
                "message": str(self), "node_type": self.node_type,
                "line": self.lineno, "column": self.col_offset}


def validate_source(source: str) -> dict:
    """Check policy without execution; syntax failures are compiled in the guest."""
    if type(source) is not str or not source.strip():
        raise CodePolicyError("Source must be a nonempty string")
    if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise CodePolicyError("Source exceeds 16384 UTF-8 bytes")
    try:
        tree = ast.parse(source, filename="source.py", mode="exec")
    except SyntaxError:
        return {"valid": True, "syntax_error": True, "ast_nodes": None}
    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_AST_NODES:
        raise CodePolicyError("Source exceeds 2000 AST nodes")
    for node in nodes:
        if type(node) not in _NODES:
            raise CodePolicyError("Unsupported Python node: " + type(node).__name__, node=node)
        if isinstance(node, ast.Name):
            if node.id.startswith("_") or (isinstance(node.ctx, ast.Store)
                    and node.id in {*SAFE_BUILTINS, "tools"}):
                raise CodePolicyError("Private or reserved name", node=node)
        if isinstance(node, ast.Attribute):
            if node.attr.startswith("_"):
                raise CodePolicyError("Private attributes are forbidden", node=node)
            if isinstance(node.value, ast.Name) and node.value.id == "tools":
                if node.attr not in OPERATIONS:
                    raise CodePolicyError("Unknown frozen operation", node=node)
            elif node.attr not in _METHODS:
                raise CodePolicyError("Only bounded container methods are allowed", node=node)
            if not isinstance(node.ctx, ast.Load):
                raise CodePolicyError("Attribute mutation is forbidden", node=node)
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id not in SAFE_BUILTINS:
                    raise CodePolicyError("Only explicit safe builtins may be called", node=node)
            elif isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "tools":
                    if node.args or node.keywords:
                        raise CodePolicyError("Frozen operations take no arguments", node=node)
            else:
                raise CodePolicyError("Indirect calls are forbidden", node=node)
            if any(k.arg is None for k in node.keywords):
                raise CodePolicyError("Expanded keyword arguments are forbidden", node=node)
        if isinstance(node, ast.Constant):
            if not isinstance(node.value, (str, int, float, bool, type(None))):
                raise CodePolicyError("Only JSON-like literals are permitted", node=node)
            if isinstance(node.value, float) and not math.isfinite(node.value):
                raise CodePolicyError("Nonfinite literals are forbidden", node=node)
    return {"valid": True, "syntax_error": False, "ast_nodes": len(nodes)}


def _reject_constant(value):
    raise ValueError("Nonfinite JSON constant")


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate JSON key")
        value[key] = item
    return value


def encode_frame(value) -> bytes:
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False,
                     separators=(",", ":")).encode("utf-8")
    if len(raw) > MAX_FRAME_BYTES:
        raise ValueError("Protocol frame exceeds limit")
    return struct.pack("!I", len(raw)) + raw


def decode_payload(raw: bytes):
    if not raw or len(raw) > MAX_FRAME_BYTES:
        raise ValueError("Invalid frame length")
    return json.loads(raw.decode("utf-8"), parse_constant=_reject_constant,
                      object_pairs_hook=_pairs)


def _read_exact(stream, count):
    chunks = bytearray()
    while len(chunks) < count:
        part = stream.read(count - len(chunks))
        if not part:
            raise EOFError("Private parent channel closed")
        chunks.extend(part)
    return bytes(chunks)


def _read_frame(stream):
    length = struct.unpack("!I", _read_exact(stream, 4))[0]
    if not 0 < length <= MAX_FRAME_BYTES:
        raise ValueError("Invalid frame length")
    return decode_payload(_read_exact(stream, length))


class _BoundedLog(io.TextIOBase):
    def __init__(self):
        self.parts = []
        self.bytes = 0
        self.truncated = False

    def write(self, value):
        value = str(value)
        raw = value.encode("utf-8", errors="replace")
        keep = raw[:max(0, MAX_LOG_BYTES - self.bytes)]
        if keep:
            self.parts.append(keep.decode("utf-8", errors="ignore"))
        self.bytes += len(keep)
        self.truncated |= len(keep) < len(raw)
        return len(value)

    def getvalue(self):
        return "".join(self.parts)


def _project_result(candidate, run_ids, log):
    """Keep only the actual run selector; never traverse extra result values."""
    if (type(candidate) is not dict or type(candidate.get("run_id")) is not str
            or candidate["run_id"] not in run_ids):
        raise ValueError("result.run_id must be a string returned by this program's run_scrublet")
    ignored = len(candidate) - 1
    if ignored:
        # Constant-size sampling: no set(candidate), deepcopy, repr(value) or
        # JSON encoding of arbitrary guest values (including cycles/NaN/tools).
        names, sampled = [], 0
        for key in candidate:
            if type(key) is str and key == "run_id":
                continue
            if type(key) is str:
                names.append(key[:64])
            sampled += 1
            if sampled == 8:
                break
        log.write(json.dumps({"event": "ignored_untrusted_result_metadata",
            "ignored_field_count": ignored, "sampled_string_key_prefixes": names,
            "sampled_field_limit": 8, "key_prefix_char_limit": 64,
            "raw_values_retained": False}, ensure_ascii=True) + "\n")
    return {"run_id": candidate["run_id"]}


def _main():
    channel_in, channel_out = sys.stdin.buffer, sys.stdout.buffer
    log = _BoundedLog()
    initial = _read_frame(channel_in)
    if not isinstance(initial, dict) or set(initial) != {"v", "type", "source", "source_sha256"}:
        raise ValueError("Invalid bootstrap")
    if initial["v"] != 1 or initial["type"] != "bootstrap":
        raise ValueError("Invalid bootstrap version")
    source = initial["source"]
    if hashlib.sha256(source.encode("utf-8")).hexdigest() != initial["source_sha256"]:
        raise ValueError("Source digest mismatch")
    sequence = 0
    run_ids = set()

    def operation(name):
        nonlocal sequence
        sequence += 1
        if sequence > MAX_TOOL_MESSAGES:
            raise RuntimeError("Frozen-operation message limit exceeded")
        channel_out.write(encode_frame({"v": 1, "type": "tool_request", "seq": sequence,
                                        "operation": name}))
        channel_out.flush()
        reply = _read_frame(channel_in)
        if (not isinstance(reply, dict) or set(reply) != {"v", "type", "seq", "output"}
                or reply["v"] != 1 or reply["type"] != "tool_response"
                or reply["seq"] != sequence):
            raise RuntimeError("Invalid private tool response")
        output = reply["output"]
        if name == "run_scrublet" and isinstance(output, dict):
            run_id = output.get("run_id")
            if isinstance(run_id, str) and 0 < len(run_id) <= 256:
                run_ids.add(run_id)
        return output

    class Tools:
        def inspect_dataset(self):
            return operation("inspect_dataset")

        def run_scrublet(self):
            return operation("run_scrublet")

    namespace = {"__builtins__": dict(SAFE_BUILTINS), "tools": Tools()}
    status, output, error = "python_error", None, None
    try:
        validate_source(source)
        code = compile(source, "source.py", "exec")
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            exec(code, namespace, namespace)
        candidate = namespace.get("result")
        selected = _project_result(candidate, run_ids, log)
        # Serialize inside the guarded error boundary, without nonfinite values.
        json.dumps(selected, allow_nan=False)
        output, status = selected, "ok"
    except BaseException as exc:
        error = {"type": type(exc).__name__[:80], "message": str(exc)[:2000]}
        if isinstance(exc, CodePolicyError):
            status = "rejected"
    channel_out.write(encode_frame({"v": 1, "type": "final", "status": status,
        "output": output, "error": error, "log": log.getvalue(),
        "log_truncated": log.truncated, "tool_messages": sequence}))
    channel_out.flush()


if __name__ == "__main__":
    try:
        _main()
    except BaseException as exc:
        # Never write unframed data to the private channel.
        try:
            sys.stdout.buffer.write(encode_frame({"v": 1, "type": "protocol_error",
                "error": {"type": type(exc).__name__[:80], "message": str(exc)[:2000]}}))
            sys.stdout.buffer.flush()
        except BaseException:
            pass
        raise SystemExit(70)
