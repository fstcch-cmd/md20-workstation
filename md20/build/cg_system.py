"""Coarse-grained Martini 3 system build (D-86): runs the plan of md20/build/martini.py.

    protein (all-atom PDB, protein atoms only) ── orient (membrane protein) ── martinize2 -ss <mdtraj DSSP>
        ── insane (bilayer / water, NaCl) ── compose system.top ── martini_openmm → system.xml

Three system kinds (same names as the all-atom membrane systems, docs/specs/membrane.md §2):
  protein  membrane protein in a bilayer: hydrophobic belt found by membrane.scan_orientation, belt centre placed on
           the bilayer centre (checked after insane, one corrective rebuild if it is off by more than 0.3 nm)
  surface  peptide or protein above the bilayer, not crossing it (insane -dm, then the gap is checked)
  bilayer  lipids, water and ions only
  water    protein in water (no membrane)
Every automatic choice is written to the DecisionLog; anything that cannot be checked stops (NEEDS_HUMAN).
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np

from . import martini as M

ION_RENAME = {"NA+": "NA", "CL-": "CL"}      # older insane releases (Martini 2 names) → Martini 3 ion moleculetypes
BELT_TOL_NM = 0.3                            # belt centre vs bilayer centre after insane
SURFACE_MIN_GAP_NM = 0.3                     # closest protein bead to the phosphate plane, surface systems


class CGBuildError(RuntimeError):
    def __init__(self, code: str, text: tuple, options: list[str] | None = None, evidence: dict | None = None):
        super().__init__(text[0])
        self.code, self.text, self.options, self.evidence = code, text, options or [], evidence or {}


def protein_only(src: Path | str, dst: Path | str) -> dict:
    """ATOM records only (martinize2 cannot map ligands, metals or water); returns counts for the decision log."""
    keep, dropped = [], 0
    for line in Path(src).read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("ATOM"):
            keep.append(line)
        elif line.startswith("HETATM"):
            dropped += 1
        elif line.startswith("TER") and keep and not keep[-1].startswith("TER"):
            keep.append("TER")
    keep.append("END")
    Path(dst).write_text("\n".join(keep) + "\n", encoding="utf-8")
    return {"atoms": sum(1 for x in keep if x.startswith("ATOM")), "hetatm_dropped": dropped}


def _read_pdb_xyz(path: Path) -> tuple[list[str], np.ndarray]:
    lines = [l for l in Path(path).read_text(encoding="utf-8", errors="replace").splitlines() if l.startswith("ATOM")]
    xyz = np.array([[float(l[30:38]), float(l[38:46]), float(l[46:54])] for l in lines]) / 10.0
    return lines, xyz


def _write_pdb_xyz(lines: list[str], xyz_nm: np.ndarray, path: Path) -> None:
    out = [l[:30] + "".join(f"{v * 10:8.3f}" for v in p) + l[54:] for l, p in zip(lines, xyz_nm)]
    Path(path).write_text("\n".join(out + ["END"]) + "\n", encoding="utf-8")


def ca_and_resnames(lines: list[str], xyz: np.ndarray) -> tuple[np.ndarray, list[str], list[tuple]]:
    idx = [i for i, l in enumerate(lines) if l[12:16].strip() == "CA"]
    return xyz[idx], [lines[i][17:20].strip() for i in idx], [(lines[i][21], lines[i][22:27]) for i in idx]


def orient_protein(src: Path, dst: Path, *, oriented: bool) -> dict:
    """Membrane normal → z and hydrophobic belt centre → origin (all-atom coordinates).  `oriented` (OPM etc.): kept
    as is, the scan still runs and is reported.  Returns the scan result and the gate."""
    from .membrane import scan_orientation, orientation_transform, apply_transform, orientation_gate
    lines, xyz = _read_pdb_xyz(src)
    ca, rn, keys = ca_and_resnames(lines, xyz)
    res = scan_orientation(ca, rn)
    gate = orientation_gate(res, oriented=oriented)
    if gate.status == "NEEDS_HUMAN":
        return {"scan": res, "gate": gate.to_dict(), "pdb": None}
    if oriented:
        new = xyz
    else:
        R, t = orientation_transform(res)
        new = apply_transform(xyz, R, t)
    _write_pdb_xyz(lines, new, dst)
    ca2 = new[[i for i, l in enumerate(lines) if l[12:16].strip() == "CA"]]
    slab = float(res.get("slab_nm") or 3.0)
    belt = [i for i, z in enumerate(ca2[:, 2]) if abs(z) <= slab / 2]
    return {"scan": res, "gate": gate.to_dict(), "pdb": str(dst), "belt_residues": len(belt), "belt_index": belt,
            "geom_centre_z_nm": float(new[:, 2].mean())}


def read_gro(path: Path | str) -> dict:
    """Minimal .gro reader: residue ids, residue names, atom names, xyz (nm) and the box."""
    lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    n = int(lines[1].split()[0])
    body = lines[2:2 + n]
    resid = np.array([int(l[0:5]) for l in body])
    resn = [l[5:10].strip() for l in body]
    name = [l[10:15].strip() for l in body]
    xyz = np.array([[float(l[20:28]), float(l[28:36]), float(l[36:44])] for l in body])
    box = np.array([float(v) for v in lines[2 + n].split()[:3]])
    return {"resid": resid, "resname": resn, "name": name, "xyz": xyz, "box": box}


def protein_bead_count(top_text: str, itps: list[Path]) -> int:
    """Number of beads of the martinize2 molecules (protein beads come first in insane's .gro)."""
    per = {}
    for p in itps:
        name, n, sec = None, 0, None
        for raw in Path(p).read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.split(";", 1)[0].strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("["):
                sec = line.strip("[] ").replace(" ", "").lower()
                continue
            if sec == "moleculetype" and name is None:
                name = line.split()[0]
            elif sec == "atoms":
                n += 1
        if name:
            per[name] = n
    return sum(per.get(m, 0) * c for m, c in M.molecules_section(top_text))


def _run(argv: list[str], cwd: Path, log: Path, timeout_s: float) -> None:
    with open(log, "a", encoding="utf-8", errors="replace") as fh:
        fh.write("$ " + " ".join(str(a) for a in argv) + "\n")
        fh.flush()
        r = subprocess.run([str(a) for a in argv], cwd=str(cwd), stdout=fh, stderr=subprocess.STDOUT,
                           timeout=timeout_s, check=False)
    if r.returncode != 0:
        tail = "\n".join(Path(log).read_text(encoding="utf-8", errors="replace").splitlines()[-15:])
        raise CGBuildError("tool_failed", (f"{Path(argv[0]).name} 失敗（結束碼 {r.returncode}）。最後的訊息：\n{tail}",
                                           f"{Path(argv[0]).name} failed (exit code {r.returncode}). Last messages:\n{tail}",
                                           f"{Path(argv[0]).name} が失敗しました（終了コード {r.returncode}）。最後のメッセージ：\n{tail}",
                                           f"{Path(argv[0]).name} 실패(종료 코드 {r.returncode}). 마지막 메시지:\n{tail}"),
                           ["改用全原子模擬", "把 cg_build.log 傳給老師"], {"log": str(log)})


def insane_supports_ff(ins_cmd: list[str]) -> bool:
    """Newer insane takes -ff M3; older releases (Martini 2 era) do not know the option."""
    try:
        r = subprocess.run([str(a) for a in ins_cmd] + ["-h"], capture_output=True, text=True, timeout=60)
        return "-ff" in (r.stdout + r.stderr)
    except (OSError, subprocess.SubprocessError):
        return False


def _tail_lines(text: str, n: int = 12) -> str:
    return "\n".join(text.splitlines()[-n:])


def build_cg_system(workdir: Path | str, *, kind: str, protein_pdb: Path | str | None = None, lipids: dict | None = None,
                    box_xy_nm: float | None = None, water_nm: float = 3.0, salt_molar: float = 0.15,
                    surface_distance_nm: float = 1.0, oriented: bool = False, ff_dir: Path | str | None = None,
                    decisions=None, avail: dict | None = None, timeout_s: float = 3600.0) -> dict:
    """Build one CG system.  Returns the manifest (paths, counts, checks).  Raises CGBuildError for anything that
    needs a person (NEEDS_HUMAN in the workflow)."""
    wd = Path(workdir)
    wd.mkdir(parents=True, exist_ok=True)
    log = wd / "cg_build.log"
    log.write_text("", encoding="utf-8")
    avail = M.availability() if avail is None else avail
    ff = Path(ff_dir) if ff_dir else M.default_ff_dir()
    dec = decisions
    man = {"kind": kind, "workdir": str(wd), "log": str(log), "ff_dir": str(ff)}
    membrane = kind in ("protein", "surface", "bilayer")
    prot = None
    ss = None
    memshift = 0.0
    half_z = 0.0
    if kind in ("protein", "surface", "water"):
        if not protein_pdb:
            raise CGBuildError("no_solute", ("這個粗粒化系統需要蛋白或胜肽結構。", "This coarse-grained system needs a protein "
                               "or peptide structure.", "この粗視化の系にはタンパク質かペプチドの構造が必要です。",
                               "이 조립화 계에는 단백질이나 펩타이드 구조가 필요합니다."), ["md.membrane.type: bilayer"])
        aa = wd / "protein_aa.pdb"
        cnt = protein_only(protein_pdb, aa)
        man["protein_input"] = {"source": str(protein_pdb), **cnt}
        if dec and cnt["hetatm_dropped"]:
            dec.record("build.cg", "hetero atoms", cnt["hetatm_dropped"],
                       f"粗粒化只轉換蛋白原子；移除 {cnt['hetatm_dropped']} 個 HETATM（配體、金屬、水）。Martini 3 沒有它們的通用參數。",
                       kind="auto_fixed")
        if kind == "protein":
            o = orient_protein(aa, wd / "protein_oriented.pdb", oriented=oriented)
            man["orientation"] = {k: v for k, v in o.items() if k != "belt_index"}
            man["belt_index"] = o.get("belt_index") or []
            if o["pdb"] is None:
                g = o["gate"]
                raise CGBuildError("orientation", (g["explanation"], "The hydrophobic belt of the protein is not clear, so "
                                   "its orientation in the membrane cannot be set automatically.",
                                   "タンパク質の疎水帯がはっきりしないため、膜内の向きを自動で決められません。",
                                   "단백질의 소수성 띠가 분명하지 않아 막 안의 방향을 자동으로 정할 수 없습니다."),
                                   g.get("options") or ["md.membrane.oriented: true（輸入已定向，例如 OPM）"], {"scan": o["scan"]})
            prot = Path(o["pdb"])
            if dec:
                dec.record("build.cg", "orientation", "oriented input" if oriented else "hydrophobic belt",
                           ("輸入結構已定向，照原樣使用。" if oriented else
                            f"以疏水帶掃描決定膜法線（傾角 {o['scan'].get('tilt_deg')}°），疏水帶中心放在膜中心。"),
                           kind="auto")
        else:
            prot = aa
        try:
            ss = M.dssp_string(prot)
        except Exception as exc:  # noqa: BLE001
            raise CGBuildError("dssp", (f"無法計算二級結構（mdtraj DSSP）：{exc}", f"Secondary structure could not be computed "
                               f"(mdtraj DSSP): {exc}", f"二次構造を計算できませんでした（mdtraj DSSP）：{exc}",
                               f"이차 구조를 계산할 수 없습니다(mdtraj DSSP): {exc}"), ["改用全原子模擬"]) from exc
        man["secondary_structure"] = ss
        _, pxyz = _read_pdb_xyz(prot)
        ext = pxyz.max(0) - pxyz.min(0)
        half_z = float(ext[2]) / 2
        if box_xy_nm is None:
            box_xy_nm = max(8.0, float(max(ext[0], ext[1])) + 4.0)
        if kind == "surface":
            memshift = 2.0 + float(surface_distance_nm) + half_z
    box_xy_nm = float(box_xy_nm or 8.0)
    if kind == "bilayer":
        box_z = 4.0 + 2 * water_nm
    elif kind == "surface":
        box_z = 2 * (memshift + half_z) + 2 * water_nm
    elif kind == "protein":
        box_z = max(4.0 + 2 * water_nm, 2 * half_z + 2 * water_nm)
    else:
        box_z = max(box_xy_nm, 2 * half_z + 2 * water_nm)
    box = (box_xy_nm, box_xy_nm, round(box_z, 2))
    ins_cmd = (avail.get("insane") or {}).get("argv") or ["insane"]
    use_ff = insane_supports_ff(ins_cmd)
    plan = M.plan_cg_membrane(prot, wd, lipids=lipids if membrane else None, box_nm=box, salt_molar=salt_molar,
                              forcefield_dir=ff, avail=avail, membrane=membrane, memshift_nm=memshift, ss=ss,
                              insane_ff=use_ff)
    man["plan"] = plan.to_dict()
    man["box_nm"] = list(box)
    if plan.status != "PASS":
        i = plan.issues[0]
        raise CGBuildError(i["code"], tuple(i["text"]), i.get("options"), {"plan": plan.to_dict()})

    def run_tools(p):
        for st in p.steps:
            if st["kind"] == "exec":
                _run(st["argv"], wd, log, timeout_s)
                for o in st["outputs"]:
                    if "*" not in o and not (wd / o).is_file():
                        raise CGBuildError("no_output", (f"{st['name']} 沒有產生 {o}。", f"{st['name']} did not write {o}.",
                                           f"{st['name']} が {o} を出力しませんでした。", f"{st['name']}이(가) {o}을(를) 만들지 않았습니다."),
                                           ["改用全原子模擬", "把 cg_build.log 傳給老師"], {"log": str(log)})
    run_tools(plan)

    # belt check (membrane protein): the PO4 plane centre vs the CG backbone of the belt residues
    if kind == "protein":
        off = _belt_offset(wd, man)
        man["belt_offset_nm"] = off
        if off is not None and abs(off) > BELT_TOL_NM:
            first = off
            shift = -off
            plan2 = M.plan_cg_membrane(prot, wd, lipids=lipids, box_nm=box, salt_molar=salt_molar, forcefield_dir=ff,
                                       avail=avail, membrane=True, memshift_nm=shift, ss=ss, insane_ff=use_ff)
            run_tools(plan2)
            off = _belt_offset(wd, man)
            if off is not None and abs(off) > abs(first):         # the option's sign is the other way round
                plan2 = M.plan_cg_membrane(prot, wd, lipids=lipids, box_nm=box, salt_molar=salt_molar, forcefield_dir=ff,
                                           avail=avail, membrane=True, memshift_nm=-shift, ss=ss, insane_ff=use_ff)
                run_tools(plan2)
                off = _belt_offset(wd, man)
            man["plan"] = plan2.to_dict()
            man["belt_offset_nm"] = off
            if dec:
                dec.record("build.cg", "belt offset", f"{first:+.2f} → {off:+.2f} nm",
                           f"insane 依蛋白幾何中心置中，疏水帶中心偏離膜中心 {first:+.2f} nm；以 -dm 平移後重建，偏差 {off:+.2f} nm。",
                           kind="auto_fixed")
            if off is not None and abs(off) > BELT_TOL_NM:
                raise CGBuildError("belt_offset", (f"疏水帶中心與膜中心相差 {off:+.2f} nm（上限 {BELT_TOL_NM}），重建後仍不符。",
                                   f"The hydrophobic belt is {off:+.2f} nm from the bilayer centre (limit {BELT_TOL_NM}) even "
                                   "after a rebuild.", f"疎水帯の中心が膜の中心から {off:+.2f} nm ずれています（上限 {BELT_TOL_NM}）。"
                                   "作り直しても直りませんでした。", f"소수성 띠 중심이 막 중심에서 {off:+.2f} nm 떨어져 있습니다(상한 "
                                   f"{BELT_TOL_NM}). 다시 만들어도 맞지 않습니다."),
                                   ["md.membrane.oriented: true（輸入已定向，例如 OPM）", "改用全原子模擬"])
    if kind == "surface":
        gap = _surface_gap(wd, man)
        man["surface_gap_nm"] = gap
        if gap is not None and gap < SURFACE_MIN_GAP_NM:
            raise CGBuildError("surface_overlap", (f"胜肽離磷酸平面只有 {gap:.2f} nm，與膜重疊。",
                               f"The peptide is only {gap:.2f} nm from the phosphate plane, overlapping the membrane.",
                               f"ペプチドがリン酸の面から {gap:.2f} nm しか離れておらず、膜と重なっています。",
                               f"펩타이드가 인산 평면에서 {gap:.2f} nm밖에 떨어져 있지 않아 막과 겹칩니다."),
                               ["md.membrane.surface_distance_nm: 1.5"])

    # topology
    for name in M.FF_SOURCE["sha256"]:
        if (ff / name).is_file():
            shutil.copyfile(ff / name, wd / name)
    itps = sorted(wd.glob("molecule_*.itp"))
    ptop = (wd / "protein.top").read_text(encoding="utf-8") if prot is not None else ""
    itop = (wd / "insane.top").read_text(encoding="utf-8")
    for a, b in ION_RENAME.items():
        itop = "\n".join((b + l[len(a):]) if l.split(";")[0].strip().startswith(a + " ") else l for l in itop.splitlines())
    ff_inc = [M.FF_FILES["core"]] + ([M.FF_FILES["phospholipids"]] if membrane else []) + [M.FF_FILES["solvents"]] + \
             ([M.FF_FILES["ions"]] if salt_molar > 0 else [])
    top = M.compose_topology(itop, ptop, ff_inc, [p.name for p in itps], title=f"MD20 Martini 3 {kind}")
    (wd / "system.top").write_text(top, encoding="utf-8")
    man["n_protein_beads"] = protein_bead_count(ptop, itps) if prot is not None else 0
    try:
        sysinfo = M.build_openmm_system(wd / "system.gro", wd / "system.top", wd / "system.xml", include_dir=wd)
    except Exception as exc:  # noqa: BLE001
        raise CGBuildError("martini_openmm", (f"martini_openmm 無法建立系統：{type(exc).__name__}: {exc}",
                           f"martini_openmm could not create the system: {type(exc).__name__}: {exc}",
                           f"martini_openmm で系を作れませんでした：{type(exc).__name__}: {exc}",
                           f"martini_openmm이 계를 만들 수 없습니다: {type(exc).__name__}: {exc}"), ["改用全原子模擬"]) from exc
    g = read_gro(wd / "system.gro")
    if sysinfo["n_particles"] != len(g["name"]):
        raise CGBuildError("count_mismatch", (f"拓撲有 {sysinfo['n_particles']} 顆珠子，座標檔有 {len(g['name'])} 顆，不一致。",
                           f"The topology has {sysinfo['n_particles']} beads but the coordinates have {len(g['name'])}.",
                           f"トポロジーのビーズは {sysinfo['n_particles']} 個、座標は {len(g['name'])} 個で一致しません。",
                           f"토폴로지에는 비드 {sysinfo['n_particles']}개, 좌표에는 {len(g['name'])}개가 있어 일치하지 않습니다."),
                           ["把 cg_build.log 傳給老師"])
    man.update({"system_xml": str(wd / "system.xml"), "gro": str(wd / "system.gro"), "top": str(wd / "system.top"),
                "n_beads": sysinfo["n_particles"], "molecules": M.molecules_section(top),
                "settings": {"epsilon_r": M.CG_EPSILON_R, "cutoff_nm": M.CG_CUTOFF_NM, "timestep_fs": M.CG_TIMESTEP_FS,
                             "friction_per_ps": M.CG_FRICTION_PER_PS}, "membrane": membrane,
                "lipids": dict(lipids or {}) if membrane else {}, "salt_molar": salt_molar})
    if dec:
        mols = ", ".join(f"{n} {c}" for n, c in man["molecules"])
        dec.record("build.cg", kind, f"{man['n_beads']} beads",
                   f"Martini 3 粗粒化系統（{kind}）：盒子 {box[0]:g}×{box[1]:g}×{box[2]:g} nm，{mols}。"
                   f"蛋白二級結構以 mdtraj DSSP 計算後傳給 martinize2（-ss），彈性網路固定三級結構。", kind="auto")
    return man


def _po4_centre(g: dict) -> tuple[float, np.ndarray]:
    po4 = np.array([n == "PO4" for n in g["name"]])
    z = g["xyz"][po4, 2]
    return float(z.mean()), z


def _belt_offset(wd: Path, man: dict) -> float | None:
    """Mean z of the BB beads of the belt residues (positions in input order) minus the PO4 centre."""
    g = read_gro(wd / "system.gro")
    if not any(n == "PO4" for n in g["name"]):
        return None
    c, _ = _po4_centre(g)
    bb = [i for i, n in enumerate(g["name"]) if n == "BB"]
    if not bb:
        return None
    sel = [bb[i] for i in (man.get("belt_index") or []) if i < len(bb)] or bb
    return float(g["xyz"][sel, 2].mean() - c)


PROTEIN_BEADS = ("BB", "SC1", "SC2", "SC3", "SC4", "SC5")


def _surface_gap(wd: Path, man: dict) -> float | None:
    """Closest protein bead to the phosphate plane on its side of the bilayer (nm; negative = overlapping)."""
    g = read_gro(wd / "system.gro")
    if not any(n == "PO4" for n in g["name"]):
        return None
    c, z = _po4_centre(g)
    upper = z[z > c].mean() if (z > c).any() else c
    lower = z[z <= c].mean() if (z <= c).any() else c
    n = int(man.get("n_protein_beads") or 0)
    idx = list(range(n)) if n else [i for i, nm in enumerate(g["name"]) if nm in PROTEIN_BEADS]
    if not idx:
        return None
    pz = g["xyz"][idx, 2]
    return float(pz.min() - upper) if pz.mean() > c else float(lower - pz.max())
