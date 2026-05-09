"""
Compatibility shim: convert pydantic-generated JSON Schemas into the subset
Gemini's function-calling API accepts. Gemini chokes on a few JSON Schema
features pydantic emits by default.

Removed/transformed:
  - `additionalProperties` (Gemini rejects unknown keys here).
  - `$ref` / `$defs` (Gemini needs inlined schemas).
  - `default` is fine; left in.
  - `examples` removed.
  - `title` removed (cosmetic).
  - `anyOf: [{type:..}, {type:"null"}]` collapses to plain type with
    `nullable: true`.
"""

from __future__ import annotations

import copy
from typing import Any


def _resolve_refs(schema: dict, defs: dict) -> Any:
    if isinstance(schema, dict):
        if "$ref" in schema:
            ref = schema["$ref"]
            # "#/$defs/Foo" -> defs["Foo"]
            name = ref.split("/")[-1]
            return _resolve_refs(copy.deepcopy(defs.get(name, {})), defs)
        return {k: _resolve_refs(v, defs) for k, v in schema.items()}
    if isinstance(schema, list):
        return [_resolve_refs(v, defs) for v in schema]
    return schema


_DROP_KEYS = {
    "additionalProperties",
    "title",
    "examples",
    "$schema",
    "$defs",
    # Gemini's JSON-Mode is brittle on length/value constraints; strip them
    # and rely on prompt instructions. The schema docstrings carry the intent.
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "pattern",
    "uniqueItems",
}


def _strip(schema: Any) -> Any:
    if isinstance(schema, dict):
        # Collapse anyOf:[{...}, {type:"null"}] -> nullable
        if "anyOf" in schema and isinstance(schema["anyOf"], list):
            non_null = [s for s in schema["anyOf"] if s.get("type") != "null"]
            null_present = any(s.get("type") == "null" for s in schema["anyOf"])
            if len(non_null) == 1 and null_present:
                merged = {**non_null[0], **{k: v for k, v in schema.items() if k != "anyOf"}}
                merged["nullable"] = True
                return _strip(merged)
        out = {}
        for k, v in schema.items():
            if k in _DROP_KEYS:
                continue
            out[k] = _strip(v)
        return out
    if isinstance(schema, list):
        return [_strip(v) for v in schema]
    return schema


def to_gemini_schema(json_schema: dict) -> dict:
    """Resolve $refs, drop unsupported keys, collapse nullable anyOfs."""
    defs = json_schema.get("$defs", {})
    resolved = _resolve_refs(copy.deepcopy(json_schema), defs)
    return _strip(resolved)
