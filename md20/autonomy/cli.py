"""D-143: `md20 autonomy ...` and `md20 binding reassess` (the owner's entry point to the bounded-autonomy loop).

  md20 autonomy policy set --approver NAME --allow ACTION[,..] [--ns N] [--gpu-hours H] [--core-hours H] [--storage-gb G]
                           [--max-attempts K] [--no-improvement-stop K] [--yes]
  md20 autonomy policy show | revoke --by NAME
  md20 autonomy plan      dry run: what would be proposed and decided; writes nothing
  md20 autonomy status    ledger summary: cost, attempts, stops, escalations, remaining budget
  md20 autonomy approve PROPOSAL --by NAME      a person approves one proposal that needs approval
  md20 autonomy run [--max-cycles N]            executes ONLY what a written policy authorizes (no policy: refuses)
  md20 binding reassess WORKFLOW [--target T] [--include-outdated] [--dry-run]

Every command takes `--project P --workflow W` (or `--workflow-dir DIR`) and `--lang zh|en|ja|ko` (default zh).  No budget has
a default: a number that is not given is a resource that is not authorized.  Nothing here writes a policy by itself; only
`policy set`, run by a person who confirms it (interactively, or with `--yes`), does.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from ..i18n import colon, paren, pick
from ..util import atomic_write_json, now_iso, safe_name
from .controller import Controller
from .ledger import Ledger
from .model import (ACTION_LABEL_ZH, ACTION_TYPES, DIM_LABEL_ZH, FORBIDDEN_CHANGES, POLICY_FILE, Policy, PolicyError, load_policy,
                    save_policy)

EXIT_REFUSED = 2

# (zh, en, ja, ko)
T = {
    "no_policy": ("沒有行動政策：只提出建議，不會自動執行任何行動。", "No action policy: recommendations only, nothing runs by itself.",
                  "行動ポリシーがありません。提案だけを行い、自動では何も実行しません。", "행동 정책이 없습니다. 제안만 하고 자동으로 실행하지 않습니다."),
    "bad_policy": ("行動政策檔無效，視為沒有政策：", "The policy file is invalid and counts as no policy: ",
                   "ポリシーファイルが無効なので、ポリシーなしとして扱います：", "정책 파일이 올바르지 않아 정책이 없는 것으로 처리합니다: "),
    "in_effect": ("行動政策有效", "Policy in effect", "ポリシーは有効です", "정책이 유효합니다"),
    "approved": ("核准者與時間", "Approved by, at", "承認者と日時", "승인자와 시각"),
    "allowed": ("允許自動執行的行動", "Actions allowed to run by themselves", "自動実行を許可する行動", "자동 실행을 허용한 행동"),
    "budget": ("預算上限（含重試與失敗的實際花費）", "Budget ceilings (actual use, retries and failures included)",
               "予算の上限（再試行と失敗を含む実際の消費）", "예산 상한(재시도와 실패를 포함한 실제 사용량)"),
    "unauthorized": ("未核准（不給數字的資源不授權）", "not authorized (a resource without a number is not authorized)",
                     "未承認（数値のない資源は承認されません）", "미승인(숫자를 주지 않은 자원은 승인되지 않음)"),
    "attempts": ("每個行動最多嘗試（含第一次）", "Attempts per action (first launch included)", "1 つの行動の最大試行回数（初回を含む）",
                 "행동당 최대 시도(첫 실행 포함)"),
    "streak": ("連續幾次行動後診斷都沒有改善就停止", "Stop after this many actions in a row without better diagnostics",
               "診断が改善しない行動がこの回数続いたら停止", "진단이 나아지지 않은 행동이 이 횟수만큼 이어지면 중단"),
    "never": ("永遠不會自動做的事", "What never runs by itself", "自動では決して行わないこと", "자동으로는 절대 하지 않는 것"),
    "else_needs": ("政策沒列出的行動、成本估計未知的行動、用到沒給額度的資源，都要你逐項核准。",
                   "Actions the policy does not list, actions with an unknown cost estimate and actions that use a resource without a "
                   "ceiling each need your approval.",
                   "ポリシーに載っていない行動、費用が不明な行動、上限のない資源を使う行動は、1 件ずつ承認が必要です。",
                   "정책에 없는 행동, 비용을 추정할 수 없는 행동, 상한이 없는 자원을 쓰는 행동은 하나씩 승인해야 합니다."),
    "remaining": ("剩餘額度", "Remaining", "残り", "남은 한도"),
    "refused": ("拒絕，沒有寫任何檔案：", "Refused, nothing was written: ", "拒否しました。何も書き込んでいません：", "거부했습니다. 아무것도 쓰지 않았습니다: "),
    "confirm": ("以上就是這份政策允許的範圍。確認請輸入 yes：", "That is everything this policy allows. Type yes to confirm: ",
                "これがこのポリシーの許可範囲です。確認するには yes と入力：", "이것이 이 정책이 허용하는 범위입니다. 확인하려면 yes를 입력하십시오: "),
    "need_confirm": ("需要你親自確認（互動輸入 yes），或明確加上 --yes。", "You must confirm it yourself (type yes) or pass --yes explicitly.",
                     "ご自身で確認（yes を入力）するか、--yes を明示してください。", "직접 확인(yes 입력)하거나 --yes를 명시하십시오."),
    "written": ("已寫入政策：", "Policy written: ", "ポリシーを書き込みました：", "정책을 저장했습니다: "),
    "revoked": ("已撤銷政策（舊檔保留為歷史）：", "Policy revoked (the old file is kept as history): ",
                "ポリシーを取り消しました（旧ファイルは履歴として保存）：", "정책을 철회했습니다(이전 파일은 기록으로 보존): "),
    "nothing_to_revoke": ("目前沒有政策可撤銷。", "There is no policy to revoke.", "取り消すポリシーはありません。", "철회할 정책이 없습니다."),
    "no_targets": ("這個工作流程沒有已完成的結合計算，沒有可評估的證據（自主行動讀的是傘狀採樣的評估）。",
                   "This workflow has no finished binding result, so there is no evidence to assess (the loop reads umbrella-sampling assessments).",
                   "このワークフローには完了した結合計算がなく、評価できる証拠がありません。",
                   "이 워크플로에는 완료된 결합 계산이 없어 평가할 증거가 없습니다."),
    "run_refused": ("不執行：沒有有效的行動政策。請先由擁有者執行 md20 autonomy policy set。",
                    "Not running: there is no valid action policy. The owner must run md20 autonomy policy set first.",
                    "実行しません。有効な行動ポリシーがありません。先に所有者が md20 autonomy policy set を実行してください。",
                    "실행하지 않습니다. 유효한 행동 정책이 없습니다. 먼저 소유자가 md20 autonomy policy set을 실행해야 합니다."),
}


def tt(key: str, lang: str) -> str:
    return pick(T[key], lang)


ACTION_LABELS = {
    "reanalysis": ("重新分析（不產生新取樣）", "Re-analysis (no new sampling)", "再解析（新規サンプリングなし）", "재분석(새 샘플링 없음)"),
    "extend_approved_run": ("延長已核准的執行", "Extend an approved run", "承認済みの実行を延長", "승인된 실행 연장"),
    "add_independent_replica": ("新增獨立重複", "Add an independent replica", "独立レプリカを追加", "독립 반복 추가"),
    "refine_approved_umbrella_windows": ("補強已核准的傘狀採樣窗口", "Refine approved umbrella windows",
                                         "承認済みアンブレラウィンドウを補強", "승인된 엄브렐라 윈도우 보강"),
}
DIM_LABELS = {"sim_ns": ("模擬時間（ns）", "Simulated time (ns)", "シミュレーション時間（ns）", "시뮬레이션 시간(ns)"),
              "gpu_hours": ("GPU 小時", "GPU hours", "GPU 時間", "GPU 시간"),
              "core_hours": ("CPU 核心小時", "CPU core hours", "CPU コア時間", "CPU 코어 시간"),
              "storage_gb": ("儲存（GB）", "Storage (GB)", "ストレージ（GB）", "저장 공간(GB)")}
FORBIDDEN_LABELS = {
    "force_field": ("力場", "force field", "力場", "힘장"),
    "chemical_identity": ("化學身分（配體或受體是哪個分子）", "chemical identity (which molecule the ligand or receptor is)",
                          "化学的な同一性（リガンドや受容体がどの分子か）", "화학적 정체(리간드나 수용체가 어떤 분자인지)"),
    "protonation": ("質子化假設", "protonation assumptions", "プロトン化の仮定", "양성자화 가정"),
    "restraints": ("約束", "restraints", "拘束", "구속"),
    "reference_state": ("參考態（標準態與結合態的定義）", "the reference state (definition of standard and bound state)",
                        "基準状態（標準状態と結合状態の定義）", "기준 상태(표준 상태와 결합 상태의 정의)"),
    "scientific_model": ("科學模型", "the scientific model", "科学モデル", "과학 모델"),
    "paid_backend": ("付費後端", "paid back ends", "有料のバックエンド", "유료 백엔드"),
    "external_data_exposure": ("對外傳送資料", "sending data out", "データの外部送信", "데이터 외부 전송"),
}


# ------------------------------------------------------------------------------------------------ locating things
def resolve_workflow_dir(a) -> Path:
    """--workflow-dir, or <project>/workflows/<name>.  A positional/--workflow that is already a workflow folder works too."""
    wd = getattr(a, "workflow_dir", None)
    if wd:
        return Path(wd)
    name = getattr(a, "workflow", None)
    if name and (Path(name) / "config.json").is_file():
        return Path(name)
    if getattr(a, "project", None) and name:
        from ..cli import _open_project
        return _open_project(a).dir / "workflows" / safe_name(name)
    if name:
        from ..workflow import find_workflows
        hits = [r for r in find_workflows(a.dir) if r["name"] == safe_name(name)]
        if len(hits) == 1:
            return Path(hits[0]["workflow_dir"])
        raise SystemExit(f"找不到唯一的工作流程 {name}（找到 {len(hits)} 個）；請加 --project。")
    raise SystemExit("請指定 --project 與 --workflow（或 --workflow-dir）。")


def _lang(a) -> str:
    return getattr(a, "lang", None) or "zh"


def _p(msg: str = "") -> None:
    print(msg, flush=True)


# ------------------------------------------------------------------------------------------------ policy
class PolicyRefused(ValueError):
    pass


def _num(label: str, v) -> float | None:
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise PolicyRefused(f"{label} 必須是數字：{v!r}")
    if not math.isfinite(x) or x < 0:
        raise PolicyRefused(f"{label} 必須是有限的非負數：{v!r}")
    return x


def build_policy(a, *, now: str | None = None) -> Policy:
    """The policy a `policy set` command describes.  Refuses (PolicyRefused) unknown or forbidden actions, a missing approver,
    and a policy that authorizes nothing.  There are no default budgets."""
    approver = (getattr(a, "approver", None) or "").strip()
    if not approver:
        raise PolicyRefused("必須用 --approver 寫下核准者。")
    acts = [x.strip() for x in str(getattr(a, "allow", "") or "").split(",") if x.strip()]
    if not acts:
        raise PolicyRefused("必須用 --allow 列出允許的行動：" + "、".join(ACTION_TYPES))
    forbidden = [x for x in acts if x in FORBIDDEN_CHANGES]
    if forbidden:
        raise PolicyRefused("這些屬於會改變科學協定的類別，政策永遠不能授權：" + "、".join(forbidden)
                            + "（需要另外的明確決定，不是自主行動）。")
    unknown = [x for x in acts if x not in ACTION_TYPES]
    if unknown:
        raise PolicyRefused("不認得的行動：" + "、".join(unknown) + "。可用：" + "、".join(ACTION_TYPES))
    kw = {"max_sim_ns": _num("--ns", getattr(a, "ns", None)), "max_gpu_hours": _num("--gpu-hours", getattr(a, "gpu_hours", None)),
          "max_core_hours": _num("--core-hours", getattr(a, "core_hours", None)),
          "max_storage_gb": _num("--storage-gb", getattr(a, "storage_gb", None))}
    for k, label in (("max_attempts", "--max-attempts"), ("no_improvement_stop", "--no-improvement-stop")):
        v = getattr(a, k, None)
        if v is not None:
            if isinstance(v, bool) or not isinstance(v, int) or v < 1:
                raise PolicyRefused(f"{label} 必須是 ≥ 1 的整數。")
            kw[k] = v
    at = now or now_iso()
    import hashlib
    tag = hashlib.sha256(json.dumps([approver, acts, at, kw], sort_keys=True).encode("utf-8")).hexdigest()[:6]
    pol = Policy(policy_id=f"pol-{at.replace('-', '').replace(':', '')}-{tag}",
                 approved_by=approver, approved_at=at, allowed_actions=tuple(dict.fromkeys(acts)), **kw)
    ok, why = pol.effective()
    if not ok:
        raise PolicyRefused(why + "。至少要給一個大於 0 的預算（--ns、--gpu-hours、--core-hours、--storage-gb），沒有預設值。")
    return pol


def policy_summary(pol: Policy, lang: str = "zh", remaining: dict | None = None) -> list[str]:
    C = colon(lang)
    lines = [f"{tt('in_effect', lang)}{C}{pol.policy_id}", f"{tt('approved', lang)}{C}{pol.approved_by}, {pol.approved_at}",
             f"{tt('allowed', lang)}{C}" + "、".join(pick(ACTION_LABELS[a], lang) for a in pol.allowed_actions), f"{tt('budget', lang)}{C}"]
    dims = (("sim_ns", pol.max_sim_ns), ("gpu_hours", pol.max_gpu_hours), ("core_hours", pol.max_core_hours), ("storage_gb", pol.max_storage_gb))
    for d, v in dims:
        rem = (remaining or {}).get(d)
        lines.append(f"  {pick(DIM_LABELS[d], lang)}{C}" + (tt("unauthorized", lang) if v is None else f"{v:g}"
                                                          + (paren(f"{tt('remaining', lang)} {rem:g}", lang) if rem is not None else "")))
    lines.append(f"{tt('attempts', lang)}{C}{pol.max_attempts}")
    lines.append(f"{tt('streak', lang)}{C}{pol.no_improvement_stop}")
    lines.append(f"{tt('never', lang)}{C}" + "、".join(pick(v, lang) for v in FORBIDDEN_LABELS.values()))
    lines.append(tt("else_needs", lang))
    return lines


def _archive(path: Path, kind: str, stamp: str) -> Path:
    dest = path.with_name(f"autonomy_policy.{kind}-{stamp.replace(':', '').replace('-', '')}.json")
    n = 1
    while dest.exists():
        n += 1
        dest = path.with_name(f"autonomy_policy.{kind}-{stamp.replace(':', '').replace('-', '')}-{n}.json")
    path.replace(dest)
    return dest


def cmd_policy(a, wf_dir: Path | None = None) -> int:
    lang = _lang(a)
    wf_dir = wf_dir or resolve_workflow_dir(a)
    ledger = Ledger(wf_dir / "autonomy")
    path = wf_dir / "autonomy" / POLICY_FILE
    if a.pol_cmd == "show":
        pol, note = load_policy(wf_dir)
        if getattr(a, "json", False):
            _p(json.dumps({"policy": pol.to_dict() if pol else None, "note": note, "effective": bool(pol and pol.effective()[0])},
                          ensure_ascii=False, indent=2))
            return 0
        if pol is None:
            _p((tt("bad_policy", lang) + note) if path.is_file() else tt("no_policy", lang))
            return 0
        ok, why = pol.effective()
        for ln in policy_summary(pol, lang, ledger.remaining(pol)):
            _p(ln)
        if not ok:
            _p(why)
        return 0
    if a.pol_cmd == "set":
        try:
            pol = build_policy(a)
        except PolicyRefused as exc:
            print(tt("refused", lang) + str(exc), file=sys.stderr, flush=True)
            return EXIT_REFUSED
        for ln in policy_summary(pol, lang):
            _p(ln)
        if not getattr(a, "yes", False):
            if not sys.stdin.isatty():
                print(tt("refused", lang) + tt("need_confirm", lang), file=sys.stderr, flush=True)
                return EXIT_REFUSED
            if input(tt("confirm", lang)).strip().lower() != "yes":
                print(tt("refused", lang) + tt("need_confirm", lang), file=sys.stderr, flush=True)
                return EXIT_REFUSED
        if path.is_file():
            _archive(path, "superseded", pol.approved_at)
        save_policy(wf_dir, pol)
        ledger.append("policy_set", policy=pol.to_dict(), by=pol.approved_by)
        _p(tt("written", lang) + str(path))
        return 0
    if a.pol_cmd == "revoke":
        by = (getattr(a, "by", None) or "").strip()
        if not by:
            print(tt("refused", lang) + "必須用 --by 寫下是誰撤銷。", file=sys.stderr, flush=True)
            return EXIT_REFUSED
        if not path.is_file():
            _p(tt("nothing_to_revoke", lang))
            return 0
        old, _ = load_policy(wf_dir)
        dest = _archive(path, "revoked", now_iso())
        ledger.append("policy_revoked", by=by, policy_id=old.policy_id if old else None, archived=dest.name)
        _p(tt("revoked", lang) + dest.name)
        return 0
    return EXIT_REFUSED


# ------------------------------------------------------------------------------------------------ plan / status / approve
def _controller(wf_dir: Path, **kw) -> Controller:
    return Controller.for_workflow(wf_dir, **kw)


def cmd_plan(a, wf_dir: Path | None = None) -> int:
    """Dry run.  Reads the workflow and the ledger, writes nothing (no ledger line, no state file, no directory)."""
    from .inputs import inputs_for_workflow
    lang = _lang(a)
    wf_dir = wf_dir or resolve_workflow_dir(a)
    inputs = inputs_for_workflow(wf_dir, extend_ps=getattr(a, "extend_ps", None))
    ctl = _controller(wf_dir)
    out = []
    for inp in inputs:
        out.append(ctl.dry_run(inp))
    if getattr(a, "json", False):
        _p(json.dumps(out, ensure_ascii=False, indent=2, default=str))
        return 0
    pol, _note = load_policy(wf_dir)
    if pol is None or not pol.effective()[0]:
        _p(tt("no_policy", lang))
    if not out:
        _p(tt("no_targets", lang))
    for r in out:
        _p(f"[{r['scope']}] {r['mode']}")
        for ln in r["text"]:
            _p("  " + ln)
        for e in r["escalations"]:
            _p(f"  需要你決定：{e['reason']} — {e['detail']}")
    return 0


def status_data(wf_dir: Path) -> dict:
    """Everything `status` prints, as data (the GUI can show it read-only)."""
    ledger = Ledger(wf_dir / "autonomy")
    pol, note = load_policy(wf_dir)
    st = ledger.state()
    return {"policy": pol.to_dict() if pol else None, "policy_effective": bool(pol and pol.effective()[0]), "policy_note": note,
            "integrity": ledger.integrity(), "cost": ledger.cost_summary(), "remaining": ledger.remaining(pol),
            "proposals": {k: ps.snapshot() for k, ps in st.proposals.items()},
            "scopes": {k: {"stopped": v["stopped"], "streak": v["streak"], "escalations": v["escalations"][-5:]} for k, v in st.scopes.items()}}


def cmd_status(a, wf_dir: Path | None = None) -> int:
    lang = _lang(a)
    wf_dir = wf_dir or resolve_workflow_dir(a)
    d = status_data(wf_dir)
    if getattr(a, "json", False):
        _p(json.dumps(d, ensure_ascii=False, indent=2, default=str))
        return 0
    if d["policy"] and d["policy_effective"]:
        _p(f"{tt('in_effect', lang)}：{d['policy']['policy_id']}，{d['policy']['approved_by']}")
    else:
        _p(tt("no_policy", lang) if not d["policy_note"] or "沒有行動政策檔" in d["policy_note"] else tt("bad_policy", lang) + d["policy_note"])
    c = d["cost"]
    _p(f"嘗試 {c['attempts']} 次（失敗 {c['failed_attempts']}、取消 {c['cancelled_attempts']}、重試 {c['retries']}）；"
       f"實際用量 牆鐘 {c['resources']['wall_s']:.0f} s、GPU {c['resources']['gpu_hours']:.3g} h、核心 {c['resources']['core_hours']:.3g} h、"
       f"磁碟 {c['resources']['storage_gb']:.3g} GB；模擬 {c['simulated_ps_reported'] / 1000:.3g} ns（成功 {c['simulated_ps_successful'] / 1000:.3g} ns）")
    if c["observed_legacy"]["actions"]:
        _p(f"既有補窗流程（不受政策管轄）記錄 {c['observed_legacy']['actions']} 個動作")
    for k, v in d["remaining"].items():
        if v is not None:
            _p(f"剩餘 {pick(DIM_LABELS[k], lang)}：{v:g}")
    for key, p in d["proposals"].items():
        _p(f"  {key[:12]}  {pick(ACTION_LABELS.get(p['action'], (p['action'],) * 4), lang)}  {p['status']}  嘗試 {p['attempts']}")
    for s, v in d["scopes"].items():
        if v["stopped"]:
            _p(f"  [{s}] 已停止：{v['stopped'].get('reason')} — {v['stopped'].get('detail')}")
    if not d["integrity"]["ok"]:
        _p(f"帳本有 {d['integrity']['bad_lines']} 行無法解析：不會執行任何行動，請人工檢查。")
    return 0


def cmd_approve(a, wf_dir: Path | None = None) -> int:
    wf_dir = wf_dir or resolve_workflow_dir(a)
    ctl = _controller(wf_dir)
    if not (getattr(a, "by", None) or "").strip():
        print("必須用 --by 寫下是誰核准。", file=sys.stderr, flush=True)
        return EXIT_REFUSED
    ok = ctl.approve(a.proposal, a.by.strip(), getattr(a, "note", "") or "")
    _p("已記錄核准。" if ok else "帳本裡找不到這個提案。")
    return 0 if ok else 1


# ------------------------------------------------------------------------------------------------ run
def cmd_run(a, wf_dir: Path | None = None, *, make_factory=None, platform=None) -> int:
    """Run the loop for every finished binding target.  Refuses unless a valid written policy exists; the controller then
    still gates every action (allowed list, budget, prerequisites, checkpoint, claim)."""
    from types import SimpleNamespace
    from .executors import WorkflowExecutors
    from .inputs import inputs_for_workflow
    lang = _lang(a)
    wf_dir = wf_dir or resolve_workflow_dir(a)
    pol, note = load_policy(wf_dir)
    if pol is None or not pol.effective()[0]:
        print(tt("run_refused", lang) + (f" ({note})" if note else ""), file=sys.stderr, flush=True)
        return EXIT_REFUSED
    from ..project import Project
    from ..workflow import Workflow
    fake = bool(getattr(a, "fake", False))
    if not fake:
        from ..util.license import require
        require("autonomy")
    wf = Workflow.open(Project(wf_dir.parent.parent), wf_dir.name)
    if make_factory is None:
        from ..engine.factory import make_backend_factory
        if fake:
            platform = platform or SimpleNamespace(name="CPU", properties={})
        else:
            from ..env import choose_platform
            platform = platform or choose_platform()
        mode = getattr(a, "mode", "balanced")
        make_factory = lambda case, proto: make_backend_factory(case, proto, fake=fake, platform=platform, resource_mode=mode)  # noqa: E731
    from ..engine import PausePolicy
    pause = PausePolicy(pause_file=wf.project.dir / "PAUSE", pause_on_battery=False)
    ex = WorkflowExecutors(wf, make_factory, platform, should_pause=pause, progress_cb=None, check_licence=not fake)
    ctl = Controller.for_workflow(wf_dir, executor=ex, preflight=ex.preflight, reassessor=ex.reassessor)
    extend_ps = getattr(a, "extend_ps", None)
    first = inputs_for_workflow(wf_dir, extend_ps=extend_ps)
    if not first:
        _p(tt("no_targets", lang))
        return 0
    for inp in first:
        target = inp.target_key
        reports = ctl.run_until_stop(lambda t=target: next(iter(inputs_for_workflow(wf_dir, extend_ps=extend_ps, targets=[t])), inp),
                                     max_cycles=int(getattr(a, "max_cycles", 3) or 3))
        for rep in reports:
            for e in rep.executed:
                _p(f"[{inp.scope}] {e.action_type}：{e.status}" + (f"（{e.reason}）" if e.reason else ""))
            if rep.stop:
                _p(f"[{inp.scope}] 停止：{rep.stop['reason']} — {rep.stop['detail']}")
            elif not rep.executed:
                for k, d in rep.step.decisions.items():
                    _p(f"[{inp.scope}] 不執行：{d.outcome} — {d.reason}")
    return 0


# ------------------------------------------------------------------------------------------------ binding reassess
def cmd_binding(a) -> int:
    if a.bind_cmd != "reassess":
        return EXIT_REFUSED
    from ..sampling.reassess import reassess_workflow, report_lines
    wf_dir = resolve_workflow_dir(a)
    wf = None
    if not a.dry_run:
        try:
            from ..project import Project
            from ..workflow import Workflow
            wf = Workflow.open(Project(wf_dir.parent.parent), wf_dir.name)
        except Exception:  # noqa: BLE001 - without a Workflow the comparison is flagged stale instead of recomputed
            wf = None
    rep = reassess_workflow(wf_dir, targets=a.target or None, include_outdated=a.include_outdated, dry_run=a.dry_run, wf=wf)
    if getattr(a, "json", False):
        _p(json.dumps(rep, ensure_ascii=False, indent=2, default=str))
    else:
        for ln in report_lines(rep):
            _p(ln)
    return 1 if any(t["status"] == "error" for t in rep["targets"].values()) else 0


# ------------------------------------------------------------------------------------------------ argparse
def _common(p) -> None:
    p.add_argument("--project"); p.add_argument("--workflow"); p.add_argument("--workflow-dir")
    p.add_argument("--lang", choices=["zh", "en", "ja", "ko"], default="zh")


def register(sub) -> None:
    """Add `autonomy` and `binding` to the main parser's subparsers."""
    au = sub.add_parser("autonomy", help="有界自主行動（D-137、D-143）：政策、乾跑、狀態、執行")
    asub = au.add_subparsers(dest="au_cmd", required=True)
    pp = asub.add_parser("policy", help="擁有者的行動政策：set、show、revoke")
    psub = pp.add_subparsers(dest="pol_cmd", required=True)
    ps = psub.add_parser("set", help="寫下政策（沒有預設預算；要你確認）")
    _common(ps)
    ps.add_argument("--approver", required=True); ps.add_argument("--allow", required=True, help="逗號分隔：" + ",".join(ACTION_TYPES))
    ps.add_argument("--ns", type=float); ps.add_argument("--gpu-hours", type=float); ps.add_argument("--core-hours", type=float)
    ps.add_argument("--storage-gb", type=float); ps.add_argument("--max-attempts", type=int); ps.add_argument("--no-improvement-stop", type=int)
    ps.add_argument("--yes", action="store_true", help="不互動確認（寫入前仍會印出完整摘要）")
    sh = psub.add_parser("show"); _common(sh); sh.add_argument("--json", action="store_true")
    rv = psub.add_parser("revoke"); _common(rv); rv.add_argument("--by", required=True)
    pp.set_defaults(fn=lambda a: cmd_policy(a))
    pl = asub.add_parser("plan", help="乾跑：會提出什麼、怎麼決定；不寫任何檔案")
    _common(pl); pl.add_argument("--json", action="store_true"); pl.add_argument("--extend-ps", type=float, help="延長已核准 run 的長度（ps，由你決定，無預設）")
    pl.set_defaults(fn=lambda a: cmd_plan(a))
    st = asub.add_parser("status", help="帳本摘要"); _common(st); st.add_argument("--json", action="store_true")
    st.set_defaults(fn=lambda a: cmd_status(a))
    ap_ = asub.add_parser("approve", help="核准一個需要核准的提案"); _common(ap_)
    ap_.add_argument("proposal"); ap_.add_argument("--by", required=True); ap_.add_argument("--note", default="")
    ap_.set_defaults(fn=lambda a: cmd_approve(a))
    ru = asub.add_parser("run", help="只執行政策授權的行動（沒有政策就拒絕）"); _common(ru)
    ru.add_argument("--max-cycles", type=int, default=3); ru.add_argument("--extend-ps", type=float); ru.add_argument("--fake", action="store_true")
    ru.set_defaults(fn=lambda a: cmd_run(a))
    bd = sub.add_parser("binding", help="結合計算的維護：reassess（用目前規則重新評估舊結果）")
    bsub = bd.add_subparsers(dest="bind_cmd", required=True)
    ra = bsub.add_parser("reassess", help="由已儲存的 PMF 欄位重新評估並寫回（原檔備份，不重新取樣）")
    ra.add_argument("workflow"); ra.add_argument("--project"); ra.add_argument("--workflow-dir")
    ra.add_argument("--target", action="append"); ra.add_argument("--include-outdated", action="store_true")
    ra.add_argument("--dry-run", action="store_true"); ra.add_argument("--json", action="store_true")
    ra.set_defaults(fn=cmd_binding)
