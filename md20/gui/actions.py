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

from ..build.receptor import receptor_choice_action
from ..util import atomic_write_json, load_json

# workflow step keys in execution order; a decision at step X invalidates X and everything after it
STEP_ORDER = ["structure_gate", "receptor_docking", "docking_preflight", "docking", "pose_selection", "md_cases",
              "md_runs", "analysis", "binding", "report"]
STRUCTURE_OVERRIDE = {"resolution": "resolution", "R-free": "r_free", "ligand occupancy": "ligand_occupancy",
                      "pocket occupancy": "pocket"}
_METAL_OPT = re.compile(r"metal_policy:\s*\{\s*([A-Za-z0-9:]+)\s*:\s*(bonded|keep_nonbonded|remove)\s*\}")
_LOCATIONS = {"intracellular": "intracellular", "extracellular-membrane": "extracellular-membrane", "secreted": "secreted"}


def _act(label: str, patch: list, from_step: str, *, needs_text: bool = False, text_hint: str = "") -> dict:
    return {"label": label, "patch": patch, "from_step": from_step, "needs_text": needs_text, "text_hint": text_hint}


def _option_action(gate: dict, option: str, *, step: str, ligand: str | None) -> dict | None:
    name = gate.get("name", "")
    ev = gate.get("evidence") or {}
    # structure confidence: "仍要使用（structure_override.x）" → override with the student's reason
    if name in STRUCTURE_OVERRIDE and "structure_override" in option:
        return _act(option, [{"path": ["structure_override", STRUCTURE_OVERRIDE[name]], "value": "{text}"}], step,
                    needs_text=True, text_hint="為什麼這個結構仍可用（會寫進決策日誌與報告）")
    # pocket metal before docking: "metal_policy: {ZN: bonded}…"
    m = _METAL_OPT.search(option)
    if m:
        return _act(option, [{"path": ["metal_policy", m.group(1)], "value": m.group(2)}], step)
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
    if step == "receptor_docking":
        if receptor_choice_action(name, option) is None:
            return None
        return _act(option, [{"path": ["human_choices", "receptor", name], "value": option}], step)
    # blind docking / redocking
    if name == "blind docking":
        if option.startswith("box.from_residue:"):
            res = option.split(":", 1)[1].strip()
            return _act(option, [{"path": ["box"], "value": {"from_residue": res}}], step)
        if option.startswith("box.allow_blind"):
            return _act(option, [{"path": ["box", "allow_blind"], "value": True}], step)
        return None
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


def gate_actions(gate: dict, *, step: str, ligand: str | None = None) -> tuple[list[dict], list[str]]:
    """(clickable actions, options that must be handled outside the program)."""
    actions, manual = [], []
    if gate.get("status") != "NEEDS_HUMAN":
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
