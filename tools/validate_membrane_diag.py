"""Validate the artifact written by tools/diag_membrane_nan.py (D-136, R5 membrane part).

diag_membrane_nan.py intentionally returns 0 so that diagnostics are collected even when systems blow up; that exit
code proves nothing.  This separate validator answers two different questions and never mixes them:

  1. Is the artifact COMPLETE?  Expected number of builds and runs, no missing record, no build error, no truncated
     run, finished-marker present, protocol the one that was asked for.  A "no" exits non-zero.
  2. What was OBSERVED?  Failure (NaN) counts under the named protocol, split by construction (independent builds of
     the same membrane plan) and by velocity seed.  Counts are reported, never turned into a pass/fail verdict and
     never into a universal stability claim.

Exit codes: 0 = artifact complete (whatever the NaN counts are); 1 = missing / unreadable / incomplete artifact;
2 = command-line misuse.  Pure Python (json only); runs anywhere.

Usage:
  python tools/validate_membrane_diag.py DIAG_OUT_DIR_OR_diag.json [more ...]
         [--expect-builds N] [--expect-seeds 1,2,3] [--expect-steps 200] [--expect-long-min 5000]
         [--json OUT.json] [--markdown OUT.md]     (--markdown appends; use $GITHUB_STEP_SUMMARY in CI)

Expectations given on the command line win over the artifact's own "protocol" block; if they disagree the artifact
was produced under a different protocol than the one that was requested, which is itself a problem.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

SHORT_MIN_DEFAULT = 500
CHUNK_STEPS_DEFAULT = 10
DISCLAIMER = ("Observation under the named protocol only; this is neither a qualification nor a statement that "
              "membrane systems are stable or unstable in general.")


def _problem(code, where, message, severity="error"):
    return {"code": code, "severity": severity, "where": where, "message": message}


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _walk_numbers(x):
    if isinstance(x, bool):
        return
    if isinstance(x, (int, float)):
        yield x
    elif isinstance(x, (list, tuple)):
        for v in x:
            yield from _walk_numbers(v)
    elif isinstance(x, dict):
        for v in x.values():
            yield from _walk_numbers(v)


def resolve_expectations(report: dict, cli: dict | None):
    """CLI values win over the artifact's protocol block.  Returns (expect, problems)."""
    cli = {k: v for k, v in (cli or {}).items() if v is not None}
    proto = report.get("protocol") if isinstance(report.get("protocol"), dict) else {}
    recorded = {"builds": proto.get("builds_requested"), "seeds": proto.get("velocity_seeds"),
                "steps": proto.get("steps"), "long_min": proto.get("min_iter_long"),
                "short_min": proto.get("min_iter_short", SHORT_MIN_DEFAULT if proto else None),
                "chunk_steps": proto.get("chunk_steps", CHUNK_STEPS_DEFAULT if proto else None)}
    probs = []
    expect = {}
    for key in ("builds", "seeds", "steps", "long_min"):
        if key in cli and recorded.get(key) is not None and cli[key] != recorded[key]:
            probs.append(_problem("PROTOCOL_MISMATCH", "protocol",
                                  f"{key}: requested {cli[key]!r} but the artifact records {recorded[key]!r}"))
        expect[key] = cli.get(key, recorded.get(key))
    expect["short_min"] = cli.get("short_min", recorded.get("short_min") or SHORT_MIN_DEFAULT)
    expect["chunk_steps"] = recorded.get("chunk_steps") or CHUNK_STEPS_DEFAULT
    return expect, probs


def validate(report, cli_expect: dict | None = None) -> dict:
    """Pure function: `report` is the parsed diag.json (or None).  Returns a result dict (JSON-serialisable)."""
    problems: list[dict] = []
    res = {"complete": False, "problems": problems, "expected": {}, "counts": {}, "observed": {}, "protocol": {}}
    if not isinstance(report, dict):
        problems.append(_problem("ARTIFACT_UNREADABLE", "diag.json", "top level is not a JSON object"))
        return res
    proto = report.get("protocol") if isinstance(report.get("protocol"), dict) else None
    res["protocol"] = proto or {}
    builds = report.get("builds")
    if not isinstance(builds, list):
        problems.append(_problem("ARTIFACT_UNREADABLE", "builds", "no 'builds' list"))
        return res
    for key in ("openmm", "python"):
        if not report.get(key):
            problems.append(_problem("MISSING_FIELD", key, f"top-level '{key}' missing (environment not recorded)", "warning"))

    expect, probs = resolve_expectations(report, cli_expect)
    problems.extend(probs)
    res["expected"] = expect
    if proto is None:
        problems.append(_problem("LEGACY_ARTIFACT", "protocol",
                                 "no protocol block (written before D-136): completeness is judged only against the "
                                 "expectations given on the command line", "warning"))
        if report.get("finished") is not True:
            problems.append(_problem("NO_FINISH_MARKER", "finished",
                                     "legacy artifact has no finished marker: a run killed half-way looks the same", "warning"))
    elif report.get("finished") is not True:
        problems.append(_problem("NOT_FINISHED", "finished",
                                 "the diagnostic did not reach its end (killed, timed out or crashed): artifact is partial"))
    n_builds, seeds, steps = expect.get("builds"), expect.get("seeds"), expect.get("steps")
    long_min, short_min, chunk = expect.get("long_min"), expect.get("short_min"), expect.get("chunk_steps")
    missing_expect = [k for k, v in (("builds", n_builds), ("seeds", seeds), ("steps", steps), ("long_min", long_min)) if v is None]
    if missing_expect:
        problems.append(_problem("NO_EXPECTATION", "protocol",
                                 f"cannot judge completeness: no expected {', '.join(missing_expect)} (the artifact has no "
                                 "protocol block and none was given on the command line)"))
    if isinstance(n_builds, int) and n_builds < 1:
        problems.append(_problem("NO_BUILDS_EXPECTED", "protocol",
                                 "expected build count is below 1 (for a cross-OS run: the builds to run on were not found)"))

    # ---- per-build / per-run records
    expected_pairs = None
    if seeds and long_min is not None and short_min is not None:
        expected_pairs = {(short_min, s) for s in seeds} | {(long_min, seeds[0])}
    seen_idx: list = []
    run_rows = []          # (build index, run dict)
    build_rows = []
    for pos, b in enumerate(builds):
        if not isinstance(b, dict):
            problems.append(_problem("MALFORMED_BUILD", f"builds[{pos}]", "build record is not an object"))
            continue
        idx = b.get("build", pos)
        seen_idx.append(idx)
        where = f"build{idx}"
        if b.get("error"):
            first = str(b["error"]).strip().splitlines()[-1][:160] if str(b["error"]).strip() else ""
            problems.append(_problem("BUILD_ERROR", where, f"build or its runs raised: {first}"))
        else:
            for key in ("status", "xyz_sha", "n_atoms"):
                if b.get(key) in (None, ""):
                    problems.append(_problem("MISSING_FIELD", where, f"build record has no '{key}'"))
        runs = b.get("runs")
        if not isinstance(runs, list):
            runs = []
            if not b.get("error"):
                problems.append(_problem("MISSING_RUNS", where, "no 'runs' list"))
        got = {}
        for r in runs:
            if not isinstance(r, dict):
                problems.append(_problem("MALFORMED_RUN", where, "run record is not an object"))
                continue
            key = (r.get("min_iter"), r.get("seed"))
            if key in got:
                problems.append(_problem("DUPLICATE_RUN", where, f"min_iter={key[0]} seed={key[1]} recorded twice"))
            got[key] = r
            run_rows.append((idx, r))
        if expected_pairs is not None:
            for pair in sorted(expected_pairs - set(got)):
                problems.append(_problem("MISSING_RUN", where, f"expected run min_iter={pair[0]} seed={pair[1]} is absent"))
            for pair in sorted(set(got) - expected_pairs, key=str):
                problems.append(_problem("UNEXPECTED_RUN", where, f"run min_iter={pair[0]} seed={pair[1]} is not in the protocol", "warning"))
        build_rows.append(b)
    if isinstance(n_builds, int):
        want = set(range(n_builds))
        have = set(i for i in seen_idx if isinstance(i, int))
        for i in sorted(want - have):
            problems.append(_problem("MISSING_BUILD", f"build{i}", "expected build record is absent"))
        for i in sorted(have - want):
            problems.append(_problem("UNEXPECTED_BUILD", f"build{i}", "build index beyond the requested count", "warning"))
        if len(seen_idx) != len(set(seen_idx)):
            problems.append(_problem("DUPLICATE_BUILD", "builds", "a build index is recorded twice"))

    # ---- run content
    nan_runs, finite_runs, truncated = [], [], 0
    for idx, r in run_rows:
        where = f"build{idx} min={r.get('min_iter')} seed={r.get('seed')}"
        for key in ("min_iter", "seed", "fmax_after_min", "chunks", "seconds"):
            if key not in r:
                problems.append(_problem("MALFORMED_RUN", where, f"run record has no '{key}'"))
        if "nan_at_step" not in r:
            problems.append(_problem("MALFORMED_RUN", where, "run record has no 'nan_at_step' (cannot tell NaN from clean)"))
            continue
        chunks = r.get("chunks") if isinstance(r.get("chunks"), list) else []
        nan_step = r.get("nan_at_step")
        if nan_step:
            nan_runs.append((idx, r))
            if not r.get("error"):
                problems.append(_problem("MALFORMED_RUN", where, "NaN recorded without an error string", "warning"))
            if chunks and isinstance(chunks[-1], list) and chunks[-1] and _finite(chunks[-1][0]) and chunks[-1][0] >= nan_step:
                problems.append(_problem("MALFORMED_RUN", where, "chunk recorded at or after the NaN step"))
        else:
            finite_runs.append((idx, r))
            if r.get("error"):
                problems.append(_problem("MALFORMED_RUN", where, "error string without a NaN step: failure not attributed"))
            if isinstance(steps, int) and chunk:
                want_chunks = steps // chunk
                if len(chunks) != want_chunks:
                    truncated += 1
                    problems.append(_problem("TRUNCATED_RUN", where, f"{len(chunks)} of {want_chunks} chunks recorded without a NaN"))
            bad = [x for x in _walk_numbers([r.get("fmax_after_min"), r.get("pe_min"), r.get("chunks")]) if not _finite(x)]
            if bad:
                problems.append(_problem("NONFINITE_VALUE", where,
                                         f"{len(bad)} non-finite number(s) in a run recorded as clean (counted separately below)", "warning"))

    # ---- counts and observations
    errors = [p for p in problems if p["severity"] == "error"]
    res["complete"] = not errors
    n_expected_runs = (n_builds * len(expected_pairs)) if isinstance(n_builds, int) and expected_pairs else None
    res["counts"] = {"builds_expected": n_builds, "builds_recorded": len(builds), "runs_expected": n_expected_runs,
                     "runs_recorded": len(run_rows), "runs_clean": len(finite_runs), "runs_nan": len(nan_runs),
                     "runs_truncated": truncated, "errors": len(errors),
                     "warnings": len(problems) - len(errors)}
    res["observed"] = observe(build_rows, run_rows, short_min, long_min, seeds)
    return res


def observe(builds: list, run_rows: list, short_min, long_min, seeds) -> dict:
    """Descriptive failure counts.  No thresholds, no verdict."""
    def isnan(r):
        return bool(r.get("nan_at_step"))
    short = [(i, r) for i, r in run_rows if r.get("min_iter") == short_min]
    long_ = [(i, r) for i, r in run_rows if r.get("min_iter") == long_min and long_min != short_min]
    out = {"runs": len(run_rows), "nan": sum(1 for _, r in run_rows if isnan(r)),
           "short_minimisation": {"min_iter": short_min, "runs": len(short), "nan": sum(1 for _, r in short if isnan(r))},
           "long_minimisation": {"min_iter": long_min, "runs": len(long_), "nan": sum(1 for _, r in long_ if isnan(r))}}
    # construction: independent builds of the same plan
    cons = []
    for b in builds:
        if isinstance(b, dict):
            cons.append({"build": b.get("build"), "xyz_sha": b.get("xyz_sha"), "construction_seed": b.get("construction_seed"),
                         "source": b.get("source")})
    shas = {c["xyz_sha"] for c in cons if c["xyz_sha"]}
    cseeds = {c["construction_seed"] for c in cons}
    recorded_seeds = {s for s in cseeds if s is not None}
    out["construction"] = {
        "builds": len(cons), "distinct_start_structures": len(shas),
        "construction_seeds_recorded": sorted(recorded_seeds, key=str), "construction_seed_unrecorded": None in cseeds,
        "note": ("the construction seed was the same for every build, so differences between builds come from steps the "
                 "seed does not control (placement/packing/minimisation order)" if len(recorded_seeds) == 1 and len(shas) > 1
                 else "construction seed not varied or not recorded; builds compared as independent draws"),
    }
    # failures per build and per velocity seed (short-minimisation runs: same protocol as the original test)
    per_build: dict = {}
    for i, r in short:
        per_build.setdefault(i, {})[r.get("seed")] = isnan(r)
    builds_any = sorted(i for i, d in per_build.items() if any(d.values()))
    builds_all = sorted(i for i, d in per_build.items() if d and all(d.values()))
    mixed_within = sorted(i for i, d in per_build.items() if d and any(d.values()) and not all(d.values()))
    per_seed: dict = {}
    for i, r in short:
        per_seed.setdefault(r.get("seed"), {})[i] = isnan(r)
    seeds_mixed_across_builds = sorted((s for s, d in per_seed.items() if d and any(d.values()) and not all(d.values())), key=str)
    out["short_minimisation"]["by_build"] = {str(i): {"runs": len(d), "nan": sum(d.values())} for i, d in sorted(per_build.items())}
    out["short_minimisation"]["by_velocity_seed"] = {str(s): {"runs": len(d), "nan": sum(d.values())} for s, d in sorted(per_seed.items(), key=lambda kv: str(kv[0]))}
    out["variation"] = {
        "builds_with_any_nan": builds_any, "builds_with_all_seeds_nan": builds_all,
        "builds_where_outcome_depends_on_velocity_seed": mixed_within,
        "velocity_seeds_where_outcome_depends_on_build": seeds_mixed_across_builds,
        "reading": ("a build in which only some velocity seeds fail is velocity-seed sensitive; a velocity seed that fails in "
                    "some builds and not others is construction sensitive; a build failing for every seed points at the "
                    "construction itself.  Descriptive, with few runs; not a statistical test."),
    }
    nonfinite = 0
    for _, r in run_rows:
        if not isnan(r):
            nonfinite += sum(1 for x in _walk_numbers([r.get("fmax_after_min"), r.get("pe_min"), r.get("chunks")]) if not _finite(x))
    out["nonfinite_values_in_clean_runs"] = nonfinite
    return out


def _protocol_line(res: dict) -> str:
    e = res.get("expected", {})
    p = res.get("protocol", {})
    return (f"builds={e.get('builds')} velocity_seeds={e.get('seeds')} steps={e.get('steps')} "
            f"min_iter={e.get('short_min')}/{e.get('long_min')} from_builds={p.get('from_builds')} "
            f"construction_seed={p.get('construction_seed')}")


def render_text(path: str, res: dict) -> str:
    c, o = res["counts"], res["observed"]
    lines = [f"== {path}: {'COMPLETE' if res['complete'] else 'INCOMPLETE / INVALID'}"]
    if c:
        lines.append(f"protocol: {_protocol_line(res)}")
        lines.append(f"records: builds {c['builds_recorded']}/{c['builds_expected']}  runs {c['runs_recorded']}/{c['runs_expected']}  "
                     f"clean {c['runs_clean']}  NaN {c['runs_nan']}  truncated {c['runs_truncated']}  "
                     f"errors {c['errors']}  warnings {c['warnings']}")
    for p in res["problems"]:
        lines.append(f"  [{p['severity'].upper()}] {p['code']} @ {p['where']}: {p['message']}")
    if o:
        s, lg, v, cn = o["short_minimisation"], o["long_minimisation"], o["variation"], o["construction"]
        lines.append(f"observed NaN (not a verdict): {o['nan']}/{o['runs']} runs;  short minimisation ({s['min_iter']} it) "
                     f"{s['nan']}/{s['runs']};  long ({lg['min_iter']} it) {lg['nan']}/{lg['runs']}")
        lines.append(f"  construction: {cn['builds']} builds, {cn['distinct_start_structures']} distinct start structures, "
                     f"construction seeds {cn['construction_seeds_recorded'] or 'not recorded'}"
                     + (" (+ some unrecorded)" if cn["construction_seed_unrecorded"] and cn["construction_seeds_recorded"] else ""))
        lines.append(f"  velocity-seed variation: builds failing for some seeds only {v['builds_where_outcome_depends_on_velocity_seed']}; "
                     f"builds failing for every seed {v['builds_with_all_seeds_nan']}; "
                     f"seeds failing in some builds only {v['velocity_seeds_where_outcome_depends_on_build']}")
        if o["nonfinite_values_in_clean_runs"]:
            lines.append(f"  non-finite values inside runs recorded as clean: {o['nonfinite_values_in_clean_runs']}")
    lines.append(DISCLAIMER)
    return "\n".join(lines)


def render_markdown(path: str, res: dict) -> str:
    c, o = res["counts"], res["observed"]
    out = [f"### Membrane diagnostic artifact validation: `{path}` — {'complete' if res['complete'] else '**INCOMPLETE / INVALID**'}", ""]
    if c:
        out += [f"Protocol: `{_protocol_line(res)}`", "",
                "| builds | runs | clean | NaN | truncated | errors | warnings |", "|---|---|---|---|---|---|---|",
                f"| {c['builds_recorded']}/{c['builds_expected']} | {c['runs_recorded']}/{c['runs_expected']} | {c['runs_clean']} | "
                f"{c['runs_nan']} | {c['runs_truncated']} | {c['errors']} | {c['warnings']} |", ""]
    if res["problems"]:
        out += ["| severity | code | where | message |", "|---|---|---|---|"]
        out += [f"| {p['severity']} | {p['code']} | {p['where']} | {p['message']} |" for p in res["problems"]]
        out.append("")
    if o:
        s, lg, v = o["short_minimisation"], o["long_minimisation"], o["variation"]
        out += [f"Observed NaN: **{o['nan']}/{o['runs']}** runs (short minimisation {s['nan']}/{s['runs']}, long {lg['nan']}/{lg['runs']}). "
                f"Builds failing for some velocity seeds only: {v['builds_where_outcome_depends_on_velocity_seed']}; "
                f"builds failing for every seed: {v['builds_with_all_seeds_nan']}.", ""]
    out += [f"_{DISCLAIMER}_", ""]
    return "\n".join(out)


def load_artifact(path: str):
    """Returns (report_or_None, resolved_path, problems)."""
    p = Path(path)
    if p.is_dir():
        p = p / "diag.json"
    if not p.is_file():
        return None, str(p), [_problem("ARTIFACT_MISSING", str(p), "diag.json not found (the diagnostic did not write its artifact)")]
    try:
        return json.loads(p.read_text(encoding="utf-8")), str(p), []
    except (OSError, ValueError) as exc:
        return None, str(p), [_problem("ARTIFACT_UNREADABLE", str(p), f"cannot parse: {type(exc).__name__}: {str(exc)[:120]}")]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("artifacts", nargs="+", help="diag.json or the directory that holds it")
    ap.add_argument("--expect-builds", type=int, default=None)
    ap.add_argument("--expect-seeds", default=None, help="velocity seeds, e.g. 1,2,3")
    ap.add_argument("--expect-steps", type=int, default=None)
    ap.add_argument("--expect-long-min", type=int, default=None)
    ap.add_argument("--json", default=None, help="write all results here")
    ap.add_argument("--markdown", default=None, help="append a markdown summary here (e.g. $GITHUB_STEP_SUMMARY)")
    a = ap.parse_args(argv)
    try:
        seeds = [int(s) for s in a.expect_seeds.split(",") if s.strip()] if a.expect_seeds else None
    except ValueError:
        ap.error("--expect-seeds must be a comma-separated list of integers")
    cli = {"builds": a.expect_builds, "seeds": seeds, "steps": a.expect_steps, "long_min": a.expect_long_min}
    results, ok = {}, True
    for art in a.artifacts:
        report, resolved, probs = load_artifact(art)
        if report is None:
            res = {"complete": False, "problems": probs, "expected": {}, "counts": {}, "observed": {}, "protocol": {}}
        else:
            res = validate(report, cli)
        results[resolved] = res
        ok = ok and res["complete"]
        print(render_text(resolved, res), flush=True)
    if a.json:
        Path(a.json).write_text(json.dumps({"complete": ok, "disclaimer": DISCLAIMER, "artifacts": results}, indent=1, ensure_ascii=False),
                                encoding="utf-8")
    if a.markdown:
        with open(a.markdown, "a", encoding="utf-8") as f:
            for path, res in results.items():
                f.write(render_markdown(path, res) + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
