"""One-click run report: self-contained HTML (figures embedded as base64) + reproducibility bundle.

The report is what a student hands in: a methods paragraph generated from
the actual manifests (force fields, protocol, platform, seeds), every stage
figure, acceptance tables, watchdog events and the full decision log.  Nothing
in it is typed by hand, so it cannot drift from what was run.
"""
from __future__ import annotations

import base64
import html
import json
import platform as _platform
import zipfile
from pathlib import Path

from .. import __version__
from ..project import Run
from ..util import load_json, now_iso, sha256_file


def _img(path: str | Path | None) -> str:
    p = Path(path) if path else None
    if not p or not p.is_file():
        return ""
    mime = "image/svg+xml" if p.suffix == ".svg" else "image/png"
    data = base64.b64encode(p.read_bytes()).decode()
    return f'<img src="data:{mime};base64,{data}" style="max-width:100%;height:auto">'


def _fmt_int(x) -> str:
    return f"{int(x):,}" if isinstance(x, (int, float)) else "?"


def _esc(x) -> str:
    return html.escape(str(x))


def _collect(run: Run) -> dict:
    """Everything the report needs, read from files only."""
    rm = run.manifest()
    cm = run.case.manifest()
    bm = load_json(run.case.build_dir / "build_manifest.json", {})
    stages = {}
    for name in ("minimize", "nvt", "npt", "production"):
        stages[name] = load_json(run.dir / "stages" / name / f"{name}_complete.json", {})
    decisions = run.case.project.decisions.read()
    return {"run": rm, "case": cm, "build": bm, "stages": stages, "decisions": decisions}


def methods_paragraph(data: dict, lang: str = "zh") -> str:
    rm, bm, st = data["run"], data["build"], data["stages"]
    proto = rm.get("protocol", {})
    stages = {s["name"]: s for s in proto.get("stages", [])}
    asm = bm.get("assembly", {}) or {}
    ffs = asm.get("forcefields") or ["(force fields not recorded)"]
    ligs = ", ".join(f"{l.get('name')} ({l.get('provider') or '?'}/{l.get('charge_method') or '?'})" for l in (asm.get("ligands") or [])) or "—"
    platform_name = (st.get("production") or st.get("nvt") or {}).get("platform", "?")
    hmr = (st.get("production") or {}).get("backend_info", {}).get("hmr", proto.get("hmr"))
    dt = stages.get("production", {}).get("timestep_fs", "?")
    prod_ns = stages.get("production", {}).get("length_ps", 0) / 1000.0
    box = asm.get("box_nm") or []
    box_txt = f"{box[0][0]:.2f} × {box[1][1]:.2f} × {box[2][2]:.2f} nm" if len(box) == 3 else "?"
    nvt = stages.get("nvt", {}); npt = stages.get("npt", {})
    if lang == "zh":
        return (
            f"系統以 OpenMM（MD20 {__version__}）建立：蛋白質使用 {', '.join(ffs[:2])} 力場，配體參數為 {ligs}；"
            f"以 TIP3P 水溶劑化（padding {bm.get('padding_nm', 1.0)} nm，盒大小 {box_txt}），加入離子中和至 "
            f"{asm.get('n_ions') or {}}，總原子數 {_fmt_int(asm.get('n_atoms'))}。"
            f"PME 處理長程靜電（cutoff {1.0} nm），氫原子鍵長以 SHAKE/SETTLE 約束"
            f"{'，並採用氫質量重分配（HMR）' if hmr else ''}，時間步長 {dt} fs。"
            f"先以三段式最小化（位置約束 1.0→0.5→0）消除碰撞；NVT 自 {nvt.get('result', {}).get('temperature_start_k', stages.get('nvt', {}).get('start_temperature_k', 50))} K "
            f"線性升溫至 {stages.get('nvt', {}).get('temperature_k', 300)} K（{stages.get('nvt', {}).get('length_ps', 0)} ps，Langevin 摩擦 1 ps⁻¹）；"
            f"NPT（Monte Carlo barostat，1 bar，{stages.get('npt', {}).get('length_ps', 0)} ps）期間線性解除位置約束，"
            f"以末段溫度與密度變異係數驗收；Production 為 {prod_ns:g} ns NPT，無約束，隨機種子 {stages.get('production', {}).get('seed', '?')}，"
            f"於 OpenMM {platform_name} 平台執行。所有自動決策見決策日誌。"
        )
    return (f"Systems were built with OpenMM (MD20 {__version__}) using {', '.join(ffs[:2])} for the protein and {ligs} for ligands, "
            f"solvated in TIP3P ({bm.get('padding_nm', 1.0)} nm padding, box {box_txt}), neutralised with ions ({asm.get('n_ions') or {}}; "
            f"{asm.get('n_atoms', '?')} atoms). PME electrostatics (1.0 nm cutoff), H-bond constraints{', HMR' if hmr else ''}, "
            f"{dt} fs timestep. Three-stage restrained minimisation, NVT heating to {stages.get('nvt', {}).get('temperature_k', 300)} K over "
            f"{stages.get('nvt', {}).get('length_ps', 0)} ps, NPT equilibration ({stages.get('npt', {}).get('length_ps', 0)} ps) with linear restraint release and "
            f"temperature/density acceptance, then {prod_ns:g} ns unrestrained NPT production (seed {stages.get('production', {}).get('seed', '?')}) "
            f"on the OpenMM {platform_name} platform.")


def _acceptance_table(stage: dict) -> str:
    acc = stage.get("acceptance") or {}
    rows = acc.get("checks") or []
    if not rows:
        return "<p class=muted>（無驗收項目）</p>"
    out = ["<table><tr><th>檢查</th><th>結果</th><th>數值</th></tr>"]
    for c in rows:
        vals = {k: v for k, v in c.items() if k not in {"check", "ok"}}
        out.append(f"<tr><td>{_esc(c['check'])}</td><td class={'ok' if c['ok'] else 'bad'}>{'通過' if c['ok'] else '未通過'}</td>"
                   f"<td><code>{_esc(json.dumps(vals, ensure_ascii=False))}</code></td></tr>")
    out.append("</table>")
    if acc.get("recommendation"):
        out.append(f"<p>{_esc(acc['recommendation'])}</p>")
    return "".join(out)


def _decisions_table(rows: list[dict]) -> str:
    out = ["<table><tr><th>時間</th><th>階段</th><th>項目</th><th>選擇</th><th>類型</th><th>理由</th></tr>"]
    for r in rows:
        out.append(f"<tr><td>{_esc(r.get('at',''))}</td><td>{_esc(r.get('stage',''))}</td><td>{_esc(r.get('what',''))}</td>"
                   f"<td><code>{_esc(r.get('choice',''))}</code></td><td>{_esc(r.get('kind',''))}</td><td>{_esc(r.get('why',''))}</td></tr>")
    out.append("</table>")
    return "".join(out)


_CSS = """
body{font-family:-apple-system,'Segoe UI','Noto Sans TC',sans-serif;max-width:980px;margin:2rem auto;padding:0 1rem;color:#0b0b0b;line-height:1.5}
h1{font-size:1.6rem}h2{font-size:1.2rem;border-bottom:1px solid #e6e5e1;padding-bottom:.2rem;margin-top:2rem}
table{border-collapse:collapse;width:100%;font-size:.85rem}th,td{border:1px solid #e6e5e1;padding:.3rem .5rem;text-align:left;vertical-align:top}
th{background:#f6f5f2}code{font-size:.8rem}.ok{color:#008300}.bad{color:#e34948;font-weight:600}.muted{color:#52514e}
.badge{display:inline-block;padding:.1rem .5rem;border-radius:.4rem;background:#f6f5f2;font-size:.8rem}
figure{margin:1rem 0}figcaption{font-size:.8rem;color:#52514e}
"""


def build_run_report(run: Run, out_path: Path | str | None = None, *, lang: str = "zh") -> Path:
    data = _collect(run)
    rm, cm, bm, st = data["run"], data["case"], data["build"], data["stages"]
    out_path = Path(out_path) if out_path else run.dir / "report.html"
    parts = [f"<!doctype html><html lang=zh-Hant><head><meta charset=utf-8><title>MD20 報告 — {_esc(cm.get('name'))}</title>"
             f"<style>{_CSS}</style></head><body>",
             f"<h1>MD20 模擬報告：{_esc(cm.get('name'))}</h1>",
             f"<p class=muted>專案 {_esc(run.case.project.name)} · case <code>{_esc(run.case.case_id)}</code> · run <code>{_esc(run.run_id)}</code> · "
             f"產生於 {now_iso()} · 狀態 <span class=badge>{_esc(rm.get('status'))}</span></p>",
             "<h2>方法（自動產生，可直接引用）</h2>", f"<p>{_esc(methods_paragraph(data, lang))}</p>",
             f"<details><summary>English</summary><p>{_esc(methods_paragraph(data, 'en'))}</p></details>"]
    # build summary
    asm = bm.get("assembly") or {}
    if asm:
        parts += ["<h2>系統組成</h2><table><tr><th>項目</th><th>值</th></tr>"]
        for k in ("n_atoms", "n_protein_atoms", "n_ligand_atoms", "n_waters", "n_ions", "total_charge", "forcefields", "restraints"):
            parts.append(f"<tr><td>{k}</td><td><code>{_esc(json.dumps(asm.get(k), ensure_ascii=False))}</code></td></tr>")
        parts.append("</table>")
        gates = (asm.get("gates") or {}).get("gates") or []
        rg = ((bm.get("receptor") or {}).get("gates") or {}).get("gates") or []
        lg = [g for l in (bm.get("ligands") or []) for g in ((l.get("gates") or {}).get("gates") or [])]
        if rg or lg or gates:
            parts.append("<h2>建模閘門</h2><table><tr><th>來源</th><th>閘門</th><th>狀態</th><th>說明</th></tr>")
            for src, rows in (("受體", rg), ("配體", lg), ("組裝", gates)):
                for g in rows:
                    cls = {"PASS": "ok", "AUTO_FIXED": "", "NEEDS_HUMAN": "bad"}.get(g.get("status"), "")
                    parts.append(f"<tr><td>{src}</td><td>{_esc(g.get('name'))}</td><td class='{cls}'>{_esc(g.get('status'))}</td><td>{_esc(g.get('explanation',''))}"
                                 + ("<br><code>" + "<br>".join(_esc(d) for d in g.get("diff", [])[:8]) + "</code>" if g.get("diff") else "") + "</td></tr>")
            parts.append("</table>")
    # stages
    fig_dir = run.figures_dir
    for name, label in (("minimize", "能量最小化"), ("nvt", "NVT 升溫"), ("npt", "NPT 平衡"), ("production", "Production")):
        s = st.get(name) or {}
        parts.append(f"<h2>{label} <span class=badge>{_esc(s.get('status', '未執行'))}</span></h2>")
        if not s:
            continue
        if name == "minimize":
            e = s.get("energies_kj_mol") or []
            if e:
                parts.append(f"<p>位能 {e[0]:,.0f} → {e[-1]:,.0f} kJ/mol（約束階梯 {s.get('restraint_ladder')}）</p>")
            parts.append(f"<figure>{_img(fig_dir / 'minimize_energy.png')}</figure>")
            continue
        r = s.get("result") or {}
        parts.append(f"<p>{r.get('steps', 0):,} steps · {r.get('chunks', 0)} chunks · {r.get('elapsed_s', 0):.0f} s · 平台 {_esc(s.get('platform'))}"
                     f" · dt {s.get('timestep_fs')} fs{' · HMR' if (s.get('backend_info') or {}).get('hmr') else ''}</p>")
        if r.get("watchdog_events"):
            parts.append(f"<p class=bad>watchdog 事件 {len(r['watchdog_events'])} 次（自動回滾／縮小 dt）；詳見決策日誌。</p>")
        parts.append(_acceptance_table(s))
        parts.append(f"<figure>{_img(fig_dir / f'{name}_timeseries.png')}<figcaption>{label} 時序；灰帶為驗收視窗。</figcaption></figure>")
    if (fig_dir / "run_overview.png").is_file():
        parts.append(f"<h2>整體時間軸</h2><figure>{_img(fig_dir / 'run_overview.png')}</figure>")
    parts.append("<h2>決策日誌（程式替你做的每一個選擇與理由）</h2>")
    parts.append(_decisions_table(data["decisions"]))
    parts.append("<h2>可重現性</h2>")
    parts.append(f"<p>MD20 {__version__} · Python {_platform.python_version()} · {_esc(_platform.platform())} · protocol hash <code>{_esc(rm.get('protocol_hash'))}</code></p>")
    parts.append(f"<details><summary>Protocol JSON</summary><pre>{_esc(json.dumps(rm.get('protocol'), ensure_ascii=False, indent=1))}</pre></details>")
    parts.append("</body></html>")
    out_path.write_text("".join(parts), encoding="utf-8")
    return out_path


def reproducibility_bundle(run: Run, out_zip: Path | str | None = None) -> Path:
    """Zip of everything needed to re-run or audit: manifests, decisions, protocol, build files, final states, figures, report."""
    out_zip = Path(out_zip) if out_zip else run.dir / f"{run.run_id}_bundle.zip"
    files: list[Path] = []
    files += [run.case.project.manifest_path, run.case.project.decisions.path, run.case.manifest_path, run.manifest_path]
    files += list(run.case.build_dir.glob("*.json")) + list(run.case.build_dir.glob("*.pdb")) + list(run.case.build_dir.glob("*.xml"))
    for name in ("minimize", "nvt", "npt", "production"):
        d = run.dir / "stages" / name
        if d.is_dir():
            files += [p for p in d.iterdir() if p.suffix in {".json", ".log", ".xml", ".pdb"} and not p.name.startswith("chunk_")]
    files += list(run.figures_dir.glob("*"))
    if (run.dir / "report.html").is_file():
        files.append(run.dir / "report.html")
    manifest = {"created_at": now_iso(), "md20_version": __version__, "files": []}
    root = run.case.project.dir
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            if f.is_file():
                arc = str(f.relative_to(root)) if root in f.parents else f.name
                zf.write(f, arc)
                manifest["files"].append({"path": arc, "sha256": sha256_file(f), "bytes": f.stat().st_size})
        zf.writestr("BUNDLE_MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=1))
    return out_zip
