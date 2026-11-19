"""Self-check record form, host-answer merge, label conversion, path rewriting."""

from __future__ import annotations

import copy
from typing import Any

VERDICTS = ("pass", "flag", "unknown")
CONFIDENCES = ("high", "medium", "low")
_TO_TOOL_VERDICT = {"pass": "pass", "flag": "fail", "unknown": "cannot_tell"}


class MergeError(ValueError):
    pass


def self_check_record(result: dict[str, Any]) -> dict[str, Any]:
    """The form a host sends with ``record_self_check``.

    ``verdicts`` fits today's tool contract (pass / fail / cannot_tell);
    ``items`` carries the extended per-item record (measurements, tool and
    version, evidence media, source) with ``recalled`` left empty for the host
    to fill with the krefs of QC memories it used.
    """
    items = result.get("items", [])
    verdicts = []
    extended = []
    for it in items:
        reason = it.get("note", "")
        if it["verdict"] == "unknown" and it.get("needs"):
            reason = f"[{it['needs']}] {reason}"
        verdicts.append({"item_id": it["item_id"], "verdict": _TO_TOOL_VERDICT[it["verdict"]], "reason": reason[:4000]})
        ev = it.get("evidence", {})
        extended.append(
            {
                "item_id": it["item_id"],
                "kind": it["kind"],
                "verdict": it["verdict"],
                "confidence": it["confidence"],
                "measurements": ev.get("measurements", {}),
                "frame_times_s": ev.get("frame_times_s", []),
                "evidence_media": ev.get("media", []),
                "tool": it.get("tool", {}),
                "source": it.get("source", "server"),
                "note": it.get("note", ""),
                "recalled": list(it.get("recalled", [])),
            }
        )
    tools = {result["tool"]["name"]: result["tool"]["version"], **(result["tool"].get("components") or {})}
    for it in items:
        t = it.get("tool") or {}
        if t.get("name") and t["name"] not in tools:
            tools[t["name"]] = t.get("version")
    passed = bool(items) and all(it["verdict"] == "pass" for it in items)
    flagged = [it["item_id"] for it in items if it["verdict"] == "flag"]
    open_items = [it["item_id"] for it in items if it["verdict"] == "unknown"]
    notes = (
        f"take-qc: {len(flagged)} flagged ({', '.join(flagged) or 'none'}), "
        f"{len(open_items)} unknown ({', '.join(open_items) or 'none'})"
    )
    return {
        "passed": passed,
        "notes": notes[:4000],
        "verdicts": verdicts,
        "items": extended,
        "tool_versions": tools,
        "recalled": [],
    }


def merge(result: dict[str, Any], answers: Any, allow_override: bool = False) -> dict[str, Any]:
    """Fill ``unknown`` items with the host's answers and rebuild the record.

    ``answers`` is a list (or ``{"items": [...]}``) of items in the same shape:
    ``item_id`` (or ``kind``), ``verdict``, ``confidence``, ``evidence``,
    ``note``, ``tool`` (``{"name": "host-vision:<model>"}``) and optional
    ``recalled`` krefs. Measured items are not overwritten unless
    ``allow_override``.
    """
    if isinstance(answers, dict):
        answers = answers.get("items", [])
    if not isinstance(answers, list):
        raise MergeError("answers must be a list of items or {'items': [...]}")
    out = copy.deepcopy(result)
    by_id = {it["item_id"]: it for it in out["items"]}
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for it in out["items"]:
        by_kind.setdefault(it["kind"], []).append(it)
    for ans in answers:
        targets: list[dict[str, Any]]
        if ans.get("item_id") in by_id:
            targets = [by_id[ans["item_id"]]]
        elif ans.get("kind") in by_kind and not ans.get("item_id"):
            targets = by_kind[ans["kind"]]
        else:
            raise MergeError(f"answer names no known item: {ans.get('item_id') or ans.get('kind')!r}")
        if ans.get("verdict") not in VERDICTS:
            raise MergeError(f"verdict must be one of {VERDICTS}: {ans.get('verdict')!r}")
        conf = ans.get("confidence", "medium")
        if conf not in CONFIDENCES:
            raise MergeError(f"confidence must be one of {CONFIDENCES}: {conf!r}")
        tool = ans.get("tool") or {}
        if not tool.get("name"):
            raise MergeError("every answer needs tool.name, e.g. 'host-vision:<model>'")
        for it in targets:
            if it["verdict"] != "unknown" and not allow_override:
                raise MergeError(
                    f"item {it['item_id']} was measured ({it['verdict']}); pass allow_override to replace it"
                )
            it["verdict"] = ans["verdict"]
            it["confidence"] = conf
            it["evidence"] = ans.get("evidence", {})
            it["note"] = ans.get("note", "")
            it["tool"] = {"name": tool["name"], "version": tool.get("version", "")}
            it["recalled"] = list(ans.get("recalled", []))
            it.pop("needs", None)
    out["self_check"] = self_check_record(out)
    return out


def to_label(item: dict[str, Any]) -> dict[str, Any]:
    """An item as a take-label (fixtures/qc schema) entry."""
    label: dict[str, Any] = {
        "verdict": item["verdict"],
        "confidence": item["confidence"],
        "labeled_by": "agent-draft",
        "confirmed": False,
    }
    if item.get("evidence"):
        label["evidence"] = item["evidence"]
    note = item.get("note", "")
    tool = item.get("tool") or {}
    if tool:
        note = f"{note} [{tool.get('name')} {tool.get('version', '')}]".strip()
    label["note"] = note
    if item.get("source") in ("server", "decision", "memory", "label-set"):
        label["source"] = item["source"]
    if item.get("recalled"):
        label["recalled"] = item["recalled"]
    return label


def rewrite_paths(obj: Any, mapping: dict[str, str]) -> Any:
    """Replace host-local path prefixes with ``${VAR}``: ``{"QC_ROOT": "D:/media"}``."""
    norm = sorted(((v.replace("\\", "/").rstrip("/"), k) for k, v in mapping.items()), key=lambda p: -len(p[0]))

    def fix(s: str) -> str:
        s2 = s.replace("\\", "/")
        for prefix, var in norm:
            if s2.lower().startswith(prefix.lower() + "/"):
                return "${" + var + "}" + s2[len(prefix) :]
        return s

    if isinstance(obj, str):
        return fix(obj)
    if isinstance(obj, list):
        return [rewrite_paths(x, mapping) for x in obj]
    if isinstance(obj, dict):
        return {k: rewrite_paths(v, mapping) for k, v in obj.items()}
    return obj
