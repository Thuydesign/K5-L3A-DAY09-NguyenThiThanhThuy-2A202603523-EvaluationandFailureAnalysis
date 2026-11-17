"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item
from lab9.graders import GRADERS


def _ratchet_problems(current: dict, baseline: dict, *, label: str) -> list[str]:
    problems = []
    for key in ("min", "max", "max_increase"):
        old, new = baseline.get(key), current.get(key)
        if old is not None and (new is None or (new < old if key == "min" else new > old)):
            problems.append(f"{label}: loosened {key} threshold ({old!r} -> {new!r})")
    if baseline.get("no_significant_drop") and not current.get("no_significant_drop"):
        problems.append(f"{label}: removed no_significant_drop")
    if baseline.get("blocking") and not current.get("blocking"):
        problems.append(f"{label}: changed blocking metric to non-blocking")
    return problems


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []
    pr_metrics = pr.get("metrics")
    if not isinstance(pr_metrics, dict):
        problems.append("PR metrics must be an object")
        pr_metrics = {}
    if not isinstance(base.get("metrics"), dict):
        problems.append("baseline metrics must be an object")
    for metric, value in pr_metrics.items():
        if isinstance(value, (int, float)) and not math.isfinite(value):
            problems.append(f"metric {metric} is not finite")

    rows = pr.get("rows")
    if not isinstance(rows, list):
        problems.append("PR rows must be a list")
        rows = []
    base_rows = base.get("rows")
    if not isinstance(base_rows, list):
        problems.append("baseline rows must be a list")
        base_rows = []
    manifest = pr.get("manifest")
    if not isinstance(manifest, dict):
        problems.append("PR manifest must be an object")
        manifest = {}
    base_manifest = base.get("manifest")
    if not isinstance(base_manifest, dict):
        problems.append("baseline manifest must be an object")
        base_manifest = {}
    if not isinstance(manifest.get("eval_set_sha"), str) or not manifest["eval_set_sha"]:
        problems.append("PR manifest is missing eval_set_sha")
    if not isinstance(base_manifest.get("eval_set_sha"), str) or not base_manifest["eval_set_sha"]:
        problems.append("baseline manifest is missing eval_set_sha")
    seeds = manifest.get("seeds") or []
    item_count = manifest.get("items")
    if not isinstance(item_count, int) or isinstance(item_count, bool) or item_count < 1:
        problems.append("manifest items must be a positive integer")
    if (not isinstance(seeds, list) or not seeds
            or any(not isinstance(seed, int) or isinstance(seed, bool) for seed in seeds)):
        problems.append("manifest seeds must be a non-empty list of integers")
    elif len(set(seeds)) != len(seeds):
        problems.append("manifest seeds contain duplicates")
    if isinstance(item_count, int) and seeds and len(rows) != item_count * len(seeds):
        problems.append(f"row count {len(rows)} != manifest items x seeds ({item_count} x {len(seeds)})")

    def row_pairs(report_rows: list, report_name: str) -> tuple[list[tuple], set[tuple]]:
        pairs = []
        for index, row in enumerate(report_rows):
            if not isinstance(row, dict):
                problems.append(f"{report_name} row {index} is not an object")
                continue
            item, seed = row.get("item_id"), row.get("seed")
            if not isinstance(item, str) or not isinstance(seed, int) or isinstance(seed, bool):
                problems.append(f"{report_name} row {index} has invalid item_id or seed")
                continue
            pairs.append((item, seed))
        if len(set(pairs)) != len(pairs):
            problems.append(f"{report_name} has duplicate (item_id, seed) rows")
        return pairs, set(pairs)

    _, pr_set = row_pairs(rows, "PR")
    _, base_set = row_pairs(base_rows, "baseline")
    if pr_set != base_set:
        problems.append("(item_id, seed) set differs from baseline")

    if pr.get("evaluator_failures"):
        problems.append(f"{len(pr['evaluator_failures'])} evaluator failure(s)")
    graded_ids = {
        metric["id"] for metric in spec.get("metrics", [])
        if metric["id"] in GRADERS or metric.get("grader") == "code"
    }
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        for metric in graded_ids:
            if row.get(metric) is None:
                problems.append(f"row {index} has missing/None value for graded metric {metric}")
                break

    def slices_by_item(report_rows: list[dict]) -> dict:
        result = {}
        for row in report_rows:
            if not isinstance(row, dict):
                continue
            item_id = row.get("item_id")
            raw_tags = row.get("slices") or []
            if not isinstance(raw_tags, list) or any(not isinstance(tag, str) for tag in raw_tags):
                problems.append(f"item {item_id} has invalid slice tags")
                continue
            tags = tuple(sorted(raw_tags))
            if item_id in result and result[item_id] != tags:
                problems.append(f"item {item_id} has inconsistent slice tags")
            result.setdefault(item_id, tags)
        return result

    if slices_by_item(rows) != slices_by_item(base_rows):
        problems.append("item slice tags differ from baseline")

    if base_spec and spec.get("eval_set_version") == base_spec.get("eval_set_version"):
        old_metrics = {m["id"]: m for m in base_spec.get("metrics", [])}
        new_metrics = {m["id"]: m for m in spec.get("metrics", [])}
        for metric_id, old in old_metrics.items():
            if metric_id not in new_metrics:
                problems.append(f"ratchet: removed metric {metric_id}")
                continue
            new = new_metrics[metric_id]
            problems.extend(_ratchet_problems(
                {**(new.get("threshold") or {}), "blocking": new.get("blocking", False)},
                {**(old.get("threshold") or {}), "blocking": old.get("blocking", False)},
                label=f"ratchet metric {metric_id}",
            ))

        old_slices = {(s["name"], s["metric"]): s for s in base_spec.get("slices", [])}
        new_slices = {(s["name"], s["metric"]): s for s in spec.get("slices", [])}
        for slice_id, old in old_slices.items():
            if slice_id not in new_slices:
                problems.append(f"ratchet: removed slice {slice_id[0]}/{slice_id[1]}")
                continue
            problems.extend(_ratchet_problems(
                new_slices[slice_id], old, label=f"ratchet slice {slice_id[0]}/{slice_id[1]}"
            ))
    return problems


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked, lines = [], []
    bootstrap = spec.get("bootstrap", {})
    for entry in spec.get("slices", []):
        name, metric = entry["name"], entry["metric"]
        pr_items = per_item(pr, metric, slice_name=name)
        base_items = per_item(base, metric, slice_name=name)
        value = sum(pr_items.values()) / len(pr_items) if pr_items else None
        reasons = []
        delta_note = ""
        if value is None:
            reasons.append("no PR rows")
        elif "min" in entry and value < entry["min"]:
            reasons.append(f"{value:.3f} < min {entry['min']}")

        if entry.get("no_significant_drop"):
            keys = sorted(set(pr_items) & set(base_items))
            if not keys:
                reasons.append("no paired items")
            else:
                delta, lo, hi = stats.paired_bootstrap(
                    [pr_items[k] for k in keys],
                    [base_items[k] for k in keys],
                    n_resamples=bootstrap.get("n_resamples", 1000),
                    rng=bootstrap.get("rng", 2027),
                    confidence=bootstrap.get("confidence", 0.95),
                )
                delta_note = f"Δ {delta:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                if hi < 0:
                    reasons.append("significant drop")

        slice_id = f"slice:{name}/{metric}"
        if reasons and entry.get("blocking"):
            blocked.append(slice_id)
        status = "BLOCK" if reasons and entry.get("blocking") else "warn" if reasons else "ok"
        detail = "; ".join(reasons)
        lines.append(f"  {slice_id:<36} {value!s:<8} {delta_note:<28} {status}{': ' + detail if detail else ''}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    pr_manifest = pr.get("manifest")
    base_manifest = base.get("manifest")
    if not isinstance(pr_manifest, dict) or not isinstance(base_manifest, dict):
        return ["integrity"], ["  INTEGRITY report manifest must be an object"]
    pr_sha, base_sha = pr_manifest.get("eval_set_sha"), base_manifest.get("eval_set_sha")
    if not isinstance(pr_sha, str) or not isinstance(base_sha, str):
        return ["integrity"], ["  INTEGRITY report manifest is missing eval_set_sha"]
    if pr_sha != base_sha:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
