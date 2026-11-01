"""Workflow summary report: docking → pose choice → MD (apo vs docked) → analysis → binding strength."""
from __future__ import annotations

import json
from pathlib import Path

from ..util import load_json, now_iso
from .html import _img, _esc, _CSS, _decisions_table, build_run_report


def _fmt(x, nd: int = 2) -> str:
    return "" if x is None else f"{float(x):.{nd}f}"


def _screen_section(wf) -> str:
    st = wf.state()["steps"]
    d = st.get("screen_docking") or {}
    if not (wf.cfg.get("screen") or d):
        return ""
    from ..docking.screen import rank_screen, failed_rows
    res = load_json(d.get("results", ""), {}) if d.get("results") else {}
    man = load_json((st.get("screen_library") or {}).get("manifest", ""), {}) if st.get("screen_library") else {}
    rows = rank_screen(res, top_n=int((wf.cfg.get("screen") or {}).get("top_n", 20))) if res else []
    sel = set((wf.cfg.get("screen") or {}).get("select") or [])
    parts = ["<h3>高通量前期篩選</h3>",
             "<p class=muted>縮減搜尋（exhaustiveness {} 、{} 個 pose）的 Vina 分數；只用來剔除化合物，不是結合自由能。"
             "與第 1 名差距 &lt; 1 kcal/mol 的化合物在 Vina 誤差內，名次沒有統計意義。</p>".format(
                 (res.get("params") or {}).get("exhaustiveness", "—"), (res.get("params") or {}).get("n_poses", "—"))]
    if not rows:
        parts.append("<p class=muted>（篩選尚未完成）</p>")
        return "".join(parts)
    for k in ("histogram", "scatter", "top"):
        pth = ((d.get("plots") or {}).get(k) or {}).get("png")
        if pth:
            parts.append(f"<figure style='display:inline-block;max-width:48%'>{_img(pth)}</figure>")
    parts.append("<table><tr><th>名次</th><th>化合物</th><th>score</th><th>Δ最佳</th><th>重原子</th><th>LE</th><th>cluster</th><th>接觸</th><th>推薦</th><th></th></tr>")
    for r in rows[:50]:
        parts.append(f"<tr><td>{r['rank']}</td><td>{_esc(r['name'])}</td><td>{r['score']:.2f}</td><td>{r['delta_to_best']:+.2f}</td>"
                     f"<td>{_fmt(r['heavy_atoms'], 0)}</td><td>{_fmt(r['ligand_efficiency'], 3)}</td><td>{r['cluster_size']}</td><td>{r['contacts']}</td>"
                     f"<td>{_esc(r['recommendation_status'])}</td><td>{'✔ 選入' if r['name'] in sel else ''}{' ≈' if r.get('indistinguishable_from_top') else ''}</td></tr>")
    parts.append("</table>")
    if len(rows) > 50:
        parts.append(f"<p class=muted>只列前 50 名；完整排名在 screen_ranking.csv（共 {len(rows)} 個）。</p>")
    bad = failed_rows(res, man)
    if bad:
        parts.append(f"<p><b>未納入篩選的化合物（{len(bad)}）：</b></p><ul>" +
                     "".join(f"<li>{_esc(b['name'])}（{_esc(b['stage'])} {_esc(b['status'])}）：{_esc(b.get('error', ''))}</li>" for b in bad[:100]) + "</ul>")
    if sel:
        parts.append(f"<p><b>使用者選入正式對接：</b>{_esc(', '.join(sorted(sel)))}（模式 {_esc((wf.cfg.get('screen') or {}).get('next_mode', 'independent'))}）</p>")
    return "".join(parts)


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


def _structure_section(wf) -> str:
    from ..util import load_json
    g = load_json(wf.dir / "structure_gates.json", {})
    if not g:
        return ""
    icon = {"PASS": "✅", "AUTO_FIXED": "🛠", "NEEDS_HUMAN": "⛔"}
    prot = (wf.state()["steps"].get("receptor_docking") or {}).get("protonation") or {}
    ptxt = ""
    if prot.get("pocket_flags"):
        ptxt = ("<h3>口袋質子化（PROPKA 審查，未自動更改）</h3><ul>" +
                "".join(f"<li><b>{_esc(f['residue'])}</b> pKa {f['pka']:.1f}：{_esc('；'.join(f['flags']))}</li>"
                        for f in prot["pocket_flags"]) + "</ul>")
    elif prot.get("note"):
        ptxt = f"<p class=muted>質子化：{_esc(prot['note'])}</p>"
    return ptxt + ("<h3>結構可信度</h3><ul>" + "".join(f"<li>{icon.get(x['status'], '')} <b>{_esc(x['name'])}</b>：{_esc(x['explanation'])}</li>"
                                          for x in g.get("gates", [])) + "</ul>")


def _cpp_section(wf) -> str:
    cpp = wf.state().get("cpp") or {}
    if not cpp:
        return ""
    rows = ["<h3>胜肽穿膜性（CPP）</h3><table><tr><th>胜肽</th><th>狀態</th><th>預測</th><th>說明</th></tr>"]
    for name, r in cpp.items():
        st = r.get("status", "")
        if r.get("override"):
            st += "（使用者覆寫）"
        rows.append(f"<tr><td>{_esc(name)}</td><td>{_esc(st)}</td><td>{_esc(r.get('prediction', '—'))}</td>"
                    f"<td>{_esc(r.get('explanation', ''))}</td></tr>")
    rows.append("</table><p class=muted>「計算預測」僅依序列特徵，不能取代穿膜實驗；胞內標靶的結論需實驗確認。</p>")
    for name, r in cpp.items():
        sug = r.get("redesign_suggestions") or {}
        if not sug:
            continue
        rows.append(f"<h4>{_esc(name)}：無法穿膜時的替代設計建議（假設，需驗證）</h4><ul>")
        label = {"submotifs": "縮短為帶電核心", "cationic": "富集 Arg/Lys", "conjugates": "接穿膜載體"}
        for bucket, items in sug.items():
            for c in items:
                rows.append(f"<li><b>{_esc(c['sequence'])}</b>（{_esc(label.get(bucket, bucket))}：{_esc(c['how'])}）"
                            f" — 預測分數 {c['score']}/8、淨電荷 {c['net_charge']:+d}</li>")
        rows.append("</ul>")
        preds = r.get("predictors") or []
        if preds:
            rows.append("<p class=muted>外部 CPP 預測工具交叉確認：" +
                        "、".join(f'<a href="{_esc(p["url"])}">{_esc(p["name"])}</a>' for p in preds) + "。</p>")
    return "".join(rows)


def _binding_section(wf) -> str:
    b = (wf.state()["steps"].get("binding") or {}).get("results", {})
    if not b:
        return "<p class=muted>（未執行 SMD／傘狀採樣）</p>"
    parts = ["<table><tr><th>配體</th><th>ΔPMF 井深 (kJ/mol)</th><th>ΔG° 估計 (kJ/mol)</th><th>ΔG° (kcal/mol)</th><th>結合距離 (nm)</th>"
             "<th>SMD 最大拉力 (kJ/mol/nm)</th><th>SMD 功 (kJ/mol)</th></tr>"]
    for name, r in b.items():
        dg = r.get('dG_standard_kj_mol') if r.get('dG_standard_kj_mol') is not None else "不輸出"
        dgk = r.get('dG_standard_kcal_mol') if r.get('dG_standard_kcal_mol') is not None else "—"
        pm = lambda v, e: f"{v} ± {e}" if v is not None and e is not None else (v if v is not None else "—")  # noqa: E731
        if r.get('dG_standard_kj_mol') is not None:
            dg = pm(r['dG_standard_kj_mol'], r.get('dG_err_kj_mol'))
        parts.append(f"<tr><td>{_esc(name)}</td><td>{pm(r.get('delta_pmf_kj_mol'), r.get('delta_pmf_err_kj_mol'))}</td><td>{dg}</td>"
                     f"<td>{dgk}</td><td>{r.get('r_min_nm') and round(r['r_min_nm'], 3)}</td>"
                     f"<td>{r.get('max_force') and round(r['max_force'])}</td><td>{r.get('work') and round(r['work'], 1)}</td></tr>")
    parts.append("</table>")
    parts.append(_comparison_html((wf.state()["steps"].get("binding") or {}).get("comparison") or {}))
    for name, r in b.items():
        figs = r.get("figures") or {}
        parts.append(f"<h3>{_esc(name)}</h3>")
        if r.get("caveats"):
            parts.append(f"<p class=warn><b>{_esc(r['caveats'][0])}</b></p>")
        if r.get("dG_withheld"):
            parts.append(f"<p class=warn>ΔG° 不輸出：{_esc(str(r['dG_withheld']))}</p>")
        hs = r.get("half_split") or {}
        if "diff_kj_mol" in hs:
            parts.append(f"<p class=muted>前半／後半段 ΔPMF：{hs['first_half_dpmf']} / {hs['second_half_dpmf']} kJ/mol（差 {hs['diff_kj_mol']}）</p>")
        for k, cap in (("smd", "SMD 拉力與功（不可逆、與速度有關）"), ("histograms", "Window 直方圖（相鄰須重疊）"), ("pmf", "PMF ± bootstrap 誤差")):
            if figs.get(k):
                parts.append(f"<figure>{_img(figs[k]['png'])}<figcaption>{cap}</figcaption></figure>")
        parts.append("<ul>" + "".join(f"<li>{_esc(c)}</li>" for c in r.get("caveats", [])) + "</ul>")
    return "".join(parts)



def _comparison_html(comp: dict) -> str:
    """WP9: ΔΔ ranking per context and co-occupancy shifts."""
    if not comp or not (comp.get("contexts") or comp.get("co_occupancy")):
        return ""
    parts = ["<h3>配體間比較（ΔΔ）</h3>"]
    for ctx, c in comp.get("contexts", {}).items():
        label = "各配體單獨結合" if ctx == "single" else f"共同口袋（{_esc(ctx.split(':', 1)[1])}）"
        if c.get("status") != "PASS":
            parts.append(f"<p class=muted>{label}：{_esc(c.get('why', ''))}</p>")
            continue
        parts.append(f"<p><b>{label}</b> — {_esc(c['why'])}</p><table><tr><th>配體</th><th>{_esc(c['quantity'])} ({_esc(c['unit'])})</th>"
                     "<th>σ</th><th>判定</th></tr>")
        for r in c["rows"]:
            parts.append(f"<tr><td>{_esc(r['key'])}</td><td>{r['delta']:+.2f}</td><td>{'—' if r['sigma'] is None else r['sigma']}</td>"
                         f"<td>{_esc(r['verdict'])}</td></tr>")
        parts.append("</table>")
    if comp.get("co_occupancy"):
        parts.append("<p><b>共存效應</b>（共同口袋 − 單獨結合）</p><ul>"
                     + "".join(f"<li>{_esc(c['why'])}</li>" for c in comp["co_occupancy"]) + "</ul>")
    parts.append("<ul class=muted>" + "".join(f"<li>{_esc(n)}</li>" for n in comp.get("notes", [])) + "</ul>")
    return "".join(parts)


def _viewer_section(wf) -> str:
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
    return "<h2>3D 檢視（離線，可拖曳旋轉；軌跡可播放）</h2>" + "".join(parts)

def build_workflow_report(wf, out_path: Path | None = None) -> Path:
    out_path = Path(out_path) if out_path else wf.dir / "workflow_report.html"
    cfg = wf.cfg
    rows = [r for r in wf.project.decisions.read() if str(r.get("stage", "")).startswith(("workflow", "docking", "binding", "build", "engine", "screen", "gui"))]
    html = [f"<!doctype html><html lang=zh-Hant><head><meta charset=utf-8><title>MD20 Workflow — {_esc(wf.name)}</title><style>{_CSS}</style></head><body>",
            f"<h1>MD20 Workflow 報告：{_esc(wf.name)}</h1>",
            f"<p class=muted>專案 {_esc(wf.project.name)} · 產生於 {now_iso()}</p>",
            "<h2>1. 設定</h2>", f"<details><summary>config.json</summary><pre>{_esc(json.dumps(cfg, ensure_ascii=False, indent=1))}</pre></details>",
            "<h2>2. 分子對接與 pose 選擇</h2>", _structure_section(wf), _screen_section(wf), _docking_section(wf), _cpp_section(wf),
            "<h2>3. 分子動力學（apo vs 對接結合態）</h2>", _md_section(wf),
            "<h2>4. 結合強度（SMD + 傘狀採樣）</h2>", _binding_section(wf),
            _viewer_section(wf),
            "<h2>5. 決策日誌</h2>", _decisions_table(rows), __import__("md20.util.stamp", fromlist=["html_footer"]).html_footer(), "</body></html>"]
    out_path.write_text("".join(html), encoding="utf-8")
    return out_path
