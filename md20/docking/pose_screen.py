"""WP5 — short-MD screen of docking poses before the pose is fixed for production.

Pure logic only (testable without OpenMM): which ranks to screen, how to judge one short trajectory,
and how to turn the screen into a three-state decision.  The workflow supplies the simulation
(build each candidate pose → short restrained-then-free MD → `compute_metrics`).

Why: a Vina score has ~1–2 kcal/mol error and no solvent/flexibility; a pose that leaves the pocket
within ~100 ps of unrestrained MD is not a credible starting point for a 10–100 ns production or PMF.
The screen does not *rank by* short-MD stability (too short to be thermodynamic) — it only removes
poses that fall apart, and it never silently picks a pose the docking rules had rejected.

Decision (written to DecisionLog with a Chinese `why`):
  recommended pose stable                     → PASS, keep it
  recommended unstable, another candidate stable → AUTO_FIXED, switch to the most stable one
  no candidate stable, or the recommended pose's simulation failed → NEEDS_HUMAN with options
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np

from ..build.gates import PASS, AUTO_FIXED, NEEDS_HUMAN

STABLE, UNSTABLE, FAILED = "STABLE", "UNSTABLE", "FAILED"


@dataclass
class PoseScreenConfig:
    enabled: bool = False
    top_n: int = 3                  # candidate poses to screen (recommended one always included)
    nvt_ps: float = 50.0            # restrained heating
    npt_ps: float = 50.0            # restraint release
    production_ps: float = 200.0    # unrestrained segment that is judged
    frame_interval_ps: float = 5.0
    max_rmsd_A: float = 2.5         # ligand heavy-atom RMSD in the protein frame, mean over the tail
    min_contact_retention: float = 0.5   # tail mean contacting residues / frame-0 contacting residues
    tail_fraction: float = 0.5

    @classmethod
    def from_cfg(cls, d: dict | None, *, tier: str = "teaching") -> "PoseScreenConfig":
        d = dict(d or {})
        if "enabled" not in d:
            d["enabled"] = tier == "research"   # default on only where production is long enough to justify it
        valid = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in valid})

    def to_dict(self) -> dict:
        return asdict(self)


def screen_candidates(entry: dict, top_n: int) -> list[int]:
    """Ranks to screen: the recommended pose first, then other poses that passed every docking rule,
    one per cluster (different binding modes are informative; near-duplicates are not), best cluster first."""
    poses = entry.get("poses") or []
    rec = entry.get("recommended_rank")
    out: list[int] = [int(rec)] if rec else []
    seen = {poses[rec - 1].get("cluster")} if rec and rec <= len(poses) else set()
    ok = [p for p in poses if not p.get("rejected") and not p.get("clash") and p.get("rank") != rec]
    for p in sorted(ok, key=lambda p: (-int(p.get("cluster_size", 1)), float(p["score"]))):
        if len(out) >= max(1, int(top_n)):
            break
        if p.get("cluster") in seen:
            continue
        seen.add(p.get("cluster"))
        out.append(int(p["rank"]))
    return out


def assess_ligand(lig_metrics: dict, cfg: PoseScreenConfig) -> dict:
    """One ligand in one short trajectory → STABLE / UNSTABLE with numbers and reasons."""
    r = np.asarray(lig_metrics.get("rmsd_in_pocket_A") or [], dtype=float)
    c = np.asarray(lig_metrics.get("contact_residues") or [], dtype=float)
    if r.size < 2 or not np.all(np.isfinite(r)):
        return {"verdict": FAILED, "reasons": ["軌跡幀數不足或含非有限值，無法判斷穩定性"]}
    k = max(1, int(round(r.size * cfg.tail_fraction)))
    tail_rmsd = float(r[-k:].mean())
    c0 = float(c[0]) if c.size else 0.0
    retention = float(c[-k:].mean() / c0) if c0 > 0 else 0.0
    reasons = []
    if tail_rmsd > cfg.max_rmsd_A:
        reasons.append(f"後段 RMSD {tail_rmsd:.2f} Å > {cfg.max_rmsd_A} Å（配體在口袋內大幅移動或離開）")
    if retention < cfg.min_contact_retention:
        reasons.append(f"接觸殘基保留率 {retention:.0%} < {cfg.min_contact_retention:.0%}（失去原本的結合接觸）")
    return {"verdict": UNSTABLE if reasons else STABLE, "tail_rmsd_A": round(tail_rmsd, 3),
            "contact_retention": round(retention, 3), "max_rmsd_A": round(float(r.max()), 3), "reasons": reasons}


def assess_pose(metrics: dict | None, ligands: list[str], cfg: PoseScreenConfig, *, error: str | None = None) -> dict:
    """A joint pose is stable only if every ligand in it is stable."""
    if error or not metrics:
        return {"verdict": FAILED, "reasons": [f"短 MD 未完成：{error or '沒有分析結果'}"], "ligands": {}}
    per = {}
    lm = metrics.get("ligands") or {}
    for name in ligands:
        per[name] = assess_ligand(lm.get(name) or {}, cfg) if name in lm else \
            {"verdict": FAILED, "reasons": [f"分析結果中沒有配體 {name}"]}
    verdicts = {v["verdict"] for v in per.values()}
    verdict = FAILED if FAILED in verdicts else UNSTABLE if UNSTABLE in verdicts else STABLE
    worst = max((v.get("tail_rmsd_A", np.inf) for v in per.values()), default=np.inf)
    return {"verdict": verdict, "worst_tail_rmsd_A": None if not np.isfinite(worst) else worst,
            "reasons": [f"{n}：{r}" for n, v in per.items() for r in v["reasons"]], "ligands": per}


def decide(entry: dict, screened: dict[int, dict], cfg: PoseScreenConfig) -> dict:
    """Three-state decision for one docking entry.  `screened` = {rank: assess_pose(...)}."""
    rec = entry.get("recommended_rank")
    name = entry.get("name", "?")
    summ = "；".join(f"rank {k}：{v['verdict']}" + (f"（後段 RMSD {v['worst_tail_rmsd_A']:.2f} Å）"
                                                     if v.get("worst_tail_rmsd_A") is not None else "")
                    for k, v in sorted(screened.items()))
    base = {"screened": {str(k): v for k, v in screened.items()}, "summary": summ}
    r = screened.get(rec)
    if r is None or r["verdict"] == FAILED:
        why = (f"{name}：推薦的第 {rec} 名 pose 短 MD 篩選{'未執行' if r is None else '失敗'}"
               f"（{'；'.join(r['reasons']) if r else '無結果'}）。不以其他 pose 代替，請先排除模擬問題。")
        return {**base, "status": NEEDS_HUMAN, "rank": None, "why": why,
                "options": ["檢查建模/MD 錯誤後重跑篩選", "在 pose_choices 指定名次（自行負責）",
                            "關閉 docking.pose_md_screen（報告會標註未篩選）"]}
    if r["verdict"] == STABLE:
        return {**base, "status": PASS, "rank": rec,
                "why": f"{name}：推薦的第 {rec} 名 pose 在 {cfg.production_ps:.0f} ps 無限制 MD 中留在口袋"
                       f"（後段 RMSD {r['worst_tail_rmsd_A']:.2f} Å ≤ {cfg.max_rmsd_A} Å），維持推薦。{summ}"}
    stable = [(k, v) for k, v in screened.items() if v["verdict"] == STABLE]
    if stable:
        k, v = min(stable, key=lambda kv: kv[1]["worst_tail_rmsd_A"])
        return {**base, "status": AUTO_FIXED, "rank": k,
                "why": f"{name}：推薦的第 {rec} 名 pose 在短 MD 中不穩定（{'；'.join(r['reasons'])}）；"
                       f"第 {k} 名 pose 同樣通過對接保守條件且穩定（後段 RMSD {v['worst_tail_rmsd_A']:.2f} Å），自動改用。"
                       f"注意：短 MD 只排除會散開的 pose，不代表第 {k} 名的結合自由能較好。{summ}"}
    return {**base, "status": NEEDS_HUMAN, "rank": None,
            "why": f"{name}：所有篩選的 pose 在 {cfg.production_ps:.0f} ps 短 MD 中都不穩定（{summ}）。"
                   "對接結果可能不可信（盒子、質子化、受體構形），不自動選擇。",
            "options": ["檢查口袋/盒子與質子化後重跑對接", "增加 top_n 篩選更多 pose",
                        "在 pose_choices 指定名次（自行負責，報告會標註）"]}
