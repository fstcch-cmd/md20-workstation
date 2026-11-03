"""Membrane analysis of a finished run (docs/specs/membrane.md §5, §6), as wired by the workflow.

`assess_equilibration` was designed to run after NPT and extend NPT once.  Doing that needs the engine to stop between
stages and read a trajectory, which would be a new step (development rule: no new phase or step).  So the workflow
uses it **after production, as an analysis only**: the acceptance is computed on the second half of the production
trajectory, nothing is extended, and a failed acceptance becomes a notice on the gate cards and in the report.
Recorded in docs/specs/gui_v2.md (D-80 integration section).

`membrane_summary` is pure numpy (tested here); `analyse_membrane_run` reads the DCD with mdtraj (CI and laptop).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from ..build.gates import Gate, PASS, AUTO_FIXED
from ..util import atomic_write_json, load_json, now_iso
from .membrane import thickness_pp, area_per_lipid, water_in_core, insertion_depth, assess_equilibration

WATER_RESNAMES = {"HOH", "WAT", "TIP3", "SOL", "T3P"}


def membrane_summary(xyz, box, *, head_idx, water_o_idx=None, solute_groups: dict | None = None,
                     reference: dict | None = None, has_protein: bool = False, protein_idx=None) -> dict:
    """xyz (F, N, 3) nm, box (F, 3) nm.  Returns plain numbers for metrics.json and the acceptance gate (dict).

    Acceptance uses the second half of the frames.  With a protein the area per lipid is not checked (the protein
    cross-section is not estimated yet).  Without water in the trajectory (solute-only DCD) the acceptance is not
    computed and the summary says so."""
    xyz = np.asarray(xyz, float)
    box = np.asarray(box, float)
    F = len(xyz)
    head_idx = list(head_idx or [])
    if F == 0 or not head_idx:
        return {"status": "SKIPPED", "why": "軌跡沒有幀或找不到脂質頭基原子，膜分析沒有執行。"}
    head = xyz[:, head_idx]
    th = thickness_pp(head, box)
    half = slice(F // 2, None)
    out = {"n_frames": F, "n_lipids": len(head_idx), "n_upper": th["n_upper"], "n_lower": th["n_lower"],
           "dpp_nm": [round(float(v), 4) for v in th["dpp_nm"]], "dpp_mean_nm": round(float(th["dpp_nm"][half].mean()), 4)}
    apl_mean = None
    if not has_protein and th["n_upper"] and th["n_lower"]:
        apl = area_per_lipid(box, th["n_upper"], th["n_lower"])
        out["apl_nm2"] = [round(float(v), 4) for v in apl["apl_nm2"]]
        apl_mean = float(apl["apl_nm2"][half].mean())
        out["apl_mean_nm2"] = round(apl_mean, 4)
    for name, idx in (solute_groups or {}).items():
        if idx:
            d = insertion_depth(xyz[:, list(idx)], head, box)
            out.setdefault("insertion", {})[name] = {
                "com_depth_nm": [round(float(v), 4) for v in d["com_depth_nm"]],
                "mean_com_depth_nm": round(float(d["com_depth_nm"][half].mean()), 4),
                "mean_deepest_nm": round(float(d["deepest_nm"][half].mean()), 4),
                "crossed_centre": d["crossed_centre"]}
    if water_o_idx is None or len(water_o_idx) == 0:
        out["acceptance"] = Gate("membrane equilibration", AUTO_FIXED,
                                 "軌跡沒有存水分子（只存溶質），無法事後檢查疏水核心的水與膜平衡；結果請當作未經驗收的膜解讀。",
                                 advisory=True, evidence={"checked": False}).to_dict()
        return out
    centre = th["centre_nm"]
    excl = xyz[:, list(protein_idx)] if (has_protein and protein_idx) else None
    cw = water_in_core(xyz[:, list(water_o_idx)], centre, box, exclude_xyz=excl)
    out["core_water"] = [int(v) for v in cw]
    g = assess_equilibration(apl_nm2=apl_mean, dpp_nm=float(th["dpp_nm"][half].mean()), core_water=float(cw[half].mean()),
                             n_lipids=len(head_idx), reference=reference or {}, attempt=1)
    if g.status == PASS:
        g = Gate(g.name, PASS, "以正式模擬後半段檢查：" + g.explanation, evidence={**g.evidence, "when": "production second half"})
    else:
        # analysis only: nothing can be extended any more, so this is a notice, not a stop (the run is already done)
        g = Gate(g.name, AUTO_FIXED,
                 "以正式模擬後半段事後檢查，膜平衡驗收未通過：" + g.explanation.split("：", 1)[-1]
                 + "沒有自動延長平衡（驗收只在分析時執行）；面積、厚度與接觸結果要當作未平衡的膜解讀，"
                 "可延長平衡（md.stage_overrides.npt.length_ps）後重跑。",
                 advisory=True, options=list(g.options), evidence={**g.evidence, "when": "production second half"})
    out["acceptance"] = g.to_dict()
    return out


def _water_oxygens(topology_pdb: Path | str) -> list[int]:
    out, i = [], 0
    for line in Path(topology_pdb).read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith(("ATOM", "HETATM")):
            if line[17:21].strip() in WATER_RESNAMES and line[12:16].strip() == "O":
                out.append(i)
            i += 1
    return out


def analyse_membrane_run(run_dir: Path | str, build_manifest: dict, *, label: str = "", decisions=None) -> dict:
    """Membrane metrics for one run (all three membrane types).  Writes analysis/membrane_metrics.json and, when no
    general analysis wrote one, analysis/metrics.json with the same content (the workflow and the report read it)."""
    import mdtraj as md
    from .stream import production_info, production_topology, remap_indices
    run_dir = Path(run_dir)
    adir = run_dir / "analysis"
    adir.mkdir(parents=True, exist_ok=True)
    mem = build_manifest.get("membrane") or (build_manifest.get("assembly") or {}).get("membrane") or {}
    top_pdb = build_manifest.get("topology_pdb")
    info = production_info(run_dir)
    if not info["dcds"] or not top_pdb:
        raise RuntimeError("找不到正式模擬的軌跡或拓樸檔，無法做膜分析。")
    top, subset = production_topology(run_dir, top_pdb)
    traj = md.load(info["dcds"], top=top)
    heads = remap_indices(mem.get("head_atom_indices") or [], subset)
    waters = remap_indices(_water_oxygens(top_pdb), subset)
    from ..workflow import manifest_ligands
    groups = {l["name"]: remap_indices(l.get("heavy_atom_indices") or [], subset) for l in manifest_ligands(build_manifest)}
    plan = mem.get("plan") or {}
    has_protein = plan.get("type") == "protein"
    prot = None
    if has_protein:
        prot = [a.index for a in traj.topology.atoms if a.residue.is_protein and a.element is not None and a.element.symbol != "H"]
    s = membrane_summary(traj.xyz, traj.unitcell_lengths, head_idx=heads, water_o_idx=waters, solute_groups=groups,
                         reference=plan.get("reference") or {}, has_protein=has_protein, protein_idx=prot)
    s.update({"label": label, "type": plan.get("type"), "created_at": now_iso()})
    # the report figures read the schema of analysis/membrane_report.py (analysis.summaries[system]["membrane_file"])
    try:
        s["membrane_file"] = str(_report_summary(traj, adir, heads, waters, groups, plan))
    except Exception as exc:  # noqa: BLE001 — the acceptance above stands; the report then has no membrane figures
        s["membrane_file_error"] = f"{type(exc).__name__}: {exc}"
        if decisions is not None:
            decisions.record("analysis.membrane", "report summary", "failed",
                             f"膜的報告摘要沒有產生（{type(exc).__name__}: {exc}）；平衡驗收與 membrane_metrics.json 不受影響。", kind="auto")
    atomic_write_json(s, adir / "membrane_metrics.json")
    if decisions is not None and s.get("acceptance"):
        g = s["acceptance"]
        decisions.record("analysis.membrane", "membrane equilibration", g["status"], g["explanation"],
                         kind="auto" if g["status"] == PASS else "auto_fixed")
    return s


def _report_summary(traj, adir: Path, heads: list, waters: list, groups: dict, plan: dict) -> Path:
    """analysis/membrane_report.membrane_report_data on the loaded trajectory → analysis/membrane_report.json."""
    from .membrane_report import membrane_report_data as report_summary
    from .membrane import scd_groups_from_names
    xyz, box = traj.xyz, traj.unitcell_lengths
    top = traj.topology
    comp = (plan.get("composition") or {}).get("upper") or {}
    kw: dict = {}
    dens = {"phosphate": xyz[:, heads, 2]}
    if waters:
        dens["water"] = xyz[:, waters, 2]
        kw["water_o_xyz"] = xyz[:, waters]
    sol = next((v for v in groups.values() if v), None)
    if sol:
        dens["solute"] = xyz[:, sol, 2]
        kw["solute_xyz"] = xyz[:, sol]
        sol_set = set(sol)
        res = {}
        for a in top.atoms:
            if a.index in sol_set:
                res.setdefault((a.residue.chain.index, a.residue.index), (f"{a.residue.name}{a.residue.resSeq}", []))[1].append(a.index)
        if len(res) > 1:
            kw["residue_names"] = [n for n, _ in res.values()]
            kw["residue_xyz"] = [xyz[:, idx] for _, idx in res.values()]
            ca = [a.index for a in top.atoms if a.index in sol_set and a.name == "CA"]
            if len(ca) >= 3:
                kw["ca_xyz"] = xyz[:, ca]
    names = [a.name for a in top.atoms]
    rids = [a.residue.index for a in top.atoms]
    scd = scd_groups_from_names(names, rids)
    if scd:
        kw.update(scd_xyz=xyz, scd_groups=scd)
    s = report_summary(time_ns=np.asarray(traj.time, float) / 1000.0, box=box, head_xyz=xyz[:, heads], composition=comp,
                       temperature_k=plan.get("temperature_k"), mtype=plan.get("type") or "bilayer", density_z=dens, **kw)
    p = adir / "membrane_report.json"
    atomic_write_json(s, p)
    return p


def membrane_only_analysis(run_dir: Path | str, build_manifest: dict, *, label: str = "", decisions=None) -> dict:
    """Surface (B) and bilayer (C) systems have no receptor, so the protein analyses (backbone RMSD, pocket contacts)
    do not apply; this writes metrics.json from the membrane analysis and returns an analysis_manifest-like summary."""
    run_dir = Path(run_dir)
    s = analyse_membrane_run(run_dir, build_manifest, label=label, decisions=decisions)
    adir = run_dir / "analysis"
    metrics = {"n_frames": s.get("n_frames", 0), "membrane": s}
    atomic_write_json(metrics, adir / "metrics.json")
    summary = {"status": "PASS", "kind": "membrane", "metrics_file": str(adir / "metrics.json"),
               "membrane_metrics_file": str(adir / "membrane_metrics.json"), "n_frames": s.get("n_frames", 0),
               **({"membrane_file": s["membrane_file"]} if s.get("membrane_file") else {}),
               "figures": [], "ligands": {}, "membrane_acceptance": s.get("acceptance"), "created_at": now_iso()}
    atomic_write_json(summary, adir / "analysis_manifest.json")
    return summary


def acceptance_from_summary(summary: dict) -> dict | None:
    """The acceptance gate stored in an analysis summary (or in its membrane_metrics.json)."""
    if summary.get("membrane_acceptance"):
        return summary["membrane_acceptance"]
    p = summary.get("membrane_metrics_file")
    return load_json(p, {}).get("acceptance") if p else None
