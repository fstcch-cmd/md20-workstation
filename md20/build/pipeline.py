"""Case-level build: receptor → ligands → assembled system, all recorded in the case manifest."""
from __future__ import annotations

from pathlib import Path

from ..project import Case
from ..util import atomic_write_json, load_json, now_iso
from .gates import NEEDS_HUMAN
from .receptor import prepare_receptor
from .ligand import prepare_ligand, LigandRecord, extract_hetatm_pose, extract_chain_pose
from .assemble import assemble_system
from .peptide import prepare_peptide, free_chain_id, looks_like_peptide, cpp_gate
from .gates import Gate


def build_case(case: Case, *, receptor: Path | str, ligand_references: list[str | Path],
               ligand_poses: list[Path | str | None] | None = None, ph: float = 7.4, padding_nm: float = 1.0,
               ionic_strength_molar: float = 0.15, human_choices: dict | None = None, run_smoke_test: bool = True,
               cocrystal_resnames: list[str] | None = None, keep_hetero: set[str] | None = None,
               extra_ligand_resnames: set[str] | None = None, peptides: list[dict] | None = None,
               ligand_names: list[str] | None = None, peptide_policy: dict | None = None,
               exclude_chains: set[str] | None = None, metal_policy: dict | None = None,
               metal_params: dict | None = None, solvent: str = "explicit", box_shape: str = "dodecahedron") -> dict:
    """Build a case.

    `cocrystal_resnames[i]` (optional) names the HETATM residue whose coordinates are the pose for ligand i.
    `peptides`: [{"name", "sequence", "pose" (SDF/PDB, optional), "cocrystal_chain" (optional), "termini",
                  "target_location", "cpp_evidence", "cpp_override"}] — built with ff14SB on their own chain.
    """
    decisions = case.project.decisions
    bdir = case.build_dir
    rec_in = case.import_input(receptor, "receptor")
    cocrystal = list(cocrystal_resnames or [])
    peptides = list(peptides or [])
    pep_chains_in_file = {p["cocrystal_chain"] for p in peptides if p.get("cocrystal_chain")}
    if metal_policy:
        # a metal with a keep/bonded policy must survive receptor clean-up; "remove" is applied at assembly
        from .receptor import COFACTOR_KEEP_DEFAULT
        keep_hetero = set(keep_hetero) if keep_hetero else set(COFACTOR_KEEP_DEFAULT)
        keep_hetero |= {k.split(":")[0].upper() for k, v in metal_policy.items() if v in ("bonded", "keep_nonbonded")}
    rman = prepare_receptor(rec_in["path"], bdir / "receptor", ph=ph, decisions=decisions, keep_hetero=keep_hetero,
                            human_choices=(human_choices or {}).get("receptor"),
                            ligand_resnames=set(cocrystal) | set(x for x in (extra_ligand_resnames or ()) if x),
                            exclude_chains=pep_chains_in_file | set(exclude_chains or ()))
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
        if isinstance(ref, str) and not Path(ref).is_file() and looks_like_peptide(ref) and not (peptide_policy or {}).get("allow_small_molecule"):
            summary.update({"status": NEEDS_HUMAN, "blocking": f"ligand {name}",
                            "blocking_detail": [Gate("peptide detected", NEEDS_HUMAN,
                                f"{(ligand_names or [name] * i)[i - 1]} 看起來是胜肽（連續 α-胺基酸骨架），若以小分子力場處理會得到錯誤的參數。"
                                "請以序列宣告為胜肽（走 ff14SB、獨立 chain），或確認它是擬肽小分子。",
                                options=["以序列宣告為胜肽", "確認為小分子（peptide_policy.allow_small_molecule）"]).to_dict()]})
            atomic_write_json(summary, bdir / "build_manifest.json")
            _update_case(case, summary)
            return summary
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
    used_chains = {l[21] for l in Path(rman["receptor_pdb"]).read_text(encoding="utf-8", errors="ignore").splitlines()
                   if l.startswith(("ATOM", "HETATM")) and len(l) > 21}
    for j, pspec in enumerate(peptides, 1):
        pname = pspec.get("name") or f"P{j:02d}"
        g, cpp = cpp_gate(pspec["sequence"], target_location=pspec.get("target_location"),
                          experimental_evidence=pspec.get("cpp_evidence"))
        if g.status == NEEDS_HUMAN and pspec.get("cpp_override"):
            g = Gate("CPP", "AUTO_FIXED", g.explanation + "（使用者選擇仍要繼續；報告標註）", options=g.options)
            cpp["override"] = True
        decisions.record("build.cpp", pname, cpp.get("status"), g.explanation, kind="human" if pspec.get("cpp_override") else "auto")
        if g.status == NEEDS_HUMAN:
            summary.update({"status": NEEDS_HUMAN, "blocking": f"peptide {pname} CPP", "blocking_detail": [g.to_dict()],
                            "cpp": {pname: cpp}})
            atomic_write_json(summary, bdir / "build_manifest.json")
            _update_case(case, summary)
            return summary
        pose = pspec.get("pose")
        if not pose and pspec.get("cocrystal_chain"):
            pose = extract_chain_pose(Path(rec_in["path"]).read_text(encoding="utf-8", errors="ignore"), pspec["cocrystal_chain"],
                                      bdir / "ligands" / f"{pname}_cocrystal_pose.pdb")
        chain = free_chain_id(used_chains)
        used_chains.add(chain)
        prec = prepare_peptide(pspec["sequence"], pose, bdir / "ligands", name=pname, chain_id=chain,
                               termini=pspec.get("termini", "charged"), decisions=decisions)
        prec.cpp = cpp
        prec.gates.setdefault("gates", []).append(g.to_dict())
        summary["ligands"].append(prec.to_dict())
        if prec.status == NEEDS_HUMAN:
            summary.update({"status": NEEDS_HUMAN, "blocking": f"peptide {pname}",
                            "blocking_detail": [x for x in prec.gates["gates"] if x["status"] == NEEDS_HUMAN]})
            atomic_write_json(summary, bdir / "build_manifest.json")
            _update_case(case, summary)
            return summary
        ligs.append(prec)
    res = assemble_system(rman["receptor_pdb"], ligs, bdir, padding_nm=padding_nm, box_shape=box_shape,
                          ionic_strength_molar=ionic_strength_molar, decisions=decisions, metal_policy=metal_policy, ph=ph,
                          metal_params=metal_params, solvent=solvent)
    if res.status == NEEDS_HUMAN:
        summary["blocking"] = "assembly"
        summary["blocking_detail"] = [g for g in (res.gates or {}).get("gates", []) if g.get("status") == NEEDS_HUMAN]
    if res.ligands:
        # keep top-level ligand records consistent with the assembled topology (they gain atom indices)
        summary["ligands"] = res.ligands
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
