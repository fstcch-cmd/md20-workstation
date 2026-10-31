"""Workflow summary report: docking → pose choice → MD (apo vs docked) → analysis → binding strength."""
from __future__ import annotations

import json
from pathlib import Path

from ..util import load_json, now_iso
from .html import _img, _esc, _CSS, _decisions_table, build_run_report


def _fmt(x, nd: int = 2) -> str:
    return "" if x is None else f"{float(x):.{nd}f}"


def _docking_section(wf) -> str:
    d = (wf.state()["steps"].get("docking") or {})
    if not d:
        return "<p class=muted>（未執行 docking：僅 apo）</p>"
    res = load_json(d["result"], {})
    sel = (wf.state()["steps"].get("pose_selection") or {}).get("selection", {})
    parts = [f"<p>模式 <b>{_esc(res.get('mode'))}</b> · scoring {_esc(res['params'].get('scoring'))} · exhaustiveness "
             f"{res['params'].get('exhaustiveness')} · box center {res['box']['center']} size {res['box']['size']}（{_esc(res['box'].get('source'))}）</p>"]
    for e in res.get("entries", []):
        parts.append(f"<h3>{_esc(e['name'])}{' (' + ' + '.join(e['ligands']) + ')' if e['name'] == 'joint' else ''}</h3>")
        parts.append("<table><tr><th>rank</th><th>score (kcal/mol)</th><th>cluster (size)</th><th>contacts</th><th>RMSD to crystal (Å)</th>"
                     + ("<th>min ligand–ligand (Å)</th>" if e["name"] == "joint" else "") + "<th></th></tr>")
        chosen = {v["rank"] for k, v in sel.get("ligands", {}).items() if v.get("entry") == e["name"]}
        for p in e["poses"]:
            tag = ("✔ 選用" if p["rank"] in chosen else "") + (" ★ 推薦" if p["recommended"] else "") + (" ⚠ 碰撞" if p.get("clash") else "")
            parts.append(f"<tr><td>{p['rank']}</td><td>{p['score']:.2f}</td><td>{p['cluster']} ({p['cluster_size']})</td><td>{p['contacts']}</td>"
                         f"<td>{_fmt(p['rmsd_ref'])}</td>"
                         + (f"<td>{p.get('min_ll_distance')}</td>" if e["name"] == "joint" else "") + f"<td>{tag}</td></tr>")
        parts.append(f"</table><p><b>推薦理由：</b>{_esc(e['reason'])}</p>")
    return "".join(parts)


def _md_section(wf) -> str:
    cases = (wf.state()["steps"].get("md_cases") or {}).get("cases", {})
    runs = (wf.state()["steps"].get("md_runs") or {}).get("runs", {})
    ana = (wf.state()["steps"].get("analysis") or {})
    parts = ["<table><tr><th>系統</th><th>模式</th><th>配體</th><th>MD</th><th>backbone RMSD 平均 (Å)</th><th>配體留在口袋</th><th>報告</th></tr>"]
    for key, c in cases.items():
        r = runs.get(key, {})
        s = (ana.get("summaries") or {}).get(key, {})
        ligs = s.get("ligands") or {}
        bound = "; ".join(f"{rn}: {'是' if v['stays_bound'] else '否'}（末段 {v['rmsd_last20_A']:.1f} Å）" for rn, v in ligs.items()) or "—"
        link = ""
        if r.get("run_ids"):
            case = wf.project.case(c["case_id"])
            from ..project import Run
            run = Run(case, r["run_ids"][0])
            try:
                rp = build_run_report(run)
                link = f"<a href='{rp.as_uri()}'>run 報告</a>"
            except Exception as exc:  # noqa: BLE001
                link = f"（報告失敗：{_esc(exc)}）"
        rm = s.get("rmsd_backbone_mean_A")
        parts.append(f"<tr><td>{_esc(key)}</td><td>{_esc(c['mode'])}</td><td>{_esc(', '.join(c['ligands']) or '—')}</td>"
                     f"<td>{_esc(r.get('status', c.get('status')))}</td><td>{_fmt(rm)}</td><td>{_esc(bound)}</td><td>{link}</td></tr>")
    parts.append("</table>")
    comp = ana.get("comparison") or {}
    if comp.get("figures", {}).get("compare"):
        parts.append(f"<figure>{_img(comp['figures']['compare']['png'])}<figcaption>Apo 與結合態的 backbone RMSD 與 Cα RMSF 疊圖。</figcaption></figure>")
    if comp.get("most_rigidified_on_binding"):
        parts.append("<p><b>結合後柔性下降最多的殘基：</b>" + "、".join(f"{x['residue']}（{x['delta_rmsf_A']:+.2f} Å）" for x in comp["most_rigidified_on_binding"][:8]) + "</p>")
    for key, s in (ana.get("summaries") or {}).items():
        for k, f in (s.get("figures") or {}).items():
            if k.startswith("contacts_"):
                parts.append(f"<figure>{_img(f['png'])}<figcaption>{_esc(key)}：口袋殘基接觸頻率</figcaption></figure>")
    return "".join(parts)


def _binding_section(wf) -> str:
    b = (wf.state()["steps"].get("binding") or {}).get("results", {})
    if not b:
        return "<p class=muted>（未執行 SMD／傘狀採樣）</p>"
    parts = ["<table><tr><th>配體</th><th>ΔPMF 井深 (kJ/mol)</th><th>ΔG° 估計 (kJ/mol)</th><th>ΔG° (kcal/mol)</th><th>結合距離 (nm)</th>"
             "<th>SMD 最大拉力 (kJ/mol/nm)</th><th>SMD 功 (kJ/mol)</th></tr>"]
    for name, r in b.items():
        parts.append(f"<tr><td>{_esc(name)}</td><td>{r.get('delta_pmf_kj_mol')}</td><td>{r.get('dG_standard_kj_mol')}</td>"
                     f"<td>{r.get('dG_standard_kcal_mol')}</td><td>{r.get('r_min_nm') and round(r['r_min_nm'], 3)}</td>"
                     f"<td>{r.get('max_force') and round(r['max_force'])}</td><td>{r.get('work') and round(r['work'], 1)}</td></tr>")
    parts.append("</table>")
    for name, r in b.items():
        figs = r.get("figures") or {}
        parts.append(f"<h3>{_esc(name)}</h3>")
        for k, cap in (("smd", "SMD 拉力與功（不可逆、與速度有關）"), ("histograms", "Window 直方圖（相鄰須重疊）"), ("pmf", "PMF ± bootstrap 誤差")):
            if figs.get(k):
                parts.append(f"<figure>{_img(figs[k]['png'])}<figcaption>{cap}</figcaption></figure>")
        parts.append("<ul>" + "".join(f"<li>{_esc(c)}</li>" for c in r.get("caveats", [])) + "</ul>")
    return "".join(parts)


def build_workflow_report(wf, out_path: Path | None = None) -> Path:
    out_path = Path(out_path) if out_path else wf.dir / "workflow_report.html"
    cfg = wf.cfg
    rows = [r for r in wf.project.decisions.read() if str(r.get("stage", "")).startswith(("workflow", "docking", "binding", "build", "engine"))]
    html = [f"<!doctype html><html lang=zh-Hant><head><meta charset=utf-8><title>MD20 Workflow — {_esc(wf.name)}</title><style>{_CSS}</style></head><body>",
            f"<h1>MD20 Workflow 報告：{_esc(wf.name)}</h1>",
            f"<p class=muted>專案 {_esc(wf.project.name)} · 產生於 {now_iso()}</p>",
            "<h2>1. 設定</h2>", f"<details><summary>config.json</summary><pre>{_esc(json.dumps(cfg, ensure_ascii=False, indent=1))}</pre></details>",
            "<h2>2. 分子對接與 pose 選擇</h2>", _docking_section(wf),
            "<h2>3. 分子動力學（apo vs 對接結合態）</h2>", _md_section(wf),
            "<h2>4. 結合強度（SMD + 傘狀採樣）</h2>", _binding_section(wf),
            "<h2>5. 決策日誌</h2>", _decisions_table(rows), "</body></html>"]
    out_path.write_text("".join(html), encoding="utf-8")
    return out_path
