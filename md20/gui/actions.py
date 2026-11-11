"""One-click gate decisions: map a gate option to a concrete config patch, write it back, invalidate downstream.

Only options the program really carries out become buttons.  Anything that needs work outside the program
(new structure, new sequence, QM parameters …) stays a text hint — a button that "accepts" an option nobody
implements would be exactly the silent guess the gates exist to prevent (寧可擋也不要猜).

An action is a plain dict (JSON-able, so the GUI can keep it on a card):
    {"id", "label", "patch": [{"path": [...], "value": ...}], "from_step", "needs_text", "text_hint"}
`path` segments are dict keys, except "ligand:<name>" which selects that entry of cfg["ligands"].
A value of the string "{text}" is replaced by what the student typed (a reason or evidence).
"""
from __future__ import annotations

import copy
import re

from .. import edition
from ..build.receptor import receptor_choice_action, CHAIN_BREAK_GATES
from ..util import atomic_write_json, load_json
from ..sampling.assessment import claim_eligible

# workflow step keys in execution order; a decision at step X invalidates X and everything after it
STEP_ORDER = [edition.STEP, "structure_gate", "receptor_docking", "screen_library", "screen_docking", "screen_selection", "docking_preflight",
              "fold", "docking", "pose_selection", "md_confirm", "md_cases", "md_runs", "analysis", "binding", "report"]
STRUCTURE_OVERRIDE = {"resolution": "resolution", "R-free": "r_free", "ligand occupancy": "ligand_occupancy",
                      "pocket occupancy": "pocket"}
_METAL_OPT = re.compile(r"metal_policy:\s*\{\s*([A-Za-z0-9:]+)\s*:\s*(bonded_open|bonded|keep_nonbonded|remove)\s*\}")
_WATER_STATE_OPT = re.compile(r"metal_water_state:\s*\{\s*([A-Za-z0-9:]+)\s*:\s*(water|hydroxide)\s*\}")
_CARBOXYLATE_OPT = re.compile(r"metal_carboxylate:\s*\{\s*([A-Za-z0-9:]+)\s*:\s*(restrain|coordinate)\s*\}")
_LOCATIONS = {"intracellular": "intracellular", "extracellular-membrane": "extracellular-membrane", "secreted": "secreted"}


class EditionLimit(ValueError):
    """A one-click action that would go beyond the limits of the edition in use (D-181).  str() is the Chinese text the
    GUI already shows for a refused action; `texts` is the same message as (zh, en, ja, ko)."""

    def __init__(self, texts):
        self.texts = tuple(texts)
        super().__init__(self.texts[0])


def _limit_hit(code: str, value, limit, feature: str, can_clamp: bool = True) -> "EditionLimit":
    return EditionLimit(edition.Hit(code, edition.SCALE, value, limit, feature, can_clamp).texts())


def _act(label: str, patch: list, from_step: str, *, needs_text: bool = False, text_hint: str = "") -> dict:
    return {"label": label, "patch": patch, "from_step": from_step, "needs_text": needs_text, "text_hint": text_hint}


def _option_action(gate: dict, option: str, *, step: str, ligand: str | None) -> dict | None:
    name = gate.get("name", "")
    ev = gate.get("evidence") or {}
    if name == edition.GATE_NAME:
        # D-181: "reduce the settings automatically and continue" is one click: the person's decision is the config key
        # edition.accept_clamp; the workflow reduces the sizes at its entrance and logs each change.  The other options
        # (change the settings, open in the complete edition, learn more) are done outside the program.
        if "edition.accept_clamp" in option:
            return _act(option, [{"path": list(edition.ACCEPT_KEY), "value": True}], edition.STEP)
        return None
    # structure confidence: "仍要使用（structure_override.x）" → override with the student's reason
    if name in STRUCTURE_OVERRIDE and "structure_override" in option:
        return _act(option, [{"path": ["structure_override", STRUCTURE_OVERRIDE[name]], "value": "{text}"}], step,
                    needs_text=True, text_hint="為什麼這個結構仍可用（會寫進決策日誌與報告）")
    # implicit solvent gates (GBn2): back to explicit water, or no binding step
    if option.startswith("md.solvent: explicit"):
        return _act(option, [{"path": ["md", "solvent"], "value": "explicit"}], "md_cases")
    # salt (D-46): "md.ions.positive: Na+（或 …）" → first ion named
    m = re.match(r"md\.ions\.(positive|negative):\s*([A-Za-z]{1,2}[+-])", option)
    if m:
        return _act(option, [{"path": ["md", "ions", m.group(1)], "value": m.group(2)}], "md_cases")
    # restraint strategy (D-23): "md.restraints: gentle"
    m = re.match(r"md\.restraints:\s*(standard|gentle|hold_backbone)\b", option)
    if m:
        return _act(option, [{"path": ["md", "restraints"], "value": m.group(1)}], "md_runs")
    if name in ("binding path", "binding target") and ev.get("target") and option.startswith("略過 "):
        # D-92: leave this target out and go on with the others; finished targets are reused from their files
        return _act(option, [{"path": ["binding", "skip_targets", ev["target"]], "value": True}], "binding")
    if name in ("binding path", "binding target") and ev.get("target") and "（binding.alone）" in option:
        # D-93: build the ligand alone (new single-ligand MD) and pull it from there; the shared-pocket MD is kept
        lig = ev.get("ligand") or ev["target"].split(":", 1)[-1]
        return _act(option, [{"path": ["binding", "alone", lig], "value": True}], "binding")
    if name in ("binding path", "binding target") and ev.get("target") and "（binding.anchor_residues）" in option:
        return _act(option, [{"path": ["binding", "anchor_residues", ev["target"]], "value": "{text}"}], "binding",
                    needs_text=True, text_hint="anchor 殘基編號，至少 3 個，位在配體要離開方向的反側（例如 120, 145, A:163）")
    if option.startswith("binding.enabled: false"):
        # D-93: "只做 MD" must also drop the targets added later (binding.added / alone), or the same gate comes back
        return _act(option, [{"path": ["binding", "enabled"], "value": False}, {"path": ["binding", "added"], "value": []},
                             {"path": ["binding", "alone"], "value": {}}], "binding")
    # pocket metal before docking: "metal_policy: {ZN: bonded}…"
    m = _METAL_OPT.search(option)
    if m:
        return _act(option, [{"path": ["metal_policy", m.group(1)], "value": m.group(2)}], step)
    # D-141 metal-bound water state: keep the neutral water (one click), confirm the hydroxide, or fall back on `bonded`.
    # The QM-input / provide-parameters options are work outside the program, so they stay hints.
    if name.startswith("metal water state "):
        m = _WATER_STATE_OPT.search(option)
        if m:
            return _act(option, [{"path": ["metal_water_state", m.group(1)], "value": m.group(2)}], "md_cases")
        return None            # "metal_policy: {…: bonded}" is handled by the generic metal_policy rule above
    # D-152/D-165 competing carboxylate: restrain / coordinate are decisions the program carries out (one click);
    # accept stays a typed config edit (it makes the result unusable), refit / protonate are work outside the program
    if name.startswith("competing carboxylate "):
        m = _CARBOXYLATE_OPT.search(option)
        if m:
            return _act(option, [{"path": ["metal_carboxylate", m.group(1)], "value": m.group(2)}], "md_cases")
        return None            # "metal_policy: {…: keep_nonbonded}" is handled by the generic metal_policy rule above
    # imported charges refused at build time: keep the fitted bonds/angles, drop the charges for that site
    if name.startswith("metal charges ") and gate.get("status") == "NEEDS_HUMAN":
        key = name.split(" ", 2)[2]
        if option.startswith("metal_params 改為不套用電荷"):
            return _act(option, [{"path": ["metal_params", key, "charges"], "value": False}], "md_cases")
        return None
    # metal site that cannot get a bonded model at build time: fall back on that site only
    if name.startswith("metal ") and gate.get("status") == "NEEDS_HUMAN":
        key = name.split(" ", 1)[1]
        for pol in ("keep_nonbonded", "remove"):
            if option.startswith(pol) or option.startswith("改用 " + pol):
                return _act(option, [{"path": ["metal_policy", key], "value": pol}], "md_cases")
        if option.startswith("改用幾何鍵結模型"):
            return _act(option, [{"path": ["metal_params", key], "value": None}], "md_cases")
        return None
    # receptor cleanup gates: only choices prepare_receptor executes
    if step == "receptor_docking" or (step == "md_cases" and name in CHAIN_BREAK_GATES + ("hetero groups",)):
        if receptor_choice_action(name, option) is None:
            return None
        # the same receptor choice applies to the docking receptor and the MD build, so both are redone
        return _act(option, [{"path": ["human_choices", "receptor", name], "value": option}], "receptor_docking")
    # blind docking / redocking
    if name == "blind docking":
        if option.startswith("box.from_residue:"):
            res = option.split(":", 1)[1].strip()
            return _act(option, [{"path": ["box"], "value": {"from_residue": res}}], step)
        if option.startswith("box.allow_blind"):
            return _act(option, [{"path": ["box", "allow_blind"], "value": True}], step)
        return None
    # HTS screen: partial library / partial docking may be accepted explicitly (listed in the report)
    if name in ("library partial", "screen partial") and option.startswith("screen.allow_partial"):
        return _act(option, [{"path": ["screen", "allow_partial"], "value": True}],
                    "screen_library" if name == "library partial" else "screen_docking")
    if name in ("multi-ligand geometry", "ligand geometry (with hydrogens)"):          # D-60
        if option.startswith("multi_ligand.exclude:"):
            names = [x.strip() for x in option.split(":", 1)[1].split("]")[0].strip(" [").split(",") if x.strip()]
            return _act(option, [{"path": ["multi_ligand", "exclude"], "value": names}], "md_cases")
        if option.startswith("multi_ligand.accept_geometry"):
            return _act(option, [{"path": ["multi_ligand", "accept_geometry"], "value": True}], "md_cases")
        if option.startswith("pose_choices:"):
            entry = option.split(":", 1)[1].split("=")[0].strip()
            return _act(option, [{"path": ["pose_choices", entry], "value": "{text}"}], "pose_selection",
                        needs_text=True, text_hint="聯合姿勢名次（數字）")
        return None
    if name == "ligand–metal coordination" and option.startswith("ligand_metal: restrain"):
        return _act(option, [{"path": ["ligand_metal"], "value": "restrain"}], "md_cases")
    if name == "box size for SMD":      # D-99: size the box for a later SMD now (rebuilds the MD cases)
        if option.startswith("md.box_for_smd: always"):
            return _act(option, [{"path": ["md", "box_for_smd"], "value": "always"}], "md_cases")
        m = re.match(r"md\.padding_nm:\s*([0-9.]+)", option)
        if m:
            return _act(option, [{"path": ["md", "padding_nm"], "value": float(m.group(1))}], "md_cases")
        return None
    if name == "long run":              # engine/longrun.py: > 1 µs, disk space, trajectory size
        if option.startswith("md.long_run_confirmed: true"):
            return _act(option, [{"path": ["md", "long_run_confirmed"], "value": True}], "md_runs")
        if option.startswith("md.long_run.solute_only: true"):
            return _act(option, [{"path": ["md", "long_run", "solute_only"], "value": True}], "md_runs")
        m = re.match(r"md\.(production_ns|long_run\.target_gb):\s*([0-9.]+)", option)
        if m:
            path = ["md", "production_ns"] if m.group(1) == "production_ns" else ["md", "long_run", "target_gb"]
            return _act(option, [{"path": path, "value": float(m.group(2))}], "md_runs")
        return None
    # D-80 folding (workflow step "fold", per ligand): choices the fold step carries out on the next run
    if name in ("fold", "fold confidence", "fold placement") and ligand:
        a = _fold_action(option, ligand)
        if a is not None:
            return a
        return None
    # D-80 membrane gates written by the build (md_cases): orientation, composition, temperature, surface placement
    if name.startswith("membrane "):
        return _membrane_action(option)
    if name == "confirm MD" and option.startswith("進入分子動力學"):
        return _act(option, [{"path": ["md_confirmed"], "value": True}], "md_confirm")
    if name == "redocking" and option.startswith("docking.skip_redock"):
        return _act(option, [{"path": ["docking", "skip_redock"], "value": True}], step)
    # peptide CPP gate (per ligand)
    if name == "CPP" and ligand:
        for k, v in _LOCATIONS.items():
            if option.endswith(k):
                return _act(option, [{"path": [f"ligand:{ligand}", "target_location"], "value": v}], step)
        if option.startswith("提供實驗證據"):
            return _act(option, [{"path": [f"ligand:{ligand}", "cpp_evidence"], "value": "{text}"}], step,
                        needs_text=True, text_hint="文獻（DOI）或自有實驗數據的簡述")
        if option.startswith("仍要繼續"):
            return _act(option, [{"path": [f"ligand:{ligand}", "cpp_override"], "value": "{text}"}], step,
                        needs_text=True, text_hint="為什麼在未驗證穿膜性的情況下仍要繼續（報告會標註）")
        return None
    # build: ligand looks like a peptide
    if name == "peptide detected" and "allow_small_molecule" in option:
        return _act(option, [{"path": ["peptide_policy", "allow_small_molecule"], "value": "{text}"}], "md_cases",
                    needs_text=True, text_hint="為什麼它是擬肽小分子而不是胜肽")
    return None


_FOLD_ENGINES = "omegafold、esmfold、boltz 或 colabfold"


def _fold_action(option: str, ligand: str) -> dict | None:
    from ..build import fold as F
    lig = f"ligand:{ligand}"
    if option == F.OPT_NO_FOLD:
        return _act(option, [{"path": [lig, "fold"], "value": False}], "fold")
    if option == F.OPT_ACCEPT_LOW:
        return _act(option, [{"path": [lig, "fold_accept_low"], "value": True}], "fold")
    if option == F.OPT_ACCEPT_RMSD:
        return _act(option, [{"path": [lig, "fold_accept_rmsd"], "value": True}], "fold")
    if option == F.OPT_DOCK:
        return _act(option, [{"path": [lig, "fold"], "value": True}], "fold")
    if option == F.OPT_OTHER_ENGINE:
        return _act(option, [{"path": [lig, "fold_engine"], "value": "{text}"}], "fold", needs_text=True,
                    text_hint=_FOLD_ENGINES)
    if option == F.OPT_RECEPTOR_SEQ:
        return _act(option, [{"path": [lig, "fold_receptor_seq"], "value": "{text}"}], "fold", needs_text=True,
                    text_hint="完整的受體序列（單字母代碼）")
    m = re.match(r"fold_engine:\s*(omegafold|esmfold|boltz|colabfold)\b", option)
    if m:
        return _act(option, [{"path": [lig, "fold_engine"], "value": m.group(1)}], "fold")
    return None          # install a tool, upload a structure: work outside the program


_LIPID_DICT = re.compile(r"^\{\s*([A-Za-z0-9]+\s*:\s*[0-9.]+\s*(,\s*[A-Za-z0-9]+\s*:\s*[0-9.]+\s*)*)\}$")


def _membrane_action(option: str) -> dict | None:
    from ..build.membrane import PRESETS
    if option.startswith("md.membrane.oriented: true"):
        return _act(option, [{"path": ["md", "membrane", "oriented"], "value": True}], "md_cases")
    m = re.match(r"md\.membrane\.lipids:\s*(.+?)\s*$", option)
    if m:
        val = m.group(1)
        if val in PRESETS and val != "gram_positive":           # gram_positive is refused by the force-field gate
            return _act(option, [{"path": ["md", "membrane", "lipids"], "value": val}], "md_cases")
        d = _LIPID_DICT.match(val)
        if d:
            comp = {k.strip().upper(): float(v) for k, v in (x.split(":") for x in d.group(1).split(","))}
            return _act(option, [{"path": ["md", "membrane", "lipids"], "value": comp}], "md_cases")
        return None
    m = re.match(r"md\.membrane\.(temperature_k|surface_distance_nm):\s*([0-9.]+)", option)
    if m:
        return _act(option, [{"path": ["md", "membrane", m.group(1)], "value": float(m.group(2))}], "md_cases")
    m = re.match(r"md\.membrane\.surface_orientation:\s*(as_is|random|parallel|normal)\b", option)
    if m:
        return _act(option, [{"path": ["md", "membrane", "surface_orientation"], "value": m.group(1)}], "md_cases")
    return None          # type changes, templates, OPM downloads: decided outside this button


def gate_actions(gate: dict, *, step: str, ligand: str | None = None) -> tuple[list[dict], list[str]]:
    """(clickable actions, options that must be handled outside the program)."""
    actions, manual = [], []
    if gate.get("status") != "NEEDS_HUMAN" and not gate.get("advisory"):    # D-48 notices keep their options clickable
        return actions, manual
    for i, opt in enumerate(gate.get("options") or []):
        a = _option_action(gate, opt, step=step, ligand=ligand)
        if a is None:
            manual.append(opt)
        else:
            a["id"] = f"{step}|{gate.get('name', '')}|{ligand or ''}|{i}"
            a["gate"] = gate.get("name", "")
            actions.append(a)
    return actions, manual


def _resolve(cfg: dict, seg: str, create: bool = True):
    if seg.startswith("ligand:"):
        n = seg.split(":", 1)[1]
        for l in cfg.get("ligands", []):
            if l.get("name") == n:
                return l
        raise KeyError(f"設定中找不到配體 {n}")
    if seg not in cfg or not isinstance(cfg[seg], dict):
        if not create:
            raise KeyError(seg)
        cfg[seg] = {}
    return cfg[seg]


def apply_patch(cfg: dict, patch: list[dict], text: str = "") -> dict:
    out = copy.deepcopy(cfg)
    for p in patch:
        path, value = list(p["path"]), p["value"]
        if value == "{text}":
            value = text
        node = out
        for seg in path[:-1]:
            node = _resolve(node, seg)
        last = path[-1]
        if isinstance(value, dict) and isinstance(node.get(last), dict) and last == "box":
            node[last] = dict(value)          # box choice replaces the whole box spec (no stale center/whole_receptor)
        else:
            node[last] = value
    return out


def invalidate_from(wf, step: str) -> list[str]:
    """Drop `step` and every later step from the workflow state so the next run redoes them."""
    st = wf.state()
    if step == edition.STEP:
        # the edition gate sits in front of every step: deciding it must not make finished work run again
        dropped = [step] if st["steps"].pop(step, None) is not None else []
        atomic_write_json(st, wf.state_path)
        return dropped
    i = STEP_ORDER.index(step) if step in STEP_ORDER else 0
    dropped = [k for k in STEP_ORDER[i:] if st["steps"].pop(k, None) is not None]
    atomic_write_json(st, wf.state_path)
    return dropped


def apply_gate_action(wf, action: dict, text: str = "") -> dict:
    """Write one decision back to the workflow config, log it as a human decision, invalidate downstream steps."""
    text = (text or "").strip()
    if action.get("needs_text") and not text:
        raise ValueError(f"「{action['label']}」需要填寫：{action.get('text_hint') or '理由'}")
    cfg = load_json(wf.dir / "config.json", wf.cfg)
    new = apply_patch(cfg, action["patch"], text)
    atomic_write_json(new, wf.dir / "config.json")
    wf.cfg = new
    dropped = invalidate_from(wf, action["from_step"])
    why = (f"使用者在 GUI 閘門卡片選擇「{action['label']}」" + (f"；理由：{text}" if text else "") +
           f"。設定已寫回 config.json，並自「{action['from_step']}」起重新執行（{', '.join(dropped) or '無已完成步驟'}）。")
    wf.dec.record("gui.gate", action.get("gate", ""), action["label"], why, kind="human",
                  patch=[{"path": p["path"], "value": text if p["value"] == "{text}" else p["value"]} for p in action["patch"]])
    return {"config": new, "invalidated": dropped}


# ------------------------------------------------------------------------------- D-131: replica plan, one-click choice
MAX_REPLICAS = 50


def set_replicas(wf, n: int, note: str = "") -> dict:
    """The student picks the number of independent replicas on the replica-plan card (1 / the advised number / custom),
    or asks for the missing ones of a finished workflow (the same call: the config now asks for more than exist).

    Writes `md.replicas` to config.json, records the choice as a human decision, and drops only the analysis and report
    steps (they must be redone with the new number).  The MD step is NOT dropped and nothing finished is deleted:
    `Workflow.run_md` resumes the same replica group, runs only the missing replicas and keeps the COMPLETE ones.
    The binding results are kept as well."""
    from ..engine.replica_plan import configured_replicas, plan_replicas, decision_why
    try:
        n = int(n)
    except (TypeError, ValueError) as exc:
        raise ValueError("重複條數要是整數") from exc
    if not 1 <= n <= MAX_REPLICAS:
        raise ValueError(f"重複條數要在 1 到 {MAX_REPLICAS} 之間")
    cap = edition.limits().max_replicas
    if cap is not None and n > cap:                       # D-181: refuse here instead of blocking at the next run
        raise _limit_hit("md.replicas", n, cap, "replicas")
    cfg = load_json(wf.dir / "config.json", wf.cfg)
    before, was_explicit = configured_replicas(cfg)
    done = wf.completed_replicas()
    cfg = copy.deepcopy(cfg)
    cfg.setdefault("md", {})["replicas"] = n
    atomic_write_json(cfg, wf.dir / "config.json")
    wf.cfg = cfg
    plan = plan_replicas(cfg, done=done)
    dropped = []
    if done:
        st = wf.state()
        dropped = [k for k in ("analysis", "report") if st["steps"].pop(k, None) is not None]
        atomic_write_json(st, wf.state_path)
    k = plan["topup_runs"]
    what = (f"使用者在重複計畫卡片選擇每個系統 {n} 條獨立重複（原本 {before} 條" + ("，設定指定" if was_explicit else "，預設") + "）。"
            + (f"已完成 {sum(done.values())} 條保留不動，只補跑缺的 {k} 條，已有的不重算；分析與報告會重做（{', '.join(dropped) or '無已完成步驟'}）。"
               if k else "") + (" " + decision_why(plan)) + (f" 使用者備註：{note}" if note else ""))
    wf.dec.record("gui.replicas", "replicas", n, what, kind="human", previous=before, done=done, topup_runs=k,
                  patch=[{"path": ["md", "replicas"], "value": n}])
    return {"replicas": n, "previous": before, "topup_runs": k, "invalidated": dropped, "config": cfg}


# ------------------------------------------------------------------------------- umbrella: manual range resampling
def binding_dirs(wf, target: str) -> list:
    """Every finished or started SMD/umbrella run of one target: the target folder itself (single run, or the first
    run kept in place when more were added, D-87) and rep1, rep2 …"""
    from pathlib import Path
    tdir = Path(wf.dir) / "binding" / target.replace(":", "_")
    reps = sorted((p for p in tdir.glob("rep*") if p.is_dir()), key=lambda p: int(p.name[3:] or 0) if p.name[3:].isdigit() else 0)
    first = [tdir] if (tdir / "binding_manifest.json").is_file() else []
    return first + reps or ([tdir] if tdir.is_dir() else [])


# ------------------------------------------------------------------------------- D-87: binding targets after the report
CONTEXT_TEXT = {"single": ("單獨與蛋白結合", "bound alone", "単独で結合", "단독 결합"),
                "multi": ("其他配體都在口袋裡", "with the other ligands in the pocket", "ほかのリガンドもポケットにある状態",
                          "다른 리간드도 포켓에 있는 상태")}


def binding_candidates(wf) -> list[dict]:
    """Every ligand that can be pulled, from the finished MD cases: target key, ligand, context, MD done or not, and
    what has been computed so far (status, runs, ΔG°)."""
    st = wf.state()["steps"]
    cases = (st.get("md_cases") or {}).get("cases") or {}
    runs = (st.get("md_runs") or {}).get("runs") or {}
    res = (st.get("binding") or {}).get("results") or {}
    b = wf.cfg.get("binding") or {}
    alone = b.get("alone") or {}
    added = set(b.get("added") or []) | {k for k, v in (alone.items() if isinstance(alone, dict) else ()) if v}
    wanted = set(b.get("ligands") or [])
    out = []
    for key, c in cases.items():
        mode = c.get("mode")
        if mode not in ("docked_single", "docked_multi"):
            continue
        for n in c.get("ligands") or []:
            tk = n if mode == "docked_single" else f"multi:{n}"
            r = res.get(tk) or {}
            planned = tk in added or (b.get("enabled") and (not wanted or n in wanted)
                                      and (mode == "docked_single" or b.get("multi", True)))
            out.append({"target": tk, "ligand": n, "case": key, "context": "single" if mode == "docked_single" else "multi",
                        "co_ligands": [m for m in c.get("ligands") or [] if m != n],
                        "md_complete": (runs.get(key) or {}).get("status") == "COMPLETE",
                        "status": r.get("status") or ("PLANNED" if planned else "NOT_STARTED"),
                        "runs": int(r.get("replicas") or 0), "dG_kj": r.get("dG_standard_kj_mol"),
                        "dG_err": r.get("dG_err_kj_mol"), "dG_withheld": r.get("dG_withheld"),
                        "delta_pmf": r.get("delta_pmf_kj_mol"), "finished_at": r.get("finished_at"),
                        # D-134: the GUI shows a ΔG° number as ΔG° only when the one claim record qualifies it
                        "dG_eligible": claim_eligible(r, "dG_standard")})
    return out


def _reopen_binding(wf) -> None:
    """Keep every finished target, mark the binding step pending and drop only the report."""
    st = wf.state()
    b = st["steps"].get("binding")
    if b:
        b["status"] = "PENDING"
    st["steps"].pop("report", None)
    atomic_write_json(st, wf.state_path)


def add_binding_targets(wf, targets: list[str], note: str = "") -> dict:
    """The student picks one or more ligands to pull after the MD (or after the report): they go to
    `binding.added`; finished targets and their windows are kept; the next run computes only the new ones and
    rebuilds the report with all of them."""
    cand = {c["target"]: c for c in binding_candidates(wf)}
    targets = [t for t in targets if t]
    bad = [t for t in targets if t not in cand]
    if not targets or bad:
        raise ValueError("沒有可以計算的配體：" + ", ".join(bad) if bad else "請至少選一個配體")
    not_ready = [t for t in targets if not cand[t]["md_complete"]]
    if not_ready:
        raise ValueError("這些配體的分子動力學還沒跑完，請先完成 MD：" + ", ".join(not_ready))
    cfg = load_json(wf.dir / "config.json", wf.cfg)
    b = cfg.setdefault("binding", {})
    b["added"] = sorted(set(b.get("added") or []) | set(targets))
    if isinstance(b.get("skip_targets"), dict):           # choosing a skipped target again brings it back (D-92)
        for t_ in targets:
            b["skip_targets"].pop(t_, None)
    if any(t.startswith("multi:") for t in targets):
        b["multi"] = True
    atomic_write_json(cfg, wf.dir / "config.json")
    wf.cfg = cfg
    _reopen_binding(wf)
    ctx = "；".join(f"{t}（{CONTEXT_TEXT[cand[t]['context']][0]}" +
                   (f"，共存：{', '.join(cand[t]['co_ligands'])}" if cand[t]["co_ligands"] else "") + "）" for t in targets)
    wf.dec.record("gui.binding", "add targets", targets,
                  f"使用者加做結合自由能（SMD＋傘狀採樣）：{ctx}。已完成的目標與其 window 保留不重算，報告重新整理後納入全部結果。"
                  + (f" 使用者備註：{note}" if note else ""), kind="human")
    return {"added": targets, "config": cfg}


def add_smd_run(wf, target: str, note: str = "") -> dict:
    """One more independent SMD/umbrella run of a finished target (new seed, starting from the next MD replica):
    the earlier runs are reused, the new one is added, ΔG° becomes the mean over all runs with their spread."""
    res = ((wf.state()["steps"].get("binding") or {}).get("results") or {}).get(target)
    if not res or res.get("status") != "PASS":
        raise ValueError(f"{target} 還沒有完成的結合自由能結果；先完成第一次")
    n = int(res.get("replicas") or 1) + 1
    cap = edition.limits().max_binding_replicas
    if cap is not None and n > cap:                       # D-181
        raise _limit_hit("binding.replicas", n, cap, "binding_full")
    cfg = load_json(wf.dir / "config.json", wf.cfg)
    b = cfg.setdefault("binding", {})
    b.setdefault("target_replicas", {})[target] = n
    if not b.get("enabled") and target not in (b.get("added") or []):
        b["added"] = sorted(set(b.get("added") or []) | {target})
    atomic_write_json(cfg, wf.dir / "config.json")
    wf.cfg = cfg
    _reopen_binding(wf)
    wf.dec.record("gui.binding", target, f"run {n}",
                  f"使用者為 {target} 加做第 {n} 次獨立的 SMD＋傘狀採樣（新的亂數種子）。前 {n - 1} 次保留，報告的 ΔG° 改為全部 "
                  f"{n} 次的平均與誤差（取重複間標準誤與 bootstrap 合併誤差的較大者）。" + (f" 使用者備註：{note}" if note else ""),
                  kind="human")
    return {"target": target, "runs": n}


def refresh_report(wf, lang: str | None = None):
    """Rebuild the report from what is on disk (no calculation); used after targets were added or runs finished."""
    from ..report.workflow_report import build_workflow_report
    from ..util import now_iso
    path = build_workflow_report(wf, lang=lang)
    st = wf.state()
    st["steps"]["report"] = {"status": "PASS", "path": str(path), "at": now_iso()}
    atomic_write_json(st, wf.state_path)
    return path


def load_windows(odir) -> tuple[dict, dict]:
    """{centre: samples} and {centre: k} from a binding output directory (w_<c>_cv.npy + windows_k.json)."""
    import numpy as np
    from pathlib import Path
    wdir = Path(odir) / "windows"
    kmap = {float(c): float(v) for c, v in load_json(wdir / "windows_k.json", {}).items() if not c.startswith("_")}  # skip stamp
    samples = {}
    for f in sorted(wdir.glob("w_*_cv.npy")):
        c = float(f.name[2:].split("_cv")[0])
        samples[c] = np.load(f)
    return samples, {c: kmap.get(c, 1000.0) for c in samples}


def resample_range(wf, target: str, lo_nm: float, hi_nm: float, *, k: float | None = None, note: str = "") -> dict:
    """The student marks a stretch of the coverage chart: plan windows there (plan_range), add them to this target's
    `binding.manual_windows`, and reopen only this target — finished windows are reused, refinement then continues
    and the PMF is recomputed."""
    if edition.limits().max_refine_rounds is not None:       # D-181: adding windows by hand reopens the window refinement
        raise EditionLimit(tuple(edition.upgrade_text("binding_full", l) for l in ("zh", "en", "ja", "ko")))
    from ..sampling.adaptive import plan_range
    from ..sampling.binding import BindingConfig
    dirs = binding_dirs(wf, target)
    if not dirs:
        raise ValueError(f"{target} 還沒有傘狀採樣結果可以補")
    samples, ks = load_windows(dirs[0])
    if not samples:
        raise ValueError(f"{target} 還沒有完成的 window")
    cfg = load_json(wf.dir / "config.json", wf.cfg)
    bc = BindingConfig(**{kk: v for kk, v in ((cfg.get("binding") or {}).get("config") or {}).items()
                          if kk in BindingConfig.__dataclass_fields__})
    plan = plan_range(lo_nm, hi_nm, samples, ks, temperature_k=bc.temperature_k, target_overlap=bc.target_overlap,
                      k=k, k_max=bc.k_umbrella_max, base_k=bc.k_umbrella)
    mw = cfg.setdefault("binding", {}).setdefault("manual_windows", {})
    have = {round(float(w["center"]), 4) for w in mw.get(target, [])}
    new = [{"center": w["center"], "k": w["k"]} for w in plan["windows"] if round(w["center"], 4) not in have]
    mw.setdefault(target, []).extend(new)
    atomic_write_json(cfg, wf.dir / "config.json")
    wf.cfg = cfg
    st = wf.state()
    b = st["steps"].get("binding")
    if b:
        (b.get("results") or {}).pop(target, None)
        b["status"] = "PENDING"
    st["steps"].pop("report", None)
    atomic_write_json(st, wf.state_path)
    wf.dec.record("gui.umbrella", target, f"resample {min(lo_nm, hi_nm):.3f}–{max(lo_nm, hi_nm):.3f} nm",
                  (plan["windows"][0]["why"] if plan["windows"] else "") + (f" 使用者備註：{note}" if note else "")
                  + f" 新增 {len(new)} 個 window；其餘結合目標不重算。", kind="human",
                  windows=new, replicas=len(dirs))
    return {"windows": new, "k": plan["k"], "spacing_nm": plan["spacing_nm"], "breaks_in_range": plan["breaks_in_range"]}


# ------------------------------------------------------------------------------- HTS screen: compound selection
def select_screen_ligands(wf, names: list[str], mode: str = "independent", note: str = "") -> dict:
    """The student ticks compounds in the 篩選 tab: write screen.select / screen.next_mode, invalidate from the
    final docking onward (the screen itself is kept)."""
    names = [str(n) for n in names if str(n).strip()]
    if not names:
        raise ValueError("請至少勾選一個化合物")
    if mode not in ("independent", "simultaneous"):
        raise ValueError("模式必須是 independent 或 simultaneous")
    if mode == "simultaneous" and len(names) < 2:
        raise ValueError("多配體同時對接至少要選 2 個化合物")
    cfg = load_json(wf.dir / "config.json", wf.cfg)
    cap = edition.limits().max_ligands
    if cap is not None:                                    # D-181: the explicit ligands and the picks must fit together
        total = len({str(l.get("name")) for l in cfg.get("ligands") or [] if isinstance(l, dict)} | set(names))
        if total > cap:
            raise _limit_hit("ligands.count", total, cap, "multi_ligand_full", False)
    sc = cfg.setdefault("screen", {})
    sc["select"], sc["next_mode"] = names, mode
    atomic_write_json(cfg, wf.dir / "config.json")
    wf.cfg = cfg
    dropped = invalidate_from(wf, "screen_selection")
    wf.dec.record("gui.screen", "select", names,
                  f"使用者在「篩選」分頁勾選 {len(names)} 個化合物進入{'多配體同時對接' if mode == 'simultaneous' else '各自對接與 MD'}"
                  + (f"；備註：{note}" if note else "") + f"。自 screen_selection 起重新執行（{', '.join(dropped) or '無已完成步驟'}）。",
                  kind="human", mode=mode)
    return {"selected": names, "mode": mode, "invalidated": dropped}
