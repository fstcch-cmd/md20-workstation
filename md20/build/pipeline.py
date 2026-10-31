"""Case-level build: receptor → ligands → assembled system, all recorded in the case manifest."""
from __future__ import annotations

from pathlib import Path

from ..project import Case
from ..util import atomic_write_json, load_json, now_iso
from .gates import NEEDS_HUMAN
from .receptor import prepare_receptor
from .ligand import prepare_ligand, LigandRecord, extract_hetatm_pose
from .assemble import assemble_system


def build_case(case: Case, *, receptor: Path | str, ligand_references: list[str | Path],
               ligand_poses: list[Path | str | None] | None = None, ph: float = 7.4, padding_nm: float = 1.0,
               ionic_strength_molar: float = 0.15, human_choices: dict | None = None, run_smoke_test: bool = True,
               cocrystal_resnames: list[str] | None = None, keep_hetero: set[str] | None = None,
               extra_ligand_resnames: set[str] | None = None) -> dict:
    """Build a case.  `cocrystal_resnames[i]` (optional) names the HETATM residue in the receptor file whose
    coordinates are the pose for ligand i (the classic "re-simulate the crystal ligand" teaching case)."""
    decisions = case.project.decisions
    bdir = case.build_dir
    rec_in = case.import_input(receptor, "receptor")
    cocrystal = list(cocrystal_resnames or [])
    rman = prepare_receptor(rec_in["path"], bdir / "receptor", ph=ph, decisions=decisions, keep_hetero=keep_hetero,
                            human_choices=(human_choices or {}).get("receptor"),
                            ligand_resnames=set(cocrystal) | set(x for x in (extra_ligand_resnames or ()) if x))
    summary = {"status": "RUNNING", "receptor": rman, "ligands": [], "created_at": now_iso()}
    if rman["status"] == NEEDS_HUMAN:
        summary["status"] = NEEDS_HUMAN
        summary["blocking"] = "receptor"
        summary["blocking_detail"] = [g for g in (rman.get("gates") or {}).get("gates", []) if g.get("status") == NEEDS_HUMAN] or rman.get("error")
        atomic_write_json(summary, bdir / "build_manifest.json")
        _update_case(case, summary)
        return summary
    poses = list(ligand_poses or [None] * len(ligand_references))
    if cocrystal:
        pdb_text = Path(rec_in["path"]).read_text(encoding="utf-8", errors="ignore")
        for i, rn in enumerate(cocrystal):
            if rn and i < len(poses) and poses[i] is None:
                poses[i] = extract_hetatm_pose(pdb_text, rn, bdir / "ligands" / f"L{i + 1:02d}_cocrystal_pose.pdb")
                decisions.record("build.ligand", f"L{i + 1:02d} pose", f"co-crystal {rn}",
                                 "以晶體中的配體座標作為起始 pose；化學（鍵序、質子化）取自參考分子，不從 PDB 猜。")
    ligs: list[LigandRecord] = []
    for i, (ref, pose) in enumerate(zip(ligand_references, poses), 1):
        name = f"L{i:02d}"
        if Path(str(ref)).is_file():
            case.import_input(ref, f"ligand_{name}_reference")
        if pose is not None:
            case.import_input(pose, f"ligand_{name}_pose")
        rec = prepare_ligand(ref, pose, bdir / "ligands", name=name, decisions=decisions, run_smoke_test=run_smoke_test)
        ligs.append(rec)
        summary["ligands"].append(rec.to_dict())
        if rec.status == NEEDS_HUMAN:
            summary["status"] = NEEDS_HUMAN
            summary["blocking"] = f"ligand {name}"
            summary["blocking_detail"] = [g for g in (rec.gates or {}).get("gates", []) if g.get("status") == NEEDS_HUMAN]
            atomic_write_json(summary, bdir / "build_manifest.json")
            _update_case(case, summary)
            return summary
    res = assemble_system(rman["receptor_pdb"], ligs, bdir, padding_nm=padding_nm,
                          ionic_strength_molar=ionic_strength_molar, decisions=decisions)
    if res.status == NEEDS_HUMAN:
        summary["blocking"] = "assembly"
        summary["blocking_detail"] = [g for g in (res.gates or {}).get("gates", []) if g.get("status") == NEEDS_HUMAN]
    summary.update({"status": "PASS" if res.status != NEEDS_HUMAN else NEEDS_HUMAN, "assembly": res.to_dict(),
                    "system_xml": res.system_xml, "topology_pdb": res.topology_pdb})
    atomic_write_json(summary, bdir / "build_manifest.json")
    _update_case(case, summary)
    return summary


def _update_case(case: Case, summary: dict) -> None:
    m = case.manifest()
    m["build_status"] = summary["status"]
    m["status"] = "BUILT" if summary["status"] == "PASS" else "BUILD_" + summary["status"]
    case.save_manifest(m)
