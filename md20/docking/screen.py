"""High-throughput pre-screen: dock every usable library compound independently, rank, plot, hand the choice back.

Spec: docs/specs/hts_screen.md §2–3.  This is a *pre-filter inside the docking step*, not a new phase: each
compound goes through the same `dock(mode="independent")` as the final docking, only with a reduced search
(exhaustiveness 8, 3 poses).  The screen can only *exclude* compounds; it never proves binding.

Resumable: screen_results.json is rewritten atomically after every compound; a re-run docks only what is
missing.  One failing compound is recorded as FAILED and the loop continues.
"""
from __future__ import annotations

import csv
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..util import atomic_write_json, load_json, now_iso, DecisionLog
from .box import Box
from ..i18n import pick as tx, colon

INDISTINGUISHABLE_KCAL = 1.0       # Vina's own error is ~1–2 kcal/mol; within this of the top, order is noise
LE_REFERENCE = 0.3                 # kcal/mol per heavy atom — common "good ligand efficiency" guide line


@dataclass
class ScreenConfig:
    exhaustiveness: int = 8
    n_poses: int = 3
    scoring: str = "vina"
    seed: int = 2026
    cpu: int = 0
    top_n: int = 20
    allow_partial: bool = False
    allow_name_lookup: bool = False
    workers: int = 4                # download threads
    library: str = ""
    sheet: str | int | None = None
    protonation: str = "auto"       # pH-7.4 major ionisation state for every compound (docking/ionize.py) | "as_given"
    ph: float = 7.4

    @classmethod
    def from_cfg(cls, d: dict | None) -> "ScreenConfig":
        d = d or {}
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def params(self) -> dict:
        return {"exhaustiveness": self.exhaustiveness, "n_poses": self.n_poses, "scoring": self.scoring, "seed": self.seed,
                "reduced_search": True, "protonation": self.protonation, "ph": self.ph,
                "note": "篩選用縮減搜尋，exhaustiveness 低、pose 少。分數只用來剔除化合物，不是結合自由能。"
                        "配體以該 pH 下的主要離子態對接，PubChem 或 ChEMBL 給的中性結構會先離子化，與受體加氫一致。"}


# ----------------------------------------------------------------------------- batch docking
def screen_dock(receptor_pdb: Path | str, entries: list[dict], box: Box, out_dir: Path | str, cfg: ScreenConfig, *,
                decisions: DecisionLog | None = None, progress_cb=None, dock_fn=None, should_stop=None) -> dict:
    """entries: usable library records ({name, path, smiles, heavy_atoms, …}).  Returns the results dict."""
    from .run import dock, LigandInput
    from .receptor_pdbqt import receptor_to_pdbqt
    dock_fn = dock_fn or dock
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    rpath = out / "screen_results.json"
    results = load_json(rpath, {"entries": {}})
    results.setdefault("entries", {})
    results.update({"box": box.to_dict(), "params": cfg.params(), "receptor": str(receptor_pdb)})
    rec_pdbqt = out / "receptor.pdbqt"
    if not rec_pdbqt.is_file():
        receptor_to_pdbqt(Path(receptor_pdb), rec_pdbqt)
    todo = [e for e in entries if results["entries"].get(e["name"], {}).get("status") != "OK"]
    if decisions and todo:
        decisions.record("screen.docking", "setup", cfg.params(),
                         f"高通量篩選 {len(entries)} 個化合物，已完成 {len(entries) - len(todo)} 個，續跑 {len(todo)} 個。每個化合物各自對接，"
                         f"exhaustiveness {cfg.exhaustiveness}、{cfg.n_poses} 個 pose。分數接近的視為不可區分，之後正式對接才用完整搜尋。")
    t0, done_now = time.monotonic(), 0
    for i, e in enumerate(todo, 1):
        if should_stop and should_stop():
            results["paused"] = True
            atomic_write_json(results, rpath)
            return results
        name = e["name"]
        rec: dict = {"heavy_atoms": e.get("heavy_atoms"), "mw": e.get("mw"), "smiles": e.get("smiles", ""),
                     "library_path": e.get("path", ""), "at": now_iso()}
        t1 = time.monotonic()
        try:
            lig = LigandInput(name=name, sdf=e.get("path", ""), smiles="" if e.get("path") else e.get("smiles", ""),
                              protonation=getattr(cfg, "protonation", "auto"), ph=float(getattr(cfg, "ph", 7.4)))
            r = dock_fn(receptor_pdb, [lig], box, out / "poses" / name, mode="independent", scoring=cfg.scoring,
                        exhaustiveness=cfg.exhaustiveness, n_poses=cfg.n_poses, seed=cfg.seed, cpu=cfg.cpu,
                        receptor_pdbqt=rec_pdbqt)
            ent = r.entries[0]
            best = min(ent["poses"], key=lambda p: p["score"])
            rec.update({"status": "OK", "score": float(best["score"]), "best_rank": int(best["rank"]),
                        "cluster_size": int(best.get("cluster_size", 1)), "contacts": int(best.get("contacts", 0)),
                        "recommended_rank": ent.get("recommended_rank"), "recommendation_status": ent.get("recommendation_status"),
                        "reason": ent.get("reason", ""), "n_poses": len(ent["poses"]),
                        "result": str(out / "poses" / name / "docking_results.json"),
                        "sdf": (ent.get("pose_sdfs") or {}).get(name, [None])[0]})
            if not rec["smiles"]:
                rec["smiles"] = ent.get("smiles", "")
            if rec["heavy_atoms"] is None and rec["smiles"]:
                rec["heavy_atoms"] = _heavy_from_smiles(rec["smiles"])
        except Exception as exc:  # noqa: BLE001  — one bad compound must not kill a 500-compound screen
            rec.update({"status": "FAILED", "error": f"{type(exc).__name__}: {exc}"})
        rec["seconds"] = round(time.monotonic() - t1, 1)
        results["entries"][name] = rec
        results["updated_at"] = now_iso()
        atomic_write_json(results, rpath)
        done_now += 1
        if progress_cb:
            avg = (time.monotonic() - t0) / done_now
            progress_cb({"stage": "screen_docking", "ligand": name, "i": len(entries) - len(todo) + i, "n": len(entries),
                         "status": rec["status"], "avg_s": round(avg, 1), "eta_s": round(avg * (len(todo) - i))})
    results["order"] = [e["name"] for e in entries]
    results.pop("paused", None)
    atomic_write_json(results, rpath)
    return results


def _heavy_from_smiles(smiles: str) -> int | None:
    try:
        from rdkit import Chem
        m = Chem.MolFromSmiles(smiles)
        return int(m.GetNumHeavyAtoms()) if m is not None else None
    except ImportError:
        return None


# ----------------------------------------------------------------------------- ranking
def rank_screen(results: dict, *, top_n: int = 20, indistinguishable_kcal: float = INDISTINGUISHABLE_KCAL) -> list[dict]:
    """Rows sorted by score (best first) with ligand efficiency, rank, and the honesty flags."""
    rows = []
    for name, r in results.get("entries", {}).items():
        if r.get("status") != "OK" or r.get("score") is None:
            continue
        heavy = r.get("heavy_atoms")
        le = round(-float(r["score"]) / heavy, 3) if heavy else None
        rows.append({"name": name, "score": round(float(r["score"]), 2), "heavy_atoms": heavy, "ligand_efficiency": le,
                     "cluster_size": r.get("cluster_size", 1), "contacts": r.get("contacts", 0),
                     "recommendation_status": r.get("recommendation_status") or "NEEDS_HUMAN", "reason": r.get("reason", ""),
                     "smiles": r.get("smiles", ""), "sdf": r.get("sdf"), "seconds": r.get("seconds")})
    rows.sort(key=lambda x: (x["score"], -(x["cluster_size"] or 0)))
    if rows:
        best = rows[0]["score"]
        for i, x in enumerate(rows, 1):
            x["rank"] = i
            x["delta_to_best"] = round(x["score"] - best, 2)
            x["indistinguishable_from_top"] = (x["score"] - best) < indistinguishable_kcal
            x["in_top_n"] = i <= top_n
    return rows


def write_ranking_csv(rows: list[dict], path: Path | str) -> Path:
    cols = ["rank", "name", "score", "delta_to_best", "indistinguishable_from_top", "heavy_atoms", "ligand_efficiency",
            "cluster_size", "contacts", "recommendation_status", "smiles", "reason"]
    p = Path(path)
    with open(p, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for r in rows:
            w.writerow([r.get(c, "") for c in cols])
    return p


def failed_rows(results: dict, manifest: dict | None = None) -> list[dict]:
    """Compounds that did not reach a score: library FAILED/SKIPPED + docking FAILED, with reasons."""
    out = []
    if manifest:
        for n in manifest.get("order") or list(manifest.get("entries", {})):
            r = manifest["entries"].get(n) or {}
            if r.get("status") != "OK":
                out.append({"name": n, "stage": "library", "status": r.get("status", "FAILED"), "error": r.get("error", "")})
    for n, r in results.get("entries", {}).items():
        if r.get("status") != "OK":
            out.append({"name": n, "stage": "docking", "status": "FAILED", "error": r.get("error", "")})
    return out


# ----------------------------------------------------------------------------- plots
def screen_plots(rows: list[dict], out_dir: Path | str, *, top_n: int = 20) -> dict:
    """Score histogram, score vs heavy atoms (LE guide), top-N bar.  PNG + SVG via analysis.plots conventions."""
    from ..analysis.plots import _mpl, _save, PALETTE, _INK2
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    plt = _mpl()
    paths: dict = {}
    if not rows:
        return paths
    scores = np.array([r["score"] for r in rows], float)
    # 1. distribution
    fig, ax = plt.subplots(figsize=(5.2, 3.2))
    bins = max(8, min(40, int(np.sqrt(len(scores)) * 2)))
    ax.hist(scores, bins=bins, color=PALETTE[0], alpha=0.85, edgecolor="white")
    ax.axvline(scores.min() + INDISTINGUISHABLE_KCAL, color=PALETTE[1], lw=1.2, ls="--")
    ax.text(scores.min() + INDISTINGUISHABLE_KCAL, ax.get_ylim()[1] * 0.95, f" 最佳 +{INDISTINGUISHABLE_KCAL:g} kcal/mol（誤差內）",
            color=PALETTE[1], fontsize=7, va="top")
    ax.set_xlabel("Vina score (kcal/mol, reduced search)"); ax.set_ylabel("compounds")
    ax.set_title(f"Screen score distribution (n={len(scores)})", fontsize=9)
    paths["histogram"] = _save(fig, out / "screen_hist")
    # 2. score vs size
    hv = np.array([r["heavy_atoms"] or np.nan for r in rows], float)
    fig, ax = plt.subplots(figsize=(5.2, 3.6))
    status_color = {"PASS": PALETTE[2], "AUTO_FIXED": PALETTE[3], "NEEDS_HUMAN": PALETTE[7]}
    for st, col in status_color.items():
        m = np.array([r["recommendation_status"] == st for r in rows])
        if m.any():
            ax.scatter(hv[m], scores[m], s=16, color=col, alpha=0.8, label=f"{st} ({int(m.sum())})", edgecolor="none")
    if np.isfinite(hv).any():
        x = np.linspace(np.nanmin(hv), np.nanmax(hv), 50)
        ax.plot(x, -LE_REFERENCE * x, color=_INK2, lw=1, ls=":", label=f"LE = {LE_REFERENCE} kcal/mol/heavy atom")
    for r in rows[:min(5, len(rows))]:
        if r["heavy_atoms"]:
            ax.annotate(r["name"], (r["heavy_atoms"], r["score"]), fontsize=6, xytext=(3, 3), textcoords="offset points")
    ax.set_xlabel("heavy atoms"); ax.set_ylabel("Vina score (kcal/mol)")
    ax.set_title("Score vs size — bigger molecules score better by construction", fontsize=9)
    ax.legend(fontsize=6, frameon=False)
    paths["scatter"] = _save(fig, out / "screen_score_vs_size")
    # 3. top N
    top = rows[:top_n]
    fig, ax = plt.subplots(figsize=(5.2, max(2.4, 0.22 * len(top) + 1.0)))
    y = np.arange(len(top))
    cols = [status_color.get(r["recommendation_status"], PALETTE[7]) for r in top]
    ax.barh(y, [-r["score"] for r in top], color=cols, alpha=0.9)
    ax.set_yticks(y); ax.set_yticklabels([r["name"] for r in top], fontsize=6); ax.invert_yaxis()
    ax.axvline(-(top[0]["score"] + INDISTINGUISHABLE_KCAL), color=PALETTE[1], lw=1, ls="--")
    ax.set_xlabel("−score (kcal/mol); dashed = within Vina error of the best")
    ax.set_title(f"Top {len(top)} (colour = pose recommendation status)", fontsize=9)
    paths["top"] = _save(fig, out / "screen_top")
    return paths


STATUS_COLORS = {"PASS": "#2f7d5b", "AUTO_FIXED": "#c08a1e", "NEEDS_HUMAN": "#b8433f"}


def echart_ranking(rows: list[dict], *, top_n: int = 30, lang: str = "en") -> dict:
    """Ranked horizontal bar chart (best score at the top), coloured by recommendation; the band marks compounds within
    1 kcal/mol of the best (inside Vina's error).  Each bar's name is the compound name, so a click selects it."""
    rs = sorted([r for r in rows if r.get("score") is not None], key=lambda r: r["score"])[:top_n]
    rs = list(reversed(rs))                      # ECharts category axes draw bottom-up
    best = min((r["score"] for r in rs), default=0.0)
    data = [{"value": r["score"], "name": r["name"],
             "itemStyle": {"color": STATUS_COLORS.get(r.get("recommendation_status"), "#7b8794")}} for r in rs]
    return {
        "title": {"text": tx(("篩選排名（Vina 分數，越負越好）", "Screening ranking (Vina score, more negative is better)",
                              "スクリーニング順位（Vina スコア、負に大きいほど良い）", "스크리닝 순위(Vina 점수, 더 음수일수록 좋음)"), lang),
                  "subtext": tx(("灰色帶是與最佳差距 1 kcal/mol 以內的範圍，這些名次在誤差內。點一下長條可以選取化合物。",
                                 "The grey band is within 1 kcal/mol of the best, where the order is within error. Click a bar "
                                 "to select the compound.",
                                 "灰色の帯は最良値から 1 kcal/mol 以内の範囲で、この中の順位は誤差内です。棒をクリックすると化合物を"
                                 "選べます。",
                                 "회색 띠는 최고값에서 1 kcal/mol 이내 범위로, 이 안의 순위는 오차 범위입니다. 막대를 누르면 화합물을 "
                                 "선택할 수 있습니다."), lang),
                  "textStyle": {"fontSize": 13, "fontWeight": 600}, "subtextStyle": {"fontSize": 11}},
        "grid": {"left": 120, "right": 40, "top": 60, "bottom": 30},
        "tooltip": {"trigger": "item", "formatter": "{b}: {c} kcal/mol"},
        "xAxis": {"type": "value", "name": "kcal/mol", "inverse": True},
        "yAxis": {"type": "category", "data": [r["name"] for r in rs], "axisLabel": {"fontSize": 11}},
        "series": [{"type": "bar", "data": data, "barMaxWidth": 14,
                    "markArea": {"silent": True, "itemStyle": {"color": "rgba(123,135,148,0.12)"},
                                 "data": [[{"xAxis": best}, {"xAxis": best + 1.0}]]} if rs else {}}],
    }


def echart_screen(rows: list[dict], top_n: int = 20, lang: str = "en") -> dict:
    """ECharts option for the GUI: score vs heavy atoms, one series per recommendation status."""
    series = []
    for st, col in (("PASS", "#1baf7a"), ("AUTO_FIXED", "#eda100"), ("NEEDS_HUMAN", "#e34948")):
        pts = [[r["heavy_atoms"], r["score"], r["name"], r["ligand_efficiency"]] for r in rows if r["recommendation_status"] == st]
        if pts:
            series.append({"name": st, "type": "scatter", "symbolSize": 7, "itemStyle": {"color": col}, "data": pts})
    sep, comma = colon(lang), tx(("，", ", ", "、", ", "), lang)
    return {"title": {"text": tx(("篩選分數與重原子數。分數越低越好，相差 1 kcal/mol 以內視為同級",
                                  "Screen score against heavy atoms. Lower is better; scores within 1 kcal/mol count as equal",
                                  "スクリーニングのスコアと重原子数。低いほど良く、1 kcal/mol 以内の差は同等とみなします",
                                  "스크리닝 점수와 중원자 수. 낮을수록 좋으며 1 kcal/mol 이내 차이는 같은 수준으로 봅니다"), lang),
                      "textStyle": {"fontSize": 12}},
            "tooltip": {"trigger": "item", "formatter": "{b}"},
            "legend": {"bottom": 0},
            "xAxis": {"name": tx(("重原子數", "Heavy atoms", "重原子数", "중원자 수"), lang), "type": "value"},
            "yAxis": {"name": "Vina score (kcal/mol)", "type": "value", "inverse": True},
            "series": [{**s, "data": [{"value": d[:2], "name": f"{d[2]}{sep}{d[1]} kcal/mol{comma}LE {d[3]}"} for d in s["data"]]} for s in series]}
