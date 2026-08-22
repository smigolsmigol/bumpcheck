"""Project capture artifacts onto stable behavior and compare them."""

from __future__ import annotations

import json
from typing import Any


def _outcome_view(outcome: dict[str, Any], *, exact: bool) -> dict[str, Any]:
    if outcome["kind"] == "return":
        projected_outcome: dict[str, Any] = {"kind": "return", "value": outcome["value"]}
    elif outcome["kind"] == "batch":
        projected_outcome = {
            "items": [
                {
                    "index": item["index"],
                    "name": item["name"],
                    "outcome": _outcome_view(item["outcome"], exact=exact),
                }
                for item in outcome["items"]
            ],
            "kind": "batch",
        }
    elif outcome.get("pydantic_error_types") is not None:
        projected_outcome = {
            "kind": "exception",
            "pydantic_error_types": outcome["pydantic_error_types"],
        }
    else:
        projected_outcome = {"kind": "exception", "type": outcome["type"]}

    if exact and outcome["kind"] == "exception":
        projected_outcome["message"] = outcome["message"]
    return projected_outcome


def semantic_view(artifact: dict[str, Any], *, exact: bool = False) -> dict[str, Any]:
    outcome = artifact["outcome"]
    projected_outcome = _outcome_view(outcome, exact=exact)

    warning_categories = sorted(item["category"] for item in artifact["warnings"])
    value: dict[str, Any] = {
        "outcome": projected_outcome,
        "warning_categories": warning_categories,
    }
    if exact:
        value.update(
            {
                "stderr": artifact["stderr"],
                "stdout": artifact["stdout"],
                "warnings": artifact["warnings"],
            }
        )
    return value


def _batch_report(
    baseline_outcome: dict[str, Any], candidate_outcome: dict[str, Any]
) -> dict[str, Any] | None:
    if baseline_outcome["kind"] != "batch" or candidate_outcome["kind"] != "batch":
        return None

    baseline_items = baseline_outcome["items"]
    candidate_items = candidate_outcome["items"]
    if len(baseline_items) != len(candidate_items):
        raise ValueError("Batch artifacts contain different input counts")

    changes = []
    for baseline_item, candidate_item in zip(baseline_items, candidate_items, strict=True):
        baseline_identity = (baseline_item["index"], baseline_item["name"])
        candidate_identity = (candidate_item["index"], candidate_item["name"])
        if baseline_identity != candidate_identity:
            raise ValueError("Batch artifacts contain different input identities")
        if baseline_item["outcome"] != candidate_item["outcome"]:
            changes.append(
                {
                    "baseline": baseline_item["outcome"],
                    "candidate": candidate_item["outcome"],
                    "index": baseline_item["index"],
                    "name": baseline_item["name"],
                }
            )
    return {"changes": changes, "total": len(baseline_items)}


def compare(
    baseline: dict[str, Any], candidate: dict[str, Any], *, exact: bool = False
) -> dict[str, Any]:
    if baseline["case"]["sha256"] != candidate["case"]["sha256"]:
        raise ValueError("Artifacts were captured from different case bytes")
    if baseline.get("inputs") != candidate.get("inputs"):
        raise ValueError("Artifacts were captured from different input bytes")

    baseline_view = semantic_view(baseline, exact=exact)
    candidate_view = semantic_view(candidate, exact=exact)
    return {
        "baseline": baseline,
        "baseline_view": baseline_view,
        "batch": _batch_report(
            baseline_view["outcome"],
            candidate_view["outcome"],
        ),
        "candidate": candidate,
        "candidate_view": candidate_view,
        "changed": baseline_view != candidate_view,
        "exact": exact,
        "schema_version": 1,
    }


def describe_outcome(outcome: dict[str, Any]) -> str:
    if outcome["kind"] == "return":
        rendered = json.dumps(
            outcome["value"], ensure_ascii=True, sort_keys=True, separators=(",", ":")
        )
        return f"return {rendered[:120]}" + ("..." if len(rendered) > 120 else "")
    if outcome["kind"] == "batch":
        return f"batch[{len(outcome['items'])}]"
    error_types = outcome.get("pydantic_error_types")
    if error_types is not None:
        return f"ValidationError[{','.join(error_types)}]"
    return f"exception {outcome['type']}"
