"""Workflow report (D-52): project-report grade, bilingual (English default, Traditional Chinese).

Every section follows the same order the user asked for:
  1. what this step is   2. scientific meaning   3. parameters used (value, recommendation for this case, reason)
  4. figures and tables (numbered, with captions)   5. interpretation written from this run's numbers.
Front matter: key findings.  Back matter: methods paragraph ready to paste, limitations, parameter appendix, decision
log, configuration.  Nothing is typed by hand; every number comes from the workflow's own files.
"""
from __future__ import annotations

import json
from pathlib import Path

from .. import advisor
from ..advisor import tx
from ..util import load_json, now_iso
from . import interpret as I
from .html import _img, _esc, build_run_report


def _restrained_tag(summary: dict, lang: str = "zh") -> str:
    """D-23: RMSD measured under a production restraint is not evidence of stability — say so next to the number."""
    r = (summary or {}).get("restrained_production") or {}
    if not r:
        return ""
    return (f"<br><small>（受約束：{_esc(', '.join(r))}；低 RMSD 不代表結構穩定）</small>" if lang == "zh" else
            f"<br><small>(restrained: {_esc(', '.join(r))}; a low RMSD is not evidence of stability)</small>")


def _fmt(x, nd: int = 2) -> str:
    return "—" if x is None else f"{float(x):.{nd}f}"


CSS = """
:root{--ink:#1f2933;--muted:#52606d;--line:#d9dee3;--soft:#f4f6f8;--accent:#2f6f9f;--good:#2f7d5b;--warn:#a86a12;--bad:#b8433f}
body{font-family:"Inter","Segoe UI","Noto Sans TC","Microsoft JhengHei",system-ui,sans-serif;color:var(--ink);max-width:1040px;
     margin:2.5rem auto;padding:0 1.5rem;line-height:1.6;font-size:15px}
h1{font-size:1.7rem;margin:0 0 .3rem;font-weight:650}h2{font-size:1.25rem;margin:2.4rem 0 .6rem;padding-bottom:.3rem;border-bottom:2px solid var(--ink)}
h3{font-size:1.02rem;margin:1.4rem 0 .4rem}h4{font-size:.8rem;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin:1.1rem 0 .3rem}
.meta{color:var(--muted);font-size:.85rem}.lead{font-size:.95rem}
table{border-collapse:collapse;width:100%;font-size:.84rem;margin:.4rem 0 .2rem}th,td{border-bottom:1px solid var(--line);padding:.35rem .5rem;
      text-align:left;vertical-align:top}th{background:var(--soft);font-weight:600;border-bottom:1px solid #b9c1c9}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.caption{font-size:.8rem;color:var(--muted);margin:.2rem 0 1rem}.caption b{color:var(--ink)}
figure{margin:1rem 0}figure img{border:1px solid var(--line)}
.box{background:var(--soft);border-left:4px solid var(--accent);padding:.8rem 1rem;margin:1rem 0}
.findings li{margin:.25rem 0}.good::marker{color:var(--good)}.note::marker{color:var(--accent)}.caution::marker{color:var(--bad)}
.tag{display:inline-block;font-size:.72rem;padding:0 .4rem;border-radius:3px;border:1px solid var(--line);color:var(--muted);margin-left:.3rem}
.tag.changed{border-color:var(--warn);color:var(--warn)}.tag.caution{border-color:var(--bad);color:var(--bad)}
.methods{font-family:Georgia,"Noto Serif TC",serif;font-size:.95rem;background:#fff;border:1px solid var(--line);padding:1rem 1.2rem}
details{margin:.6rem 0}summary{cursor:pointer;color:var(--accent)}pre{font-size:.75rem;white-space:pre-wrap}
.muted{color:var(--muted)}.warn{color:var(--warn)}
@media print{body{max-width:none;margin:1cm}h2{page-break-after:avoid}figure,table{page-break-inside:avoid}details{display:none}}
"""

H = {  # fixed headings and labels
    "title": ("分子模擬專案報告", "Molecular Simulation Project Report"),
    "project": ("專案", "Project"), "workflow": ("流程", "Workflow"), "generated": ("產生時間", "Generated"),
    "key_findings": ("重點摘要", "Key findings"), "what": ("這一步是什麼", "What this step is"),
    "meaning": ("科學意義", "Scientific meaning"), "params": ("使用的參數", "Parameters used"),
    "results": ("結果", "Results"), "interpretation": ("結果解釋", "Interpretation"),
    "parameter": ("參數", "Parameter"), "value": ("採用值", "Value used"), "recommended": ("本案例建議值", "Recommended for this case"),
    "reason": ("理由", "Reason"), "changed": ("使用者修改", "changed by user"),
    "figure": ("圖", "Figure"), "table": ("表", "Table"),
    "methods": ("方法（可直接用於報告）", "Methods (ready to use in a report)"),
    "limitations": ("限制與注意事項", "Limitations and caveats"),
    "appendix_params": ("附錄 A　完整參數表", "Appendix A  Complete parameter table"),
    "appendix_log": ("附錄 B　決策紀錄", "Appendix B  Decision log"),
    "appendix_cfg": ("附錄 C　設定檔", "Appendix C  Configuration file"),
    "zh_note": ("", "Some automatic explanations and the decision log are recorded in Traditional Chinese and are shown as recorded."),
    "not_run": ("此步驟未執行。", "This step was not run."),
}

SECTION = {
    "design": {
        "title": ("研究設計", "Study design"),
        "what": ("定義研究的標靶蛋白、配體與要回答的問題，並決定模擬哪些系統。",
                 "Defines the target protein, the ligands and the question, and which systems are simulated."),
        "meaning": ("同時模擬「蛋白單獨」與「蛋白與配體」可以把配體造成的變化與蛋白本身的熱擾動分開；沒有對照組，RMSD 或柔性的變化無法歸因於配體。",
                    "Simulating the protein alone alongside the complex separates the ligand's effect from the protein's own "
                    "thermal motion; without that reference, changes in RMSD or flexibility cannot be attributed to the ligand."),
    },
    "structure": {
        "title": ("受體結構準備與可信度", "Receptor preparation and structure validity"),
        "what": ("下載或讀入受體結構，移除結晶添加物與水，補齊缺失原子，依 pH 加氫，並檢查解析度、物種與口袋完整性。",
                 "The receptor is fetched or read, crystallisation additives and water are removed, missing atoms are added, "
                 "hydrogens are placed for the chosen pH, and resolution, species and pocket completeness are checked."),
        "meaning": ("所有後續結果都建立在這個結構上：錯的 PDB 編號、缺失的口袋殘基或錯誤的質子化狀態，會讓對接與模擬給出看似合理但沒有意義的數字。",
                    "Every later result rests on this structure: a wrong identifier, missing pocket residues or a wrong "
                    "protonation state produce numbers that look reasonable but mean nothing."),
    },
    "screen": {
        "title": ("高通量前期篩選", "High-throughput pre-screening"),
        "what": ("以較低的搜尋強度快速對接化合物庫中的每個分子，依分數與配體效率排名，由使用者選出進入正式對接的化合物。",
                 "Every compound in the library is docked quickly at reduced search effort and ranked by score and ligand "
                 "efficiency; the user selects which compounds go on to full docking."),
        "meaning": ("篩選分數只用來剔除明顯不合的化合物，不是結合自由能；分數差距小於 1 kcal mol⁻¹ 時名次沒有統計意義。",
                    "Screening scores only remove clear misfits and are not binding free energies; differences below "
                    "1 kcal mol⁻¹ carry no statistical meaning."),
    },
    "docking": {
        "title": ("分子對接與姿勢選擇", "Molecular docking and pose selection"),
        "what": ("在結合位搜尋區內以 AutoDock Vina 產生配體姿勢，依分數、叢集大小與接觸殘基選出進入模擬的姿勢。",
                 "AutoDock Vina generates ligand poses inside the search box; the pose taken into simulation is chosen from "
                 "score, cluster size and contact residues."),
        "meaning": ("對接提供合理的起始結合模式，但分數是經驗評分函數，誤差約 1 到 2 kcal mol⁻¹，也不含蛋白柔性與溶劑效應；結合是否穩定要由分子動力學判斷。",
                    "Docking provides a plausible starting binding mode, but the score is an empirical function with an "
                    "error of about 1–2 kcal mol⁻¹ and no protein flexibility or solvent; whether binding is stable is "
                    "decided by molecular dynamics."),
    },
    "peptide": {
        "title": ("胜肽配體的科學限制", "Scientific limitations of the peptide ligand"),
        "what": ("對胜肽配體檢查兩件事：作用標靶在細胞內時胜肽能否穿膜，以及選用的姿勢是否真正進入結合位。",
                 "Two checks for a peptide ligand: whether it can cross the cell membrane when the target is intracellular, "
                 "and whether the chosen pose actually enters the binding site."),
        "meaning": ("胜肽大且柔軟，對接幾乎總能找到貼在蛋白表面的姿勢；若胜肽到不了標靶或沒有進入活性位，結合計算的生物學解釋就不成立。"
                    "這些是提醒而非阻擋，因為研究目的可能本來就是表面結合或體外試驗。",
                    "Peptides are large and flexible, and docking nearly always finds a pose on the protein surface; if the "
                    "peptide cannot reach the target or does not enter the site, the biological reading of the binding "
                    "calculation fails. These are notices rather than blocks, because surface binding or an in vitro assay "
                    "may be the actual aim."),
    },
    "md": {
        "title": ("分子動力學", "Molecular dynamics"),
        "what": ("把蛋白與配體放入水盒並加鹽，經能量最小化、升溫、定壓平衡後進行正式模擬，再分析主鏈 RMSD、殘基柔性（RMSF）、配體在口袋內的位移與接觸頻率。",
                 "Protein and ligand are placed in a water box with salt, minimised, heated and equilibrated at constant "
                 "pressure, then simulated in production; the analysis covers backbone RMSD, residue flexibility (RMSF), "
                 "ligand displacement in the pocket and contact frequencies."),
        "meaning": ("模擬檢驗對接姿勢在有溫度、溶劑與蛋白柔性時是否站得住：配體離開口袋代表對接分數不能作為結合證據；"
                    "蛋白單獨與複合物的柔性差異指出受配體影響的區域。",
                    "Simulation tests whether the docked pose holds with temperature, solvent and protein flexibility: a "
                    "ligand that leaves the pocket means the docking score is not evidence of binding, and the difference in "
                    "flexibility between protein alone and complex points to the regions the ligand affects."),
    },
    "binding": {
        "title": ("結合自由能（SMD 與傘狀採樣）", "Binding free energy (SMD and umbrella sampling)"),
        "what": ("以導向分子動力學（SMD）把配體沿解離路徑拉出口袋，取路徑上的構形作為傘狀採樣窗口，以 MBAR 合併得到自由能剖面（PMF），再加體積修正得到標準結合自由能。",
                 "Steered molecular dynamics (SMD) pulls the ligand out along a dissociation path; configurations along the "
                 "path start umbrella-sampling windows, which MBAR combines into a free-energy profile (PMF); a volume "
                 "correction gives the standard binding free energy."),
        "meaning": ("PMF 的井深反映配體離開口袋需要的自由能，比對接分數更接近實驗量；但它依賴取樣是否充分（窗口重疊、前後半段一致），未收斂時只適合定性比較。",
                    "The depth of the PMF is the free energy needed to take the ligand out of the pocket and is closer to an "
                    "experimental quantity than a docking score; it depends on sufficient sampling (window overlap, agreement "
                    "between halves) and is only qualitative when not converged."),
    },
}


class Doc:
    """Numbered figures and tables."""

    def __init__(self, lang: str):
        self.lang, self.nf, self.nt = lang, 0, 0

    def t(self, pair) -> str:
        return tx(pair, self.lang)

    def figure(self, path, caption_pair) -> str:
        img = _img(path)
        if not img:
            return ""
        self.nf += 1
        return (f"<figure>{img}<div class=caption><b>{self.t(H['figure'])} {self.nf}.</b> "
                f"{_esc(self.t(caption_pair))}</div></figure>")

    def table(self, headers: list, rows: list[list], caption_pair, num_cols: set | None = None) -> str:
        self.nt += 1
        num_cols = num_cols or set()
        head = "".join(f"<th class={'num' if i in num_cols else ''}>{_esc(h)}</th>" for i, h in enumerate(headers))
        body = "".join("<tr>" + "".join(f"<td class={'num' if i in num_cols else ''}>{c}</td>" for i, c in enumerate(r)) + "</tr>"
                       for r in rows)
        return (f"<div class=caption><b>{self.t(H['table'])} {self.nt}.</b> {_esc(self.t(caption_pair))}</div>"
                f"<table><tr>{head}</tr>{body}</table>")


def _findings_html(findings: list[dict], lang: str) -> str:
    if not findings:
        return ""
    return "<ul class=findings>" + "".join(f"<li class={f['level']}>{_esc(tx(f['text'], lang))}</li>" for f in findings) + "</ul>"


def _section(doc: Doc, n: int, key: str, params_html: str, results_html: str, findings: list[dict]) -> str:
    s = SECTION[key]
    L = doc.lang
    return "".join([f"<h2>{n}. {_esc(tx(s['title'], L))}</h2>",
                    f"<h4>{tx(H['what'], L)}</h4><p>{_esc(tx(s['what'], L))}</p>",
                    f"<h4>{tx(H['meaning'], L)}</h4><p>{_esc(tx(s['meaning'], L))}</p>",
                    (f"<h4>{tx(H['params'], L)}</h4>{params_html}" if params_html else ""),
                    f"<h4>{tx(H['results'], L)}</h4>{results_html or '<p class=muted>' + _esc(tx(H['not_run'], L)) + '</p>'}",
                    (f"<h4>{tx(H['interpretation'], L)}</h4>{_findings_html(findings, L)}" if findings else "")])


# ------------------------------------------------------------------------------------------- parameters actually used
def actual_values(wf) -> dict:
    """Parameter values the run really used: the config, then the protocol of the first MD run, then engine defaults."""
    from ..engine.protocol import TIERS, make_protocol
    from ..sampling.binding import BindingConfig
    cfg = wf.cfg
    md, dk, b = cfg.get("md") or {}, cfg.get("docking") or {}, cfg.get("binding") or {}
    tier = md.get("tier", "teaching")
    v = {"tier": tier, "restraints": md.get("restraints") or "standard", "replicas": int(md.get("replicas", 1)),
         "solvent": md.get("solvent", "explicit"), "box_shape": md.get("box_shape", "dodecahedron"),
         "docking_mode": dk.get("mode", "independent"), "exhaustiveness": dk.get("exhaustiveness", 16), "n_poses": dk.get("n_poses", 9),
         "binding": bool(b.get("enabled"))}
    from ..workflow import TIER_PADDING_NM
    v["padding_nm"] = md.get("padding_nm") if md.get("padding_nm") is not None else TIER_PADDING_NM.get(tier, 0.8)
    ions = md.get("ions") or {}
    v.update({"ion_positive": ions.get("positive", "Na+"), "ion_negative": ions.get("negative", "Cl-"),
              "ion_concentration_molar": ions.get("concentration_molar", md.get("ionic_strength_molar", 0.15)),
              "neutralize": ions.get("neutralize", True)})
    proto = None
    runs = (wf.state()["steps"].get("md_runs") or {}).get("runs") or {}
    cases = (wf.state()["steps"].get("md_cases") or {}).get("cases") or {}
    for key, r in runs.items():
        if r.get("run_ids") and key in cases:
            try:
                from ..project import Run
                proto = Run(wf.project.case(cases[key]["case_id"]), r["run_ids"][0]).manifest().get("protocol")
            except Exception:  # noqa: BLE001
                proto = None
            if proto:
                break
    if not proto:
        try:
            p = make_protocol(tier, production_ns=md.get("production_ns"), restraints=v["restraints"])
            proto = p.to_dict()
            for st in proto["stages"]:
                st.update((md.get("stage_overrides") or {}).get(st["name"], {}))
        except Exception:  # noqa: BLE001
            proto = {"stages": []}
    st = {s["name"]: s for s in proto.get("stages") or []}
    mn, nvt, npt, prod = (st.get(k, {}) for k in ("minimize", "nvt", "npt", "production"))
    v.update({"minimize_iterations": mn.get("max_iterations"), "minimize_tolerance": mn.get("tolerance_kj_mol_nm"),
              "heat_start_k": nvt.get("start_temperature_k"), "nvt_ps": nvt.get("length_ps"), "npt_ps": npt.get("length_ps"),
              "temperature_k": prod.get("temperature_k"), "pressure_bar": prod.get("pressure_bar"),
              "friction_per_ps": prod.get("friction_per_ps"), "timestep_fs": prod.get("timestep_fs"),
              "production_ns": (prod.get("length_ps") or 0) / 1000.0 if prod else None,
              "trajectory_interval_ps": prod.get("trajectory_interval_ps")})
    if v["binding"]:
        try:
            bc = wf._binding_config(b)
        except Exception:  # noqa: BLE001
            bc = BindingConfig()
        for k in ("pull_distance_nm", "pull_velocity_nm_per_ps", "k_pull", "k_umbrella", "window_equil_ps", "window_prod_ps",
                  "target_overlap"):
            v[k] = getattr(bc, k)
    _ = TIERS
    return {k: x for k, x in v.items() if x is not None}


def _param_table(doc: Doc, rows: list[dict], caption) -> str:
    L = doc.lang
    out = []
    for r in rows:
        tag = f"<span class='tag changed'>{_esc(tx(H['changed'], L))}</span>" if r["value"] != r["recommended"] and r["key"] in doc.user_keys else ""
        out.append([_esc(r["label"]), _esc(r["value_text"]) + tag, _esc(r["recommended_text"]), _esc(r["why"])])
    return doc.table([tx(H["parameter"], L), tx(H["value"], L), tx(H["recommended"], L), tx(H["reason"], L)], out, caption)


# ------------------------------------------------------------------------------------------- sections
def _design(doc: Doc, wf) -> str:
    L, cfg = doc.lang, wf.cfg
    rec = cfg.get("receptor") or {}
    ligs = cfg.get("ligands") or []
    rows = [[_esc(l.get("name")), _esc("peptide" if l.get("sequence") else "small molecule" if L == "en" else ("胜肽" if l.get("sequence") else "小分子")),
             f"<code>{_esc(l.get('sequence') or l.get('smiles') or l.get('sdf') or '—')}</code>"] for l in ligs]
    systems = (cfg.get("md") or {}).get("systems") or []
    sys_txt = {"apo": ("蛋白單獨", "protein alone"), "docked_single": ("每個配體各自與蛋白", "each ligand with the protein"),
               "docked_multi": ("所有配體同時與蛋白", "all ligands together with the protein")}
    goal = cfg.get("goal")
    p = (f"<p class=lead>{_esc(tx(('受體', 'Receptor'), L))}: <b>{_esc(rec.get('pdb_id') or Path(str(rec.get('file', '—'))).name)}</b>"
         f"{(' · ' + _esc(tx(('排除鏈', 'excluded chains'), L)) + ' ' + _esc(', '.join(rec.get('exclude_chains')))) if rec.get('exclude_chains') else ''}"
         f" · pH {cfg.get('ph', 7.4)} · {_esc(tx(('模擬系統', 'Systems'), L))}: "
         f"{_esc(', '.join(tx(sys_txt.get(s, (s, s)), L) for s in systems))}"
         + (f" · {_esc(tx(('研究目標', 'Goal'), L))}: {_esc(tx(advisor.GOALS[goal], L))}" if goal in advisor.GOALS else "") + "</p>")
    val = cfg.get("validation")
    if val:
        p += f"<p class=muted>{_esc(tx(('依據文獻', 'Based on'), L))}: {_esc((val.get('paper') or {}).get('citation', ''))}</p>"
    tab = doc.table([tx(("名稱", "Name"), L), tx(("種類", "Type"), L), tx(("結構（SMILES 或序列）", "Structure (SMILES or sequence)"), L)],
                    rows, ("研究的配體", "Ligands studied")) if rows else ""
    return _section(doc, doc.next(), "design", "", p + tab, [])


def _structure(doc: Doc, wf) -> str:
    L = doc.lang
    g = load_json(wf.dir / "structure_gates.json", {})
    gates = g.get("gates") or []
    params = doc.table([tx(H["parameter"], L), tx(H["value"], L)],
                       [[tx(("pH", "pH"), L), str(wf.cfg.get("ph", 7.4))],
                        [tx(("保留的輔因子與金屬", "Cofactors and metals kept"), L), _esc(", ".join(wf.cfg.get("keep_hetero") or []) or "—")]],
                       ("受體準備參數", "Receptor preparation parameters"))
    rows = [[_esc(x.get("name")), _esc(x.get("status")), _esc(x.get("explanation"))] for x in gates]
    prot = (wf.state()["steps"].get("receptor_docking") or {}).get("protonation") or {}
    res = doc.table([tx(("檢查項目", "Check"), L), tx(("結果", "Result"), L), tx(("說明", "Explanation"), L)], rows,
                    ("結構可信度檢查", "Structure validity checks")) if rows else ""
    if prot.get("pocket_flags"):
        res += doc.table(["Residue", "pKa", tx(("注意", "Flag"), L)],
                         [[_esc(f["residue"]), f"{f['pka']:.1f}", _esc("；".join(f["flags"]))] for f in prot["pocket_flags"]],
                         ("口袋殘基的 pKa 審查（PROPKA；未自動更改）", "Pocket residue pKa review (PROPKA; not changed automatically)"), {1})
    return _section(doc, doc.next(), "structure", params, res, I.structure(gates))


def _screen(doc: Doc, wf) -> str:
    st = wf.state()["steps"]
    d = st.get("screen_docking") or {}
    if not (wf.cfg.get("screen") or d):
        return ""
    L = doc.lang
    from ..docking.screen import rank_screen, failed_rows
    res = load_json(d.get("results", ""), {}) if d.get("results") else {}
    man = load_json((st.get("screen_library") or {}).get("manifest", ""), {}) if st.get("screen_library") else {}
    scfg = wf.cfg.get("screen") or {}
    rows = rank_screen(res, top_n=int(scfg.get("top_n", 20))) if res else []
    sel = list(scfg.get("select") or [])
    params = doc.table([tx(H["parameter"], L), tx(H["value"], L)],
                       [[tx(("搜尋強度", "Exhaustiveness"), L), str((res.get("params") or {}).get("exhaustiveness", scfg.get("exhaustiveness", 8)))],
                        [tx(("每個化合物的姿勢數", "Poses per compound"), L), str((res.get("params") or {}).get("n_poses", scfg.get("n_poses", 3)))],
                        [tx(("化合物庫", "Library"), L), _esc(Path(str(scfg.get("library", "—"))).name)]],
                       ("篩選參數", "Screening parameters"))
    out = ""
    for k, cap in (("top", ("前段化合物分數", "Scores of the leading compounds")), ("scatter", ("分數與重原子數", "Score against heavy-atom count")),
                   ("histogram", ("分數分佈", "Score distribution"))):
        pth = ((d.get("plots") or {}).get(k) or {}).get("png")
        if pth:
            out += doc.figure(pth, cap)
    if rows:
        out += doc.table([tx(("名次", "Rank"), L), tx(("化合物", "Compound"), L), "Score (kcal mol⁻¹)", tx(("與最佳差距", "Δ to best"), L),
                          tx(("重原子", "Heavy atoms"), L), tx(("配體效率", "Ligand efficiency"), L), tx(("選入", "Selected"), L)],
                         [[str(r["rank"]), _esc(r["name"]), f"{r['score']:.2f}", f"{r['delta_to_best']:+.2f}", _fmt(r["heavy_atoms"], 0),
                           _fmt(r["ligand_efficiency"], 3), "✔" if r["name"] in sel else ""] for r in rows[:30]],
                         ("篩選排名（前 30 名）", "Screening ranking (top 30)"), {0, 2, 3, 4, 5})
    bad = failed_rows(res, man) if res else []
    if bad:
        out += doc.table([tx(("化合物", "Compound"), L), tx(("階段", "Stage"), L), tx(("原因", "Reason"), L)],
                         [[_esc(b["name"]), _esc(b["stage"]), _esc(b.get("error", ""))] for b in bad[:60]],
                         ("未納入篩選的化合物", "Compounds not screened"))
    return _section(doc, doc.next(), "screen", params, out, I.screen(rows, len(bad), sel))


def _docking(doc: Doc, wf, vals, f, goal) -> str:
    L = doc.lang
    d = wf.state()["steps"].get("docking") or {}
    rows = [r for r in advisor.parameter_table(vals, f, goal, L) if r["group_key"] == "docking"]
    params = _param_table(doc, rows, ("對接參數", "Docking parameters"))
    if not d:
        return _section(doc, doc.next(), "docking", params, "", [])
    res = load_json(d["result"], {})
    sel = (wf.state()["steps"].get("pose_selection") or {}).get("selection", {})
    box = res.get("box") or {}
    out = (f"<p>{_esc(tx(('搜尋區中心', 'Box centre'), L))} {_esc(box.get('center'))} Å · {_esc(tx(('尺寸', 'size'), L))} "
           f"{_esc(box.get('size'))} Å · {_esc(tx(('來源', 'source'), L))} {_esc(box.get('source'))}</p>")
    chosen = {}
    for v in (sel.get("ligands") or {}).values():
        chosen.setdefault(v.get("entry"), set()).add(v.get("rank"))
    for e in res.get("entries", []):
        trs = []
        for p in e["poses"]:
            tag = ("✔ " + tx(("選用", "used"), L) if p["rank"] in chosen.get(e["name"], set()) else "") + \
                  (" ★ " + tx(("推薦", "recommended"), L) if p.get("recommended") else "") + \
                  (" ⚠ " + tx(("碰撞", "clash"), L) if p.get("clash") else "")
            trs.append([str(p["rank"]), f"{p['score']:.2f}", f"{p['cluster']} ({p['cluster_size']})", str(p["contacts"]),
                        _fmt(p.get("rmsd_ref")), tag])
        out += doc.table([tx(("名次", "Rank"), L), "Score (kcal mol⁻¹)", tx(("叢集（大小）", "Cluster (size)"), L),
                          tx(("接觸殘基數", "Contacts"), L), tx(("與晶體 RMSD（Å）", "RMSD to crystal (Å)"), L), ""],
                         trs, (f"{e['name']} 的對接姿勢", f"Docking poses of {e['name']}"), {0, 1, 3, 4})
        if e.get("reason"):
            out += f"<p class=muted>{_esc(tx(('系統推薦理由', 'Reason for the recommendation'), L))}: {_esc(e['reason'])}</p>"
    return _section(doc, doc.next(), "docking", params, out, I.docking(res, sel))


def _peptide(doc: Doc, wf) -> str:
    st = wf.state()
    cpp, acc = st.get("cpp") or {}, st.get("peptide_access") or {}
    if not cpp and not acc:
        return ""
    L = doc.lang
    loc = {"intracellular": ("胞內", "intracellular"), "extracellular-membrane": ("膜外側", "extracellular, membrane"),
           "secreted": ("分泌或胞外", "secreted or extracellular")}
    prm = [[f"<code>{_esc(l.get('sequence'))}</code>", _esc(l.get("name")),
            _esc(tx(loc.get(str(l.get("target_location")), (l.get("target_location") or "未指定", l.get("target_location") or "not specified")), L)),
            _esc(l.get("termini", "charged"))] for l in wf.cfg.get("ligands") or [] if l.get("sequence")]
    params = doc.table([tx(("序列", "Sequence"), L), tx(("名稱", "Name"), L), tx(("作用標靶位置", "Target location"), L),
                        tx(("末端", "Termini"), L)], prm, ("胜肽設定", "Peptide settings")) if prm else ""
    rows = []
    for name, r in cpp.items():
        stt = {"實驗證實": "experimentally confirmed", "計算預測": "computational prediction", "未評估": "not assessed", "不適用": "not applicable",
               "可能穿膜": "likely to penetrate", "不太可能穿膜": "unlikely to penetrate"}
        tr = (lambda x: stt.get(x, x)) if L == "en" else (lambda x: x)
        rows.append([_esc(name), tx(("穿膜性", "Cell penetration"), L), _esc(tr(r.get("status", ""))), _esc(tr(r.get("prediction", "—"))),
                     _esc(r.get("explanation", ""))])
    for name, r in acc.items():
        for part, lab in (("precheck", ("對接前：搜尋區與大小", "Before docking: box and size")), ("pose", ("選用姿勢：埋藏與距離", "Chosen pose: burial and distance"))):
            g = r.get(part)
            if g:
                rows.append([_esc(name), tx(lab, L), _esc(g.get("gate", "")), "", _esc(g.get("explanation", ""))])
    out = doc.table([tx(("胜肽", "Peptide"), L), tx(("檢查", "Check"), L), tx(("狀態", "Status"), L), tx(("預測", "Prediction"), L),
                     tx(("說明", "Explanation"), L)], rows, ("胜肽科學檢查", "Peptide scientific checks"))
    for name, r in cpp.items():
        sug = r.get("redesign_suggestions") or {}
        if sug:
            items = [c for b in sug.values() for c in b]
            out += doc.table([tx(("序列", "Sequence"), L), tx(("設計方式", "Design"), L), tx(("預測分數", "Predicted score"), L),
                              tx(("淨電荷", "Net charge"), L)],
                             [[f"<code>{_esc(c['sequence'])}</code>", _esc(c["how"]), f"{c['score']}/8", f"{c['net_charge']:+d}"] for c in items[:9]],
                             (f"{name} 的替代設計（假設，需實驗或外部工具確認）", f"Redesign options for {name} (hypotheses to be confirmed experimentally or with external predictors)"),
                             {2, 3})
    return _section(doc, doc.next(), "peptide", params, out, I.peptide(cpp, acc))


def _md(doc: Doc, wf, vals, f, goal) -> str:
    L = doc.lang
    rows = [r for r in advisor.parameter_table(vals, f, goal, L) if r["group_key"] in ("system", "equil", "prod")]
    params = _param_table(doc, rows, ("模擬參數", "Simulation parameters"))
    cases = (wf.state()["steps"].get("md_cases") or {}).get("cases", {})
    runs = (wf.state()["steps"].get("md_runs") or {}).get("runs", {})
    ana = wf.state()["steps"].get("analysis") or {}
    sums = ana.get("summaries") or {}
    if not cases:
        return _section(doc, doc.next(), "md", params, "", [])
    trs = []
    metrics = {}
    restrained = False
    for key, c in cases.items():
        r = runs.get(key, {})
        s = sums.get(key, {})
        restrained = restrained or bool(s.get("restrained_production"))
        if s.get("metrics_file"):
            metrics[key] = load_json(s["metrics_file"], {})
        bound = "; ".join(f"{rn}: {tx(('留在口袋', 'stays'), L) if v['stays_bound'] else tx(('離開', 'leaves'), L)} ({v['rmsd_last20_A']:.1f} Å)"
                          for rn, v in (s.get("ligands") or {}).items()) or "—"
        link = ""
        if r.get("run_ids"):
            try:
                from ..project import Run
                rp = build_run_report(Run(wf.project.case(c["case_id"]), r["run_ids"][0]))
                link = f"<a href='{rp.as_uri()}'>{_esc(tx(('單次模擬報告', 'run report'), L))}</a>"
            except Exception:  # noqa: BLE001
                link = ""
        trs.append([_esc(key), _esc(", ".join(c.get("ligands") or []) or "—"), _esc(r.get("status", "—")),
                    _fmt(s.get("rmsd_backbone_mean_A")) + _restrained_tag(s, L), _esc(bound), link])
    out = doc.table([tx(("系統", "System"), L), tx(("配體", "Ligands"), L), tx(("狀態", "Status"), L),
                     tx(("主鏈 RMSD 平均（Å）", "Mean backbone RMSD (Å)"), L), tx(("配體（最後 20 % 的口袋 RMSD）", "Ligand (pocket RMSD, last 20 %)"), L), ""],
                    trs, ("各系統的模擬結果摘要", "Summary of the simulated systems"), {3})
    comp = ana.get("comparison") or {}
    if (comp.get("figures") or {}).get("compare"):
        out += doc.figure(comp["figures"]["compare"]["png"], ("蛋白單獨與複合物的主鏈 RMSD（上）與 Cα RMSF（下）。",
                                                             "Backbone RMSD (top) and Cα RMSF (bottom) of the protein alone and the complexes."))
    for key, s in sums.items():
        for k, fig in (s.get("figures") or {}).items():
            if k.startswith("contacts_"):
                out += doc.figure(fig["png"], (f"{key}：口袋殘基與配體的接觸頻率。", f"{key}: contact frequency between pocket residues and the ligand."))
    findings = I.md(sums, metrics, restrained) + I.rigidified(comp.get("most_rigidified_on_binding") or [])
    return _section(doc, doc.next(), "md", params, out, findings)


def _binding(doc: Doc, wf, vals, f, goal) -> str:
    L = doc.lang
    b = (wf.state()["steps"].get("binding") or {}).get("results", {})
    if not wf.cfg.get("binding", {}).get("enabled") and not b:
        return ""
    rows = [r for r in advisor.parameter_table(vals, f, goal, L) if r["group_key"] == "binding" and r["key"] != "binding"]
    params = _param_table(doc, rows, ("結合自由能參數", "Binding free-energy parameters"))
    if not b:
        return _section(doc, doc.next(), "binding", params, "", [])
    pm = lambda v, e: "—" if v is None else (f"{v:.1f} ± {e:.1f}" if e is not None else f"{v:.1f}")  # noqa: E731
    trs = [[_esc(n), pm(r.get("delta_pmf_kj_mol"), r.get("delta_pmf_err_kj_mol")),
            pm(r.get("dG_standard_kj_mol"), r.get("dG_err_kj_mol")) if r.get("dG_standard_kj_mol") is not None else tx(("不輸出", "not reported"), L),
            _fmt(r.get("dG_standard_kcal_mol"), 1) if r.get("dG_standard_kcal_mol") is not None else "—",
            _fmt(r.get("r_min_nm"), 3), _fmt(r.get("max_force"), 0), _fmt(r.get("work"), 1)] for n, r in b.items()]
    out = doc.table([tx(("配體", "Ligand"), L), "ΔPMF (kJ mol⁻¹)", "ΔG° (kJ mol⁻¹)", "ΔG° (kcal mol⁻¹)", tx(("結合距離（nm）", "Bound distance (nm)"), L),
                     tx(("SMD 最大拉力（kJ mol⁻¹ nm⁻¹）", "SMD peak force (kJ mol⁻¹ nm⁻¹)"), L), tx(("SMD 功（kJ mol⁻¹）", "SMD work (kJ mol⁻¹)"), L)],
                    trs, ("結合自由能結果", "Binding free-energy results"), {1, 2, 3, 4, 5, 6})
    for name, r in b.items():
        figs = r.get("figures") or {}
        out += f"<h3>{_esc(name)}</h3>"
        for k, cap in (("smd", ("SMD 拉力、功與距離，對彈簧位置作圖；功與拉速有關，不是自由能。", "SMD force, work and distance against spring position; the work depends on the pulling speed and is not a free energy.")),
                       ("histograms", ("各窗口沿反應座標的取樣分佈；相鄰窗口必須重疊，剖面才能連續。", "Sampling distribution of each window along the reaction coordinate; neighbouring windows must overlap for a continuous profile.")),
                       ("pmf", ("自由能剖面（PMF）與自助法誤差；井深為 ΔPMF。", "Free-energy profile (PMF) with bootstrap error; the depth is ΔPMF."))):
            if figs.get(k):
                out += doc.figure(figs[k]["png"], (f"{name}：{cap[0]}", f"{name}: {cap[1]}"))
        if r.get("dG_withheld"):
            out += f"<p class=warn>{_esc(tx(('ΔG° 不輸出的原因', 'Why ΔG° is not reported'), L))}: {_esc(str(r['dG_withheld']))}</p>"
    comp = (wf.state()["steps"].get("binding") or {}).get("comparison") or {}
    out += _comparison_html(comp, L)
    findings = I.binding(b)
    for ctx, c in (comp.get("contexts") or {}).items():
        if c.get("status") == "PASS" and c.get("why"):
            findings.append(I.F("note", c["why"], c["why"]))
    return _section(doc, doc.next(), "binding", params, out, findings)


def _comparison_html(comp: dict, lang: str = "zh") -> str:
    """WP9: ΔΔ ranking per context and co-occupancy shifts."""
    if not comp or not (comp.get("contexts") or comp.get("co_occupancy")):
        return ""
    zh = lang == "zh"
    parts = ["<h3>" + ("配體間比較（ΔΔ）" if zh else "Comparison between ligands (ΔΔ)") + "</h3>"]
    for ctx, c in comp.get("contexts", {}).items():
        label = (("各配體單獨結合" if zh else "Each ligand bound alone") if ctx == "single" else
                 (f"共同口袋（{_esc(ctx.split(':', 1)[1])}）" if zh else f"Shared pocket ({_esc(ctx.split(':', 1)[1])})"))
        if c.get("status") != "PASS":
            parts.append(f"<p class=muted>{label}：{_esc(c.get('why', ''))}</p>")
            continue
        parts.append(f"<p><b>{label}</b> — {_esc(c['why'])}</p><table><tr><th>{'配體' if zh else 'Ligand'}</th>"
                     f"<th class=num>{_esc(c['quantity'])} ({_esc(c['unit'])})</th><th class=num>σ</th><th>{'判定' if zh else 'Verdict'}</th></tr>")
        for r in c["rows"]:
            parts.append(f"<tr><td>{_esc(r['key'])}</td><td class=num>{r['delta']:+.2f}</td><td class=num>{'—' if r['sigma'] is None else r['sigma']}</td>"
                         f"<td>{_esc(r['verdict'])}</td></tr>")
        parts.append("</table>")
    if comp.get("co_occupancy"):
        parts.append("<p><b>" + ("共存效應" if zh else "Co-occupancy effect") + "</b>（" + ("共同口袋 − 單獨結合" if zh else "shared pocket minus alone")
                     + "）</p><ul>" + "".join(f"<li>{_esc(c['why'])}</li>" for c in comp["co_occupancy"]) + "</ul>")
    parts.append("<ul class=muted>" + "".join(f"<li>{_esc(n)}</li>" for n in comp.get("notes", [])) + "</ul>")
    return "".join(parts)


def _binding_section(wf, lang: str = "zh") -> str:
    """Binding section on its own (kept for callers and tests)."""
    doc = Doc(lang)
    doc.user_keys = set(advisor.values_from_config(wf.cfg))
    n = {"i": 0}
    doc.next = lambda: n.__setitem__("i", n["i"] + 1) or n["i"]
    vals = actual_values(wf)
    return _binding(doc, wf, vals, advisor.features_from_config(wf.cfg), wf.cfg.get("goal") or "binding")


# ------------------------------------------------------------------------------------------- methods and limitations
def methods_text(wf, vals: dict, lang: str) -> str:
    cfg = wf.cfg
    rec = cfg.get("receptor") or {}
    rid = rec.get("pdb_id") or Path(str(rec.get("file", "the supplied structure"))).name
    ligs = cfg.get("ligands") or []
    peps = [l for l in ligs if l.get("sequence")]
    sim = vals.get("docking_mode") == "simultaneous"
    hmr = vals.get("timestep_fs", 2) > 2
    box = {"dodecahedron": ("菱形十二面體", "rhombic dodecahedral"), "cube": ("立方體", "cubic")}.get(vals.get("box_shape"), ("", ""))
    salt = f"{vals.get('ion_positive', 'Na+')[:-1]}{vals.get('ion_negative', 'Cl-')[:-1]}"
    if lang == "zh":
        s = [f"受體結構（{rid}）以 PDBFixer 移除結晶添加物與水、補齊缺失重原子，並於 pH {cfg.get('ph', 7.4)} 加氫。"]
        if ligs:
            s.append(f"{len(ligs)} 個配體以 AutoDock Vina {'同時' if sim else '分別'}對接（搜尋強度 {vals.get('exhaustiveness')}，每個配體保留 {vals.get('n_poses')} 個姿勢），"
                     "依分數、叢集大小與接觸殘基選定起始姿勢。")
        s.append(f"系統以 Amber ff14SB 描述蛋白" + ("與胜肽" if peps else "") + ("、OpenFF Sage 2.2 描述小分子配體（部分電荷以 NAGL 或 AM1-BCC 計算）" if len(peps) < len(ligs) else "")
                 + f"，置於{box[0]} TIP3P 水盒（蛋白到盒邊 {vals.get('padding_nm')} nm），以 {salt} 中和淨電荷並調整至 {vals.get('ion_concentration_molar')} M。")
        s.append(f"長程靜電以 PME 計算，非鍵截斷 1.0 nm，含氫鍵以 HBonds 約束" + ("並以氫質量重分配（3 amu）" if hmr else "")
                 + f"。系統經能量最小化（最多 {vals.get('minimize_iterations')} 步），於 NVT 由 {vals.get('heat_start_k'):g} K 升溫至 {vals.get('temperature_k'):g} K（{vals.get('nvt_ps'):g} ps），"
                 f"再於 NPT（{vals.get('pressure_bar'):g} bar，Monte Carlo 恆壓器）平衡 {vals.get('npt_ps'):g} ps，期間逐步釋放位置約束（{vals.get('restraints')} 策略）。")
        s.append(f"正式模擬以 Langevin 中點積分器（摩擦係數 {vals.get('friction_per_ps'):g} ps⁻¹、步長 {vals.get('timestep_fs'):g} fs）進行 {vals.get('production_ns'):g} ns，"
                 f"獨立重複 {vals.get('replicas')} 次，每 {vals.get('trajectory_interval_ps'):g} ps 儲存一幀。所有模擬以 OpenMM 執行，分析以 MDTraj 計算主鏈 RMSD、Cα RMSF、配體口袋 RMSD 與接觸頻率。")
        if vals.get("binding"):
            s.append(f"結合自由能以導向分子動力學（拉速 {vals.get('pull_velocity_nm_per_ps'):g} nm ps⁻¹、彈簧常數 {vals.get('k_pull'):g} kJ mol⁻¹ nm⁻²，拉離 {vals.get('pull_distance_nm'):g} nm）產生解離路徑，"
                     f"沿路徑設置傘狀採樣窗口（彈簧常數 {vals.get('k_umbrella'):g} kJ mol⁻¹ nm⁻²，每窗口平衡 {vals.get('window_equil_ps'):g} ps、取樣 {vals.get('window_prod_ps'):g} ps，依重疊自適應加窗），以 MBAR 合併為自由能剖面，"
                     "誤差以自助法估計，並以前後半段一致性檢查收斂。")
        return "".join(s)
    s = [f"The receptor structure ({rid}) was prepared with PDBFixer: crystallisation additives and water were removed, "
         f"missing heavy atoms were added and hydrogens were placed at pH {cfg.get('ph', 7.4)}. "]
    if ligs:
        s.append(f"{len(ligs)} ligand{'s were' if len(ligs) > 1 else ' was'} docked {'simultaneously' if sim else 'independently'} with AutoDock Vina "
                 f"(exhaustiveness {vals.get('exhaustiveness')}, {vals.get('n_poses')} poses per ligand), and the starting pose was chosen from score, "
                 "cluster size and contact residues. ")
    s.append("The protein" + (" and peptide" if peps else "") + " were described with Amber ff14SB"
             + (" and small-molecule ligands with OpenFF Sage 2.2 (partial charges from NAGL or AM1-BCC)" if len(peps) < len(ligs) else "")
             + f". Each system was solvated in a {box[1]} TIP3P water box with {vals.get('padding_nm')} nm between protein and box edge, "
             f"neutralised and brought to {vals.get('ion_concentration_molar')} M {salt}. ")
    s.append("Long-range electrostatics used PME with a 1.0 nm non-bonded cut-off; bonds to hydrogen were constrained"
             + (" and hydrogen masses were repartitioned to 3 amu" if hmr else "") + ". "
             f"After energy minimisation (up to {vals.get('minimize_iterations')} steps), the system was heated from {vals.get('heat_start_k'):g} K to "
             f"{vals.get('temperature_k'):g} K under NVT ({vals.get('nvt_ps'):g} ps) and equilibrated under NPT ({vals.get('pressure_bar'):g} bar, "
             f"Monte Carlo barostat) for {vals.get('npt_ps'):g} ps while position restraints were released ({vals.get('restraints')} strategy). ")
    s.append(f"Production used a Langevin middle integrator (friction {vals.get('friction_per_ps'):g} ps⁻¹, time step {vals.get('timestep_fs'):g} fs) "
             f"for {vals.get('production_ns'):g} ns in {vals.get('replicas')} independent replica{'s' if vals.get('replicas', 1) > 1 else ''}, "
             f"saving a frame every {vals.get('trajectory_interval_ps'):g} ps. All simulations were run with OpenMM; backbone RMSD, Cα RMSF, "
             "ligand pocket RMSD and contact frequencies were computed with MDTraj. ")
    if vals.get("binding"):
        s.append(f"Binding free energies were obtained by steered molecular dynamics (pulling velocity {vals.get('pull_velocity_nm_per_ps'):g} nm ps⁻¹, "
                 f"spring constant {vals.get('k_pull'):g} kJ mol⁻¹ nm⁻², pulling distance {vals.get('pull_distance_nm'):g} nm) followed by umbrella "
                 f"sampling along the path (spring constant {vals.get('k_umbrella'):g} kJ mol⁻¹ nm⁻², {vals.get('window_equil_ps'):g} ps equilibration "
                 f"and {vals.get('window_prod_ps'):g} ps sampling per window, windows added adaptively by overlap); the windows were combined with MBAR, "
                 "errors were estimated by bootstrapping and convergence was checked by agreement between the first and second halves.")
    return "".join(s)


def _limitations(doc: Doc, wf) -> list[str]:
    L = doc.lang
    items = []
    for name, r in (wf.state().get("cpp") or {}).items():
        if r.get("limitation"):
            items.append(f"{name}: {r['limitation']}")
    for name, r in (wf.state().get("peptide_access") or {}).items():
        for part in ("precheck", "pose"):
            g = r.get(part) or {}
            if g.get("advisory"):
                items.append(f"{name}: {g.get('explanation', '')}")
    for name, r in ((wf.state()["steps"].get("binding") or {}).get("results") or {}).items():
        items += [f"{name}: {c}" for c in r.get("caveats") or []]
    tier = (wf.cfg.get("md") or {}).get("tier", "teaching")
    if tier == "classroom":
        items.append(tx(("本流程使用課堂等級（2 ns），只用於學習流程與檢查，不足以支持科學結論。",
                         "This workflow used the classroom tier (2 ns); it is for learning and checking the workflow and does not support scientific conclusions."), L))
    if int((wf.cfg.get("md") or {}).get("replicas", 1)) < 3:
        items.append(tx(("只有一次模擬，無法報告重複間的標準差。", "Only one replica was run, so no standard deviation between replicas can be reported."), L))
    items.append(tx(("對接分數為經驗評分，誤差約 1 到 2 kcal mol⁻¹，不應直接解讀為結合親和力。",
                     "Docking scores are empirical with an error of about 1–2 kcal mol⁻¹ and should not be read as binding affinities."), L))
    return items


# ------------------------------------------------------------------------------------------- build
def build_workflow_report(wf, out_path: Path | None = None, *, lang: str | None = None) -> Path:
    out_path = Path(out_path) if out_path else wf.dir / "workflow_report.html"
    L = lang or wf.cfg.get("language") or "en"
    L = L if L in ("en", "zh") else "en"
    doc = Doc(L)
    counter = {"n": 0}

    def nxt():
        counter["n"] += 1
        return counter["n"]
    doc.next = nxt
    cfg = wf.cfg
    goal = cfg.get("goal") or {"classroom": "teaching", "teaching": "screening", "research": "publication"}.get((cfg.get("md") or {}).get("tier"), "teaching")
    vals = actual_values(wf)
    doc.user_keys = set(advisor.values_from_config(cfg))
    f = advisor.features_from_config(cfg)
    body = [_design(doc, wf), _structure(doc, wf), _screen(doc, wf), _docking(doc, wf, vals, f, goal), _peptide(doc, wf),
            _md(doc, wf, vals, f, goal), _binding(doc, wf, vals, f, goal)]
    # key findings from every section's interpretation (recomputed cheaply from the same data)
    st = wf.state()
    secs = [I.structure((load_json(wf.dir / "structure_gates.json", {}) or {}).get("gates") or [])]
    d = st["steps"].get("docking")
    if d:
        secs.append(I.docking(load_json(d["result"], {}), (st["steps"].get("pose_selection") or {}).get("selection", {})))
    secs.append(I.peptide(st.get("cpp") or {}, st.get("peptide_access") or {}))
    ana = st["steps"].get("analysis") or {}
    secs.append(I.md(ana.get("summaries") or {}))
    secs.append(I.binding((st["steps"].get("binding") or {}).get("results") or {}))
    key = I.headline(secs)
    rows_log = [r for r in wf.project.decisions.read() if str(r.get("stage", "")).startswith(
        ("workflow", "docking", "binding", "build", "engine", "screen", "gui", "peptide"))]
    log = doc.table([tx(("時間", "Time"), L), tx(("階段", "Stage"), L), tx(("項目", "Item"), L), tx(("選擇", "Choice"), L),
                     tx(("類型", "Type"), L), tx(("理由", "Reason"), L)],
                    [[_esc(str(r.get("at", ""))[:19].replace("T", " ")), _esc(r.get("stage", "")), _esc(r.get("what", "")),
                      f"<code>{_esc(r.get('choice', ''))}</code>", _esc(r.get("kind", "")), _esc(r.get("why", ""))] for r in rows_log],
                    ("自動與人工決策（依時間）", "Automatic and human decisions (chronological)"))
    n_meth = nxt()
    n_lim = nxt()
    html = [f"<!doctype html><html lang={'zh-Hant' if L == 'zh' else 'en'}><head><meta charset=utf-8>"
            f"<title>{_esc(tx(H['title'], L))} — {_esc(wf.name)}</title><style>{CSS}</style></head><body>",
            f"<h1>{_esc(tx(H['title'], L))}</h1>",
            f"<p class=meta>{_esc(tx(H['project'], L))}: {_esc(wf.project.name)} · {_esc(tx(H['workflow'], L))}: {_esc(wf.name)} · "
            f"{_esc(tx(H['generated'], L))}: {now_iso()[:19].replace('T', ' ')} UTC</p>",
            (f"<p class=meta>{_esc(tx(H['zh_note'], L))}</p>" if L == "en" else ""),
            f"<div class=box><b>{_esc(tx(H['key_findings'], L))}</b>{_findings_html(key, L) or '<p class=muted>—</p>'}</div>",
            *body,
            f"<h2>{n_meth}. {_esc(tx(H['methods'], L))}</h2><div class=methods>{_esc(methods_text(wf, vals, L))}</div>",
            f"<h2>{n_lim}. {_esc(tx(H['limitations'], L))}</h2><ul>" + "".join(f"<li>{_esc(x)}</li>" for x in _limitations(doc, wf)) + "</ul>",
            _viewer_section(wf, L),
            f"<h2>{_esc(tx(H['appendix_params'], L))}</h2>" + _param_table(doc, advisor.parameter_table(vals, f, goal, L),
                                                                         ("全部參數：採用值、本案例建議值與理由", "All parameters: value used, recommendation for this case and reason")),
            f"<h2>{_esc(tx(H['appendix_log'], L))}</h2>{log}",
            f"<h2>{_esc(tx(H['appendix_cfg'], L))}</h2><details><summary>config.json</summary><pre>{_esc(json.dumps(cfg, ensure_ascii=False, indent=1))}</pre></details>",
            __import__("md20.util.stamp", fromlist=["html_footer"]).html_footer(), "</body></html>"]
    out_path.write_text("".join(html), encoding="utf-8")
    return out_path


def _viewer_section(wf, lang: str = "zh") -> str:
    """WP13: offline 3D view (inline JS) of each docked case — production trajectory if available, else the start."""
    try:
        from ..gui.views import viewer_targets, scene_for, viewer_html
    except Exception:  # noqa: BLE001
        return ""
    parts = []
    by_key: dict = {}
    for t in viewer_targets(wf):
        if t["key"] == "apo":
            continue
        by_key[t["key"]] = t if t["mode"] == "traj" or t["key"] not in by_key else by_key[t["key"]]
    for key, t in by_key.items():
        try:
            sc = scene_for(t, max_frames=40)
        except Exception:  # noqa: BLE001  (e.g. no mdtraj): fall back to the start structure
            try:
                sc = scene_for({**t, "mode": "start"})
                t = {**t, "label": f"{key}：建模起始結構"}
            except Exception:  # noqa: BLE001
                continue
        parts.append(f"<h3>{_esc(t['label'])}</h3>" + viewer_html(sc, standalone=False, height_px=380))
    if not parts:
        return ""
    return ("<h2>" + ("3D 檢視（離線，可拖曳旋轉；軌跡可播放）" if lang == "zh" else "3D view (offline; drag to rotate, the trajectory can be played)")
            + "</h2>" + "".join(parts))
