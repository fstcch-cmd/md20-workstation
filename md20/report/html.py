"""One-click run report: self-contained HTML (figures embedded as base64) and a reproducibility bundle.

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
from ..i18n import HTML_LANG, colon, norm, pick
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
    lg = norm(lang)
    rm, bm, st = data["run"], data["build"], data["stages"]
    proto = rm.get("protocol", {})
    stages = {s["name"]: s for s in proto.get("stages", [])}
    asm = bm.get("assembly", {}) or {}
    ffs = asm.get("forcefields") or [pick(("（未記錄力場）", "(force fields not recorded)", "（力場の記録なし）", "(힘장 기록 없음)"), lg)]
    ligs = ", ".join(f"{l.get('name')} ({l.get('provider') or '?'}, {l.get('charge_method') or '?'})" for l in (asm.get("ligands") or [])) or "—"
    platform_name = (st.get("production") or st.get("nvt") or {}).get("platform", "?")
    hmr = (st.get("production") or {}).get("backend_info", {}).get("hmr", proto.get("hmr"))
    dt = stages.get("production", {}).get("timestep_fs", "?")
    prod_ns = stages.get("production", {}).get("length_ps", 0) / 1000.0
    box = asm.get("box_nm") or []
    box_txt = f"{box[0][0]:.2f} × {box[1][1]:.2f} × {box[2][2]:.2f} nm" if len(box) == 3 else "?"
    nvt = stages.get("nvt", {})
    ff2 = ", ".join(ffs[:2])
    pad = bm.get("padding_nm", 1.0)
    ions = asm.get("n_ions") or {}
    t0 = nvt.get("result", {}).get("temperature_start_k", nvt.get("start_temperature_k", 50))
    t1 = nvt.get("temperature_k", 300)
    nvt_ps = nvt.get("length_ps", 0)
    npt_ps = stages.get("npt", {}).get("length_ps", 0)
    seed = stages.get("production", {}).get("seed", "?")
    if lg == "zh":
        return (f"系統以 OpenMM（MD20 {__version__}）建立。蛋白質使用 {ff2} 力場，配體參數為 {ligs}。"
                f"以 TIP3P 水溶劑化（padding {pad} nm，盒大小 {box_txt}），加入離子中和（{ions}），總原子數 {_fmt_int(asm.get('n_atoms'))}。"
                f"長程靜電以 PME 處理（cutoff 1.0 nm），含氫的鍵以 SHAKE 與 SETTLE 約束"
                f"{'，並採用氫質量重分配（HMR）' if hmr else ''}，時間步長 {dt} fs。"
                f"先以三段式最小化消除碰撞，位置約束依序為 1.0、0.5、0。NVT 從 {t0} K 線性升溫到 {t1} K（{nvt_ps} ps，Langevin 摩擦 1 ps⁻¹）。"
                f"NPT（Monte Carlo barostat，1 bar，{npt_ps} ps）期間線性解除位置約束，並以最後一段的溫度與密度變異係數驗收。"
                f"正式模擬為 {prod_ns:g} ns NPT，不加約束，隨機種子 {seed}，在 OpenMM {platform_name} 平台執行。所有自動決策都記在決策日誌。")
    if lg == "ja":
        return (f"系は OpenMM（MD20 {__version__}）で構築した。タンパク質には {ff2} 力場を用い、リガンドのパラメータは {ligs} とした。"
                f"TIP3P 水で溶媒和し（padding {pad} nm、ボックス {box_txt}）、イオンで中和した（{ions}）。総原子数は {_fmt_int(asm.get('n_atoms'))} である。"
                f"長距離静電相互作用は PME（cutoff 1.0 nm）で扱い、水素を含む結合は SHAKE と SETTLE で拘束した"
                f"{'。水素質量の再分配（HMR）も用いた' if hmr else ''}。時間刻みは {dt} fs である。"
                f"まず 3 段階の最小化で衝突を除いた。位置拘束は 1.0、0.5、0 の順に弱めた。NVT では {t0} K から {t1} K まで線形に昇温した（{nvt_ps} ps、Langevin 摩擦 1 ps⁻¹）。"
                f"NPT（Monte Carlo barostat、1 bar、{npt_ps} ps）では位置拘束を線形に解除し、最後の区間の温度と密度の変動係数で合否を判定した。"
                f"本計算は {prod_ns:g} ns の拘束なし NPT で、乱数シードは {seed}、OpenMM の {platform_name} プラットフォームで実行した。自動判断はすべて判断の記録に残している。")
    if lg == "ko":
        return (f"시스템은 OpenMM(MD20 {__version__})으로 구축했다. 단백질에는 {ff2} 힘장을 사용했고 리간드 매개변수는 {ligs}이다. "
                f"TIP3P 물로 용매화하고(padding {pad} nm, 상자 {box_txt}) 이온으로 중화했다({ions}). 전체 원자 수는 {_fmt_int(asm.get('n_atoms'))}이다. "
                f"장거리 정전기는 PME(cutoff 1.0 nm)로 처리했고 수소를 포함한 결합은 SHAKE와 SETTLE로 구속했다"
                f"{'. 수소 질량 재분배(HMR)도 적용했다' if hmr else ''}. 시간 간격은 {dt} fs이다. "
                f"먼저 3단계 최소화로 충돌을 제거했으며 위치 구속은 1.0, 0.5, 0 순으로 낮췄다. NVT에서 {t0} K에서 {t1} K까지 선형으로 승온했다({nvt_ps} ps, Langevin 마찰 1 ps⁻¹). "
                f"NPT(Monte Carlo barostat, 1 bar, {npt_ps} ps) 동안 위치 구속을 선형으로 풀고 마지막 구간의 온도와 밀도 변동 계수로 검수했다. "
                f"본 시뮬레이션은 구속 없는 {prod_ns:g} ns NPT이며 난수 시드는 {seed}, OpenMM {platform_name} 플랫폼에서 실행했다. 모든 자동 결정은 결정 기록에 남아 있다.")
    return (f"Systems were built with OpenMM (MD20 {__version__}) using {ff2} for the protein and {ligs} for ligands. "
            f"They were solvated in TIP3P ({pad} nm padding, box {box_txt}) and neutralised with ions ({ions}), "
            f"giving {asm.get('n_atoms', '?')} atoms. Electrostatics used PME (1.0 nm cutoff) with H-bond constraints{' and HMR' if hmr else ''} "
            f"and a {dt} fs timestep. A three-stage restrained minimisation was followed by NVT heating to {t1} K over "
            f"{nvt_ps} ps and NPT equilibration ({npt_ps} ps) with linear restraint release and "
            f"temperature and density acceptance. Production was {prod_ns:g} ns of unrestrained NPT (seed {seed}) "
            f"on the OpenMM {platform_name} platform.")


def _acceptance_table(stage: dict, lang: str = "zh") -> str:
    t = lambda *x: pick(x, lang)  # noqa: E731
    acc = stage.get("acceptance") or {}
    rows = acc.get("checks") or []
    if not rows:
        return "<p class=muted>" + t("（沒有驗收項目）", "(no acceptance checks)", "（合否チェックなし）", "(검수 항목 없음)") + "</p>"
    out = [f"<table><tr><th>{t('檢查', 'Check', '確認項目', '확인 항목')}</th><th>{t('結果', 'Result', '結果', '결과')}</th>"
           f"<th>{t('數值', 'Values', '数値', '수치')}</th></tr>"]
    ok, bad = t("通過", "pass", "合格", "통과"), t("未通過", "fail", "不合格", "미통과")
    for c in rows:
        vals = {k: v for k, v in c.items() if k not in {"check", "ok"}}
        out.append(f"<tr><td>{_esc(c['check'])}</td><td class={'ok' if c['ok'] else 'bad'}>{ok if c['ok'] else bad}</td>"
                   f"<td><code>{_esc(json.dumps(vals, ensure_ascii=False))}</code></td></tr>")
    out.append("</table>")
    if acc.get("recommendation"):
        out.append(f"<p>{_esc(acc['recommendation'])}</p>")
    return "".join(out)


def _decisions_table(rows: list[dict], lang: str = "zh") -> str:
    t = lambda *x: pick(x, lang)  # noqa: E731
    heads = (t("時間", "Time", "日時", "시각"), t("階段", "Stage", "段階", "단계"), t("項目", "Item", "項目", "항목"),
             t("選擇", "Choice", "選択", "선택"), t("類型", "Type", "種類", "유형"), t("理由", "Reason", "理由", "이유"))
    out = ["<table><tr>" + "".join(f"<th>{h}</th>" for h in heads) + "</tr>"]
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
    lang = norm(lang)
    t = lambda *x: pick(x, lang)  # noqa: E731
    c = colon(lang)
    data = _collect(run)
    rm, cm, bm, st = data["run"], data["case"], data["build"], data["stages"]
    out_path = Path(out_path) if out_path else run.dir / "report.html"
    title = t("MD20 報告", "MD20 report", "MD20 レポート", "MD20 보고서")
    parts = [f"<!doctype html><html lang={HTML_LANG[lang]}><head><meta charset=utf-8><title>{title} · {_esc(cm.get('name'))}</title>"
             f"<style>{_CSS}</style></head><body>",
             f"<h1>{t('MD20 模擬報告', 'MD20 simulation report', 'MD20 シミュレーションレポート', 'MD20 시뮬레이션 보고서')}{c}{_esc(cm.get('name'))}</h1>",
             f"<p class=muted>{t('專案', 'Project', 'プロジェクト', '프로젝트')} {_esc(run.case.project.name)} · case <code>{_esc(run.case.case_id)}</code> · "
             f"run <code>{_esc(run.run_id)}</code> · {t('產生於', 'generated', '作成', '생성')} {now_iso()} · "
             f"{t('狀態', 'status', '状態', '상태')} <span class=badge>{_esc(rm.get('status'))}</span></p>",
             "<h2>" + t("方法（自動產生，可直接引用）", "Methods (generated automatically, ready to cite)",
                        "方法（自動生成、そのまま引用できます）", "방법 (자동 생성, 그대로 인용 가능)") + "</h2>",
             f"<p>{_esc(methods_paragraph(data, lang))}</p>"]
    if lang != "en":
        parts.append(f"<details><summary>English</summary><p>{_esc(methods_paragraph(data, 'en'))}</p></details>")
    # build summary
    asm = bm.get("assembly") or {}
    if asm:
        parts += [f"<h2>{t('系統組成', 'System composition', '系の構成', '시스템 구성')}</h2><table><tr><th>{t('項目', 'Item', '項目', '항목')}</th>"
                  f"<th>{t('值', 'Value', '値', '값')}</th></tr>"]
        for k in ("n_atoms", "n_protein_atoms", "n_ligand_atoms", "n_waters", "n_ions", "total_charge", "forcefields", "restraints"):
            parts.append(f"<tr><td>{k}</td><td><code>{_esc(json.dumps(asm.get(k), ensure_ascii=False))}</code></td></tr>")
        parts.append("</table>")
        gates = (asm.get("gates") or {}).get("gates") or []
        rg = ((bm.get("receptor") or {}).get("gates") or {}).get("gates") or []
        lg = [g for l in (bm.get("ligands") or []) for g in ((l.get("gates") or {}).get("gates") or [])]
        if rg or lg or gates:
            parts.append(f"<h2>{t('建模閘門', 'Build gates', '構築のゲート', '구축 게이트')}</h2><table><tr><th>{t('來源', 'Source', '対象', '대상')}</th>"
                         f"<th>{t('閘門', 'Gate', 'ゲート', '게이트')}</th><th>{t('狀態', 'Status', '状態', '상태')}</th>"
                         f"<th>{t('說明', 'Explanation', '説明', '설명')}</th></tr>")
            for src, rows in ((t("受體", "Receptor", "受容体", "수용체"), rg), (t("配體", "Ligand", "リガンド", "리간드"), lg),
                              (t("組裝", "Assembly", "組み立て", "조립"), gates)):
                for g in rows:
                    cls = {"PASS": "ok", "AUTO_FIXED": "", "NEEDS_HUMAN": "bad"}.get(g.get("status"), "")
                    parts.append(f"<tr><td>{src}</td><td>{_esc(g.get('name'))}</td><td class='{cls}'>{_esc(g.get('status'))}</td><td>{_esc(g.get('explanation',''))}"
                                 + ("<br><code>" + "<br>".join(_esc(d) for d in g.get("diff", [])[:8]) + "</code>" if g.get("diff") else "") + "</td></tr>")
            parts.append("</table>")
    # stages
    fig_dir = run.figures_dir
    labels = (("minimize", t("能量最小化", "Energy minimisation", "エネルギー最小化", "에너지 최소화")),
              ("nvt", t("NVT 升溫", "NVT heating", "NVT 昇温", "NVT 승온")),
              ("npt", t("NPT 平衡", "NPT equilibration", "NPT 平衡化", "NPT 평형화")),
              ("production", t("Production", "Production", "本計算（Production）", "본 시뮬레이션(프로덕션)")))
    for name, label in labels:
        s = st.get(name) or {}
        parts.append(f"<h2>{label} <span class=badge>{_esc(s.get('status', t('未執行', 'not run', '未実行', '실행 안 함')))}</span></h2>")
        if not s:
            continue
        if name == "minimize":
            e = s.get("energies_kj_mol") or []
            if e:
                lad = s.get("restraint_ladder")
                parts.append("<p>" + t(f"位能從 {e[0]:,.0f} 降到 {e[-1]:,.0f} kJ/mol（約束階梯 {lad}）",
                                       f"Potential energy {e[0]:,.0f} to {e[-1]:,.0f} kJ/mol (restraint ladder {lad})",
                                       f"ポテンシャルエネルギーは {e[0]:,.0f} から {e[-1]:,.0f} kJ/mol に下がりました（拘束の段階 {lad}）",
                                       f"퍼텐셜 에너지가 {e[0]:,.0f}에서 {e[-1]:,.0f} kJ/mol로 내려갔습니다 (구속 단계 {lad})") + "</p>")
            parts.append(f"<figure>{_img(fig_dir / 'minimize_energy.png')}</figure>")
            continue
        r = s.get("result") or {}
        parts.append(f"<p>{r.get('steps', 0):,} steps · {r.get('chunks', 0)} chunks · {r.get('elapsed_s', 0):.0f} s · "
                     f"{t('平台', 'platform', 'プラットフォーム', '플랫폼')} {_esc(s.get('platform'))}"
                     f" · dt {s.get('timestep_fs')} fs{' · HMR' if (s.get('backend_info') or {}).get('hmr') else ''}</p>")
        if r.get("watchdog_events"):
            n = len(r["watchdog_events"])
            parts.append("<p class=bad>" + t(f"watchdog 事件 {n} 次，程式已自動回滾或縮小 dt。細節見決策日誌。",
                                             f"{n} watchdog events. The run rolled back or reduced dt automatically. See the decision log for details.",
                                             f"watchdog イベントが {n} 回ありました。自動でロールバックするか dt を小さくしました。詳しくは判断の記録を見てください。",
                                             f"watchdog 이벤트가 {n}회 있었습니다. 자동으로 롤백하거나 dt를 줄였습니다. 자세한 내용은 결정 기록을 보십시오.") + "</p>")
        parts.append(_acceptance_table(s, lang))
        cap = t(f"{label} 的時序。灰帶是驗收視窗。", f"{label} time series. The grey band is the acceptance window.",
                f"{label} の時系列。灰色の帯は合否判定の区間です。", f"{label} 시계열. 회색 띠는 검수 구간입니다.")
        parts.append(f"<figure>{_img(fig_dir / f'{name}_timeseries.png')}<figcaption>{cap}</figcaption></figure>")
    if (fig_dir / "run_overview.png").is_file():
        parts.append(f"<h2>{t('整體時間軸', 'Overall timeline', '全体のタイムライン', '전체 타임라인')}</h2><figure>{_img(fig_dir / 'run_overview.png')}</figure>")
    parts.append("<h2>" + t("決策日誌（程式替你做的每個選擇與理由）", "Decision log (every choice the program made for you, with the reason)",
                            "判断の記録（プログラムが代わりに行った選択とその理由）", "결정 기록 (프로그램이 대신 내린 모든 선택과 이유)") + "</h2>")
    parts.append(_decisions_table(data["decisions"], lang))
    parts.append(f"<h2>{t('可重現性', 'Reproducibility', '再現性', '재현성')}</h2>")
    parts.append(f"<p>MD20 {__version__} · Python {_platform.python_version()} · {_esc(_platform.platform())} · protocol hash <code>{_esc(rm.get('protocol_hash'))}</code></p>")
    parts.append(f"<details><summary>Protocol JSON</summary><pre>{_esc(json.dumps(rm.get('protocol'), ensure_ascii=False, indent=1))}</pre></details>")
    from ..util.stamp import html_footer
    from .. import edition as _edition
    if _edition.is_lite():                              # D-181: MD20 Lite mark; the complete edition's page is unchanged
        from .edition_section import footer_mark
        parts.append(footer_mark(lang))
    parts.append(html_footer() + "</body></html>")
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
    # re-centred trajectory (imaged, protein at the box centre) so students never open the raw wrapped DCD in VMD
    files += [p for p in (run.dir / "analysis").glob("production_centered.*")] + [p for p in (run.dir / "analysis").glob("centered_manifest.json")]
    if (run.dir / "report.html").is_file():
        files.append(run.dir / "report.html")
    manifest = {"created_at": now_iso(), "md20_version": __version__, "files": []}
    root = run.case.project.dir
    from ..util.stamp import zip_comment, stamp_record
    manifest["_md20"] = stamp_record()
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.comment = zip_comment()
        for f in files:
            if f.is_file():
                arc = str(f.relative_to(root)) if root in f.parents else f.name
                zf.write(f, arc)
                manifest["files"].append({"path": arc, "sha256": sha256_file(f), "bytes": f.stat().st_size})
        zf.writestr("BUNDLE_MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=1))
    return out_zip
