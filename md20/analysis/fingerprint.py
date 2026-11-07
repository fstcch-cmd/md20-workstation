"""Analysis cache fingerprint, reuse decision and atomic regeneration (D-135, R4; docs/specs/analysis_cache.md).

Before: `Workflow.analyse` reused a run's analysis whenever `analysis_manifest.json` said PASS.  A manifest written by an
older version (without the newer qualification fields), computed from a replaced topology, other selections or other
thresholds was reused as if it were current.

Here:
  analysis_fingerprint(...)   every input that can change the per-run analysis, as a flat {component: digest} map
                              (+ one overall digest).  Cheap: trajectories are identified by size + head/tail hash (the
                              engine's own `cheap_fingerprint`, cross-checked with the chunk hashes recorded when the
                              stage ran), never re-hashed in full.
  reuse_decision(run_dir, fp) reuse / recompute with the reason, the changed components and the affected parts; a
                              legacy manifest (no fingerprint), a missing or modified output → recompute.
  begin_staging / commit_staging / write_manifest_atomic
                              new outputs are written to a staging directory and swapped in; the previous manifest and
                              outputs are kept (`analysis_manifest.prev.json`, `prev/`) with provenance; an interrupted swap
                              is rolled back, so a complete result is never replaced by a partial one.
Recomputing analysis never reruns MD.  Pure Python (no mdtraj).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Callable

from ..util import atomic_write_json, load_json, now_iso
from ..util.hashing import cheap_fingerprint, sha256_file

ANALYSIS_VERSION = "2026-11-07.1"          # bump when ANY per-run analysis output changes meaning or gains required fields
FINGERPRINT_SCHEMA = "md20.analysis_fingerprint/1"

# which output groups each component can invalidate ("core" = metrics/figures/centred export, "extended" = extended.json,
# "assessment" = scientific assessment thresholds).  Reported in reuse_decision; analyse_run currently recomputes the
# whole per-run analysis whenever any part is stale.
GLOBAL_COMPONENTS = {"analysis_version"}
EXTENDED_ONLY = {"extended_schema", "persistence_schema", "interactions_schema", "extended_thresholds"}
ASSESSMENT_ONLY = {"assessment_thresholds_version"}

_OUTPUT_FILE_KEYS = ("metrics_file", "extended_file")      # + any other `*_file` string value in the manifest
STAGING_PREFIX = ".staging-"
JOURNAL = ".swap_journal.json"
PREV_DIR = "prev"
PREV_MANIFEST = "analysis_manifest.prev.json"


def _digest(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str, ensure_ascii=False).encode("utf-8")).hexdigest()


def _norm_charges(ch: dict | None):
    if ch is None:
        return None
    return {str(k): {str(i): int(s) for i, s in sorted(v.items(), key=lambda kv: int(kv[0]))} for k, v in sorted(ch.items())}


def _norm_groups(g: dict | None):
    if g is None:
        return None
    return {str(k): sorted(int(i) for i in v) for k, v in sorted(g.items())}


def _file_component(path: Path | str | None) -> str:
    if not path:
        return "none"
    p = Path(path)
    if not p.is_file():
        return "missing"
    return "sha256:" + sha256_file(p)


def _trajectory_components(run_dir: Path) -> tuple[dict, dict]:
    """(components, details).  DCD identity = size + head/tail hash of the file as it is NOW; the chunk hashes recorded
    when the stage ran (`production_progress.json`) are compared and a mismatch is listed in details (never silently
    trusted).  mtime is recorded but does not enter the digest (a copied project keeps its content)."""
    stage = run_dir / "stages" / "production"
    comp = load_json(stage / "production_complete.json", {})
    res = comp.get("result") or {}
    prog = load_json(stage / "production_progress.json", {})
    recorded = {}
    for row in prog.get("chunks") or []:
        rec = (row.get("artifacts") or {}).get("dcd")
        if rec and rec.get("path"):
            recorded[Path(rec["path"]).name] = rec
    comps, det = {}, {"dcd": {}, "recorded_mismatch": []}
    for i, d in enumerate(res.get("dcd_paths") or []):
        p = Path(d)
        key = f"dcd:{i:04d}:{p.name}"
        if not p.is_file():
            comps[key] = "missing"
            det["dcd"][key] = {"missing": True}
            continue
        cur = cheap_fingerprint(p)
        comps[key] = f"{cur['bytes']}:{cur['edge_sha256']}"
        det["dcd"][key] = {"bytes": cur["bytes"], "mtime_ns": cur["mtime_ns"], "edge_sha256": cur["edge_sha256"]}
        rec = recorded.get(p.name)
        if rec and (int(rec.get("bytes", -1)) != cur["bytes"] or rec.get("edge_sha256") != cur["edge_sha256"]):
            det["recorded_mismatch"].append(p.name)
            comps[key] += ":differs_from_chunk_manifest"
    comps["production_state_sha256"] = str(comp.get("state_sha256") or "not_recorded")
    comps["production_record"] = _digest({"steps": res.get("steps"), "timestep_fs": comp.get("timestep_fs"),
                                          "dcd_atoms": (comp.get("backend_info") or {}).get("dcd_atoms"),
                                          "dcd_atom_count": (comp.get("backend_info") or {}).get("dcd_atom_count"),
                                          "n_dcd": len(res.get("dcd_paths") or [])})
    return comps, det


def _code_versions() -> tuple[dict, dict]:
    """Schema/threshold versions of the code that makes the analysis (imports are lazy and failure-tolerant)."""
    comps: dict = {"analysis_version": ANALYSIS_VERSION}
    thr: dict = {}
    from . import persistence as PS
    from . import interactions as IX
    from . import extended as EX
    comps["persistence_schema"] = PS.SCHEMA
    comps["interactions_schema"] = f"{IX.SCHEMA}|{IX.CUTOFF_SOURCE}"
    comps["extended_schema"] = EX.EXTENDED_SCHEMA
    thr["extended"] = {"MAX_FRAMES": EX.MAX_FRAMES, "HB_DIST_NM": EX.HB_DIST_NM, "HYDROPHOBIC_NM": EX.HYDROPHOBIC_NM,
                       "IONIC_NM": EX.IONIC_NM, "WATER_BRIDGE_NM": EX.WATER_BRIDGE_NM, "CUTOFF_NM": IX.CUTOFF_NM,
                       "sensitivity": EX.SENSITIVITY_TOLERANCES}
    comps["extended_thresholds"] = _digest(thr["extended"])
    try:
        from .traj import LIGAND_STATE_THRESHOLDS
        thr["ligand_state"] = LIGAND_STATE_THRESHOLDS
        comps["ligand_state_thresholds"] = _digest(LIGAND_STATE_THRESHOLDS)
    except Exception as exc:  # noqa: BLE001 — a missing plotting stack must not stop the fingerprint
        comps["ligand_state_thresholds"] = f"unavailable:{type(exc).__name__}"
    try:
        from ..sampling.assessment import THRESHOLDS_VERSION
        comps["assessment_thresholds_version"] = THRESHOLDS_VERSION
    except Exception as exc:  # noqa: BLE001
        comps["assessment_thresholds_version"] = f"unavailable:{type(exc).__name__}"
    return comps, thr


def analysis_fingerprint(run_dir: Path | str, topology_pdb: Path | str | None, *, ligand_groups: dict | None = None,
                         metal_indices: list[int] | None = None, ligand_charges: dict | None = None, membrane: bool = False,
                         extra: dict | None = None) -> dict:
    """Everything the per-run analysis depends on.  Arguments are the ORIGINAL full-system values handed to
    `analyse_run` (before any solute remapping).  Returns {"schema", "analysis_version", "digest", "components",
    "thresholds", "details"}; `components` is a flat {name: str} map so `reuse_decision` can name what changed."""
    run_dir = Path(run_dir)
    comps, thr = _code_versions()
    traj_comps, det = _trajectory_components(run_dir)
    comps.update(traj_comps)
    comps["topology"] = _file_component(topology_pdb)
    comps["selections"] = _digest({"ligand_groups": _norm_groups(ligand_groups), "metal_indices": sorted(int(i) for i in metal_indices)
                                   if metal_indices is not None else None, "ligand_charges": _norm_charges(ligand_charges),
                                   "membrane": bool(membrane)})
    rj = load_json(run_dir / "run.json", {})
    proto = rj.get("protocol")
    comps["protocol"] = str(rj.get("protocol_hash") or (_digest(proto) if proto is not None else "not_recorded"))
    # auto-stride depends on the memory budget: the same run analysed with another budget has another effective resolution
    comps["analysis_memory_gb"] = str(os.environ.get("MD20_ANALYSIS_MEM_GB", "default"))
    for k, v in sorted((extra or {}).items()):
        comps[f"extra:{k}"] = _digest(v)
    return {"schema": FINGERPRINT_SCHEMA, "analysis_version": ANALYSIS_VERSION, "digest": _digest(comps), "components": comps,
            "thresholds": thr, "details": det}


def parts_for(changed: list[str]) -> list[str]:
    """Output groups a set of changed components affects: "core" (metrics, figures, centred export), "extended",
    "assessment"."""
    parts: set[str] = set()
    for k in changed:
        if k in GLOBAL_COMPONENTS or k in ("topology", "selections", "protocol", "production_record", "production_state_sha256",
                                           "analysis_memory_gb", "ligand_state_thresholds") or k.startswith(("dcd:", "extra:")):
            parts |= {"core", "extended"}
        elif k in EXTENDED_ONLY:
            parts.add("extended")
        elif k in ASSESSMENT_ONLY:
            parts.add("assessment")
        else:
            parts |= {"core", "extended"}           # an unknown component: be conservative
    return [p for p in ("core", "extended", "assessment") if p in parts]


# ------------------------------------------------------------------------------------------------ reuse decision
def _referenced_files(man: dict) -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []
    for k, v in man.items():
        if k.endswith("_file") and isinstance(v, str) and v:
            refs.append((k, v))
    for name, v in (man.get("figures") or {}).items():
        for fmt, path in (v.items() if isinstance(v, dict) else [("", v)]):
            if isinstance(path, str) and path:
                refs.append((f"figures.{name}{'.' + fmt if fmt else ''}", path))
    return refs


def reuse_decision(run_dir: Path | str, fp: dict) -> dict:
    """May the stored analysis of `run_dir` be reused for fingerprint `fp`?

    Returns {"reuse": bool, "reason": …, "changed": [component names], "recompute_parts": […], "missing": […],
    "modified": […], "notes": […], "manifest_analysis_version": …}.  `reason` is one of
    "unchanged", "no_manifest", "not_pass", "legacy", "missing_files", "output_modified", "changed".
    Calling it first completes the rollback of an interrupted swap (recover_interrupted)."""
    run_dir = Path(run_dir)
    adir = run_dir / "analysis"
    notes = recover_interrupted(run_dir)
    out = {"reuse": False, "reason": "", "changed": [], "recompute_parts": [], "missing": [], "modified": [], "notes": notes,
           "manifest_analysis_version": None, "current_digest": fp.get("digest")}
    mpath = adir / "analysis_manifest.json"
    man = load_json(mpath, None) if mpath.is_file() else None
    if not isinstance(man, dict) or not man:
        out["reason"] = "no_manifest"
        out["recompute_parts"] = ["core", "extended"]
        return out
    out["manifest_analysis_version"] = man.get("analysis_version")
    if man.get("status") != "PASS":
        out["reason"] = "not_pass"
        out["recompute_parts"] = ["core", "extended"]
        return out
    old = man.get("fingerprint")
    if not isinstance(old, dict) or not isinstance(old.get("components"), dict):
        out["reason"] = "legacy"
        out["notes"].append("manifest written before analysis fingerprints existed; its results lack the newer "
                            "resolution/qualification fields and are not reused")
        out["recompute_parts"] = ["core", "extended"]
        return out
    oc, nc = old["components"], fp.get("components") or {}
    out["changed"] = sorted(k for k in set(oc) | set(nc) if oc.get(k) != nc.get(k))
    out["recompute_parts"] = parts_for(out["changed"]) if out["changed"] else []
    out["missing"] = sorted(k for k, p in _referenced_files(man) if not Path(p).is_file()
                            or (Path(p).stat().st_size == 0 and not k.startswith("figures.")))
    sums = man.get("outputs") or {}
    for name, rec in sums.items():
        p = adir / name
        if not p.is_file():
            if name not in out["missing"]:
                out["missing"].append(name)
        elif sha256_file(p) != rec.get("sha256"):
            out["modified"].append(name)
    if out["missing"]:
        out["reason"] = "missing_files"
        out["recompute_parts"] = out["recompute_parts"] or ["core", "extended"]
    elif out["modified"]:
        out["reason"] = "output_modified"
        out["recompute_parts"] = out["recompute_parts"] or ["core", "extended"]
    elif out["changed"]:
        out["reason"] = "changed"
    else:
        out["reuse"], out["reason"] = True, "unchanged"
    return out


# ------------------------------------------------------------------------------------------------ atomic regeneration
def begin_staging(run_dir: Path | str) -> Path:
    """New staging directory under analysis/ for the JSON/NPY outputs of one regeneration.  Stale staging directories
    from interrupted earlier attempts are removed first (they were never swapped in)."""
    adir = Path(run_dir) / "analysis"
    adir.mkdir(parents=True, exist_ok=True)
    for old in adir.glob(f"{STAGING_PREFIX}*"):
        shutil.rmtree(old, ignore_errors=True)
    st = adir / f"{STAGING_PREFIX}{uuid.uuid4().hex[:10]}"
    st.mkdir()
    return st


def recover_interrupted(run_dir: Path | str) -> list[str]:
    """If a swap was interrupted (journal present), put the previous outputs back from analysis/prev/.  Idempotent."""
    adir = Path(run_dir) / "analysis"
    jp = adir / JOURNAL
    if not jp.is_file():
        return []
    notes = []
    j = load_json(jp, {}) or {}
    live = load_json(adir / "analysis_manifest.json", {}) or {}
    if j.get("new_commit_id") and live.get("commit_id") == j["new_commit_id"]:
        for st in adir.glob(f"{STAGING_PREFIX}*"):               # the manifest (written last) is the new one: swap completed
            shutil.rmtree(st, ignore_errors=True)
        jp.unlink(missing_ok=True)
        return ["a completed regeneration had left its journal behind; cleaned up"]
    for name in j.get("files") or []:
        prev = adir / PREV_DIR / name
        if prev.is_file():
            shutil.copy2(prev, adir / f".{name}.restore")
            os.replace(adir / f".{name}.restore", adir / name)
        elif name in (j.get("new_files") or []):
            (adir / name).unlink(missing_ok=True)          # a file the interrupted swap created and the old result never had
    for st in adir.glob(f"{STAGING_PREFIX}*"):
        shutil.rmtree(st, ignore_errors=True)
    jp.unlink(missing_ok=True)
    notes.append("an interrupted regeneration was rolled back; the previous complete analysis is intact")
    return notes


def commit_staging(run_dir: Path | str, staging: Path | str, manifest: dict, *, fingerprint: dict,
                   provenance: dict | None = None, _hook: Callable[[str, str], None] | None = None) -> dict:
    """Swap the staged outputs in and write the manifest LAST.

    Order: (1) hash the staged files, write the new manifest into staging; (2) copy the current outputs and manifest to
    analysis/prev/ and analysis_manifest.prev.json (with provenance); (3) journal; (4) os.replace every staged file;
    (5) os.replace the manifest; (6) drop journal and staging.  A failure in (4)/(5) leaves the journal, and the next
    `reuse_decision`/`recover_interrupted` restores the previous outputs.  `_hook(stage, name)` is a test seam.
    Returns the final manifest."""
    run_dir, staging = Path(run_dir), Path(staging)
    adir = run_dir / "analysis"
    hook = _hook or (lambda stage, name: None)
    names = sorted(p.name for p in staging.iterdir() if p.is_file() and not p.name.startswith("analysis_manifest"))
    outputs = {n: {"sha256": sha256_file(staging / n), "bytes": (staging / n).stat().st_size} for n in names}
    final = {**manifest, "fingerprint": {k: v for k, v in fingerprint.items() if k != "details"},
             "fingerprint_details": fingerprint.get("details"), "analysis_version": fingerprint.get("analysis_version", ANALYSIS_VERSION),
             "outputs": outputs, "committed_at": now_iso(), "commit_id": uuid.uuid4().hex, "provenance": {**(provenance or {}), "run_dir": str(run_dir)}}
    atomic_write_json(final, staging / "analysis_manifest.json", backup=False)
    old_man = adir / "analysis_manifest.json"
    prev = adir / PREV_DIR
    new_files = [n for n in names if not (adir / n).is_file()]
    prev.mkdir(parents=True, exist_ok=True)
    for n in names:
        if (adir / n).is_file():
            shutil.copy2(adir / n, prev / n)
    if old_man.is_file():
        old = load_json(old_man, {}) or {}
        old["superseded"] = {"at": now_iso(), "by_digest": fingerprint.get("digest"),
                             "by_analysis_version": final["analysis_version"], "legacy": "fingerprint" not in old,
                             "reason": (provenance or {}).get("reason", "regenerated"),
                             "outputs_kept_in": str(prev)}
        atomic_write_json(old, adir / PREV_MANIFEST, backup=False)
    atomic_write_json({"files": names + ["analysis_manifest.json"], "new_files": new_files, "started_at": now_iso(),
                       "new_commit_id": final["commit_id"]},
                      adir / JOURNAL, backup=False)
    for n in names:
        hook("replace", n)
        os.replace(staging / n, adir / n)
    hook("replace", "analysis_manifest.json")
    os.replace(staging / "analysis_manifest.json", adir / "analysis_manifest.json")
    (adir / JOURNAL).unlink(missing_ok=True)
    shutil.rmtree(staging, ignore_errors=True)
    return final


def write_manifest_atomic(run_dir: Path | str, manifest: dict, *, fingerprint: dict, outputs: dict | None = None,
                          staging: Path | str | None = None, provenance: dict | None = None,
                          _hook: Callable[[str, str], None] | None = None) -> dict:
    """Convenience over begin_staging/commit_staging: `outputs` = {file name: JSON-able object} are written into the
    staging directory (or into the one given), then everything is committed together with `manifest`."""
    st = Path(staging) if staging is not None else begin_staging(run_dir)
    for name, obj in (outputs or {}).items():
        atomic_write_json(obj, st / name, backup=False)
    return commit_staging(run_dir, st, manifest, fingerprint=fingerprint, provenance=provenance, _hook=_hook)
