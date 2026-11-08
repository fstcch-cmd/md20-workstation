"""NiceGUI pages.  Thin layer over md20.gui.logic; run with `md20 gui`."""
from __future__ import annotations

import os

from pathlib import Path

from nicegui import app, ui

from ..env import run_doctor, choose_platform
from ..project import Project
from ..util import default_projects_dir, load_json, safe_name
from ..workflow import Workflow
from .logic import Runner, config_from_form, list_workflows, pose_table, set_pose_choice, screen_table
from .actions import apply_gate_action, resample_range, select_screen_ligands
from . import actions as ACT
from . import theme
from .connection import CONNECTION_JS, tune_heartbeat
from ..docking.screen import echart_screen, echart_ranking
from .views import (gate_cards, timeline, live_series, echart_options, viewer_targets, scene_for, viewer_html,
                    coverage_targets, coverage_chart, coverage_summary, replica_card, phase_rows)
from .content import t
from ..i18n import pick, colon, paren, LANGS, LANG_NAMES, QUASAR_LANG
from .gate_text import gate_title, gate_general, option_text

from ..util.timeutil import to_local
from ..util import license as LIC
RUNNER = Runner()
STATE: dict = {"projects_dir": default_projects_dir(), "platform": None, "doctor": None, "lang": None}


def lang() -> str:
    """Interface language (D-51): English by default; the choice is kept in <projects>/gui_settings.json."""
    path = Path(STATE["projects_dir"]) / "gui_settings.json"
    try:
        mt = path.stat().st_mtime_ns
    except OSError:
        mt = None
    if STATE["lang"] is None or STATE.get("lang_mtime") != mt:      # re-read when the file changes (another window)
        STATE["lang"] = load_json(path, {}).get("lang", "en") if mt else "en"
        STATE["lang_mtime"] = mt
    return STATE["lang"] if STATE["lang"] in LANG_NAMES else "en"


def _(zh: str, en: str, ja: str = "", ko: str = "") -> str:
    """Inline text for page code, in the interface language (D-74; a missing Japanese or Korean text falls back to English)."""
    return pick((zh, en, ja, ko), lang())


STEP_TEXT = {"receptor_input": ("受體來源", "Receptor source", "受容体の入力", "수용체 입력"),
             "receptor_docking": ("受體整理", "Receptor preparation", "受容体の準備", "수용체 준비"),
             "screen_library": ("篩選：化合物庫", "Screening: compound library", "スクリーニング：化合物ライブラリ", "스크리닝: 화합물 라이브러리"),
             "screen_docking": ("篩選：快速對接", "Screening: fast docking", "スクリーニング：高速ドッキング", "스크리닝: 빠른 도킹"),
             "screen_selection": ("篩選：選擇化合物", "Screening: compound selection", "スクリーニング：化合物の選択", "스크리닝: 화합물 선택"),
             "fold": ("胜肽摺疊", "Peptide folding", "ペプチドの折りたたみ", "펩타이드 접힘"),
             "docking": ("分子對接", "Molecular docking", "分子ドッキング", "분자 도킹"),
             "pose_selection": ("姿勢選擇", "Pose selection", "ポーズの選択", "포즈 선택"),
             "md_confirm": ("確認進入分子動力學", "Confirm molecular dynamics", "分子動力学に進む確認", "분자동역학 진행 확인"),
             "md_cases": ("建模", "System building", "系の構築", "계 구축"),
             "md_runs": ("分子動力學", "Molecular dynamics", "分子動力学", "분자동역학"),
             "analysis": ("軌跡分析", "Trajectory analysis", "トラジェクトリ解析", "궤적 분석"),
             "binding": ("結合自由能", "Binding free energy", "結合自由エネルギー", "결합 자유 에너지"),
             "report": ("報告", "Report", "レポート", "보고서")}
STATUS_TEXT = {"PASS": ("完成", "Done", "完了", "완료"), "COMPLETE": ("完成", "Done", "完了", "완료"),
               "RUNNING": ("執行中", "Running", "実行中", "실행 중"), "PAUSED": ("已暫停", "Paused", "一時停止中", "일시 정지됨"),
               "NEEDS_HUMAN": ("需要你決定", "Needs your decision", "判断が必要", "결정 필요"),
               "ERROR": ("錯誤", "Error", "エラー", "오류"), "IDLE": ("未執行", "Idle", "未実行", "실행 전"),
               "AUTO_FIXED": ("已自動修正", "Corrected automatically", "自動で修正済み", "자동 수정됨"), "—": ("—", "—", "—", "—")}


def card_source(src: str, lang_code: str | None = None) -> str:
    """Source label of a gate card; gate_cards(lang=...) already writes it in the interface language."""
    return src


def card_badge(c: dict, lang_code: str | None = None) -> str:
    if c.get("advisory"):
        return pick(("科學限制提醒", "Scientific notice", "科学的な限界のお知らせ", "과학적 한계 안내"), lang_code or lang())
    return c["label"]                     # gate_cards(lang=...) already wrote the badge in the interface language


# the zh and en labels of these three are quoted in the student guides (docs/students/): keep them as they are
RESOURCE_MODES = {"background": ("省資源：可同時寫報告", "Light: keep using the computer",
                                 "省リソース：レポートを書きながら使う", "절약: 보고서를 쓰면서 사용"),
                  "balanced": ("平衡（預設）", "Balanced (default)", "バランス（既定）", "균형(기본)"),
                  "full": ("全速：電腦閒置時", "Full speed: computer idle", "フル稼働：パソコンを使っていないとき",
                           "최대 속도: 컴퓨터를 쓰지 않을 때")}


def resource_mode() -> str:
    m = load_json(Path(STATE["projects_dir"]) / "gui_settings.json", {}).get("resource_mode", "balanced")
    return m if m in RESOURCE_MODES else "balanced"


def set_resource_mode(mode: str) -> None:
    """D-68: the user decides how much of the computer a calculation may take; applies to the next start (and to
    Vina calls of the running one, which read it from the environment)."""
    from ..util import atomic_write_json
    path = Path(STATE["projects_dir"]) / "gui_settings.json"
    d = load_json(path, {})
    d["resource_mode"] = mode if mode in RESOURCE_MODES else "balanced"
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(d, path)
    os.environ["MD20_RESOURCE_MODE"] = d["resource_mode"]


def switch_projects_dir(path: str | Path) -> Path:
    """D-88: use another projects folder (chosen or opened by the user); the interface language and resource mode
    follow along, and the choice is kept for the next start (gui/folders.py)."""
    from . import folders
    from ..util import atomic_write_json
    new = Path(path)
    new.mkdir(parents=True, exist_ok=True)
    keep_lang, keep_mode = lang(), resource_mode()
    STATE["projects_dir"] = new
    STATE["lang"] = None
    sp = new / "gui_settings.json"
    d = load_json(sp, {})
    if "lang" not in d or "resource_mode" not in d:
        d.setdefault("lang", keep_lang)
        d.setdefault("resource_mode", keep_mode)
        atomic_write_json(d, sp)
    folders.remember(new)
    return new


def set_lang(code: str) -> None:
    from ..util import atomic_write_json
    STATE["lang"] = code if code in LANG_NAMES else "en"
    path = Path(STATE["projects_dir"]) / "gui_settings.json"
    d = load_json(path, {})
    d["lang"] = STATE["lang"]
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(d, path)


def _theme_head(L: str) -> None:
    """D-146: the design system (gui/theme.py) and the connection keeper (D-147) on every page."""
    from . import theme
    ui.colors(**theme.QUASAR_COLORS)
    ui.add_head_html(theme.css(L))
    ui.add_head_html(CONNECTION_JS)

STATUS_COLOR = {"PASS": "positive", "COMPLETE": "positive", "RUNNING": "primary", "PAUSED": "warning",
                "NEEDS_HUMAN": "negative", "ERROR": "negative"}


NO_DATA = ("沒有資料", "No data", "データがありません", "데이터가 없습니다")


def no_data() -> str:
    """Quasar's empty-table text follows the language chosen at server start; set it per table instead (D-74)."""
    return f'no-data-label="{pick(NO_DATA, lang())}"'


def _platform():
    if STATE["platform"] is None:
        STATE["platform"] = choose_platform()
    return STATE["platform"]


def _feature_card():
    """D-128: the licence is valid but a calculation needed a feature it does not include (binding, membrane, hts, cg).
    The message of the blocked start stays on this card until it is dismissed or a start succeeds."""
    texts = STATE.get("feature_block")
    if not texts:
        return
    L = lang()
    with ui.card().classes("w-full max-w-5xl mx-auto md20-card md20-notice").props("data-testid=feature-card"):
        ui.label(_("你的授權不含此功能", "Your licence does not include this feature", "お持ちのライセンスにはこの機能が含まれていません",
                   "귀하의 라이선스에는 이 기능이 포함되어 있지 않습니다")).classes("md20-section")
        ui.label(pick(texts, L)).classes("text-sm")

        def dismiss():
            STATE["feature_block"] = None
            ui.navigate.reload()
        ui.button(_("關閉", "Dismiss", "閉じる", "닫기"), on_click=dismiss).props("flat dense color=primary")


def _license_card():
    """D-125: when no valid licence is installed, a card on every page says so, shows this computer's machine code and
    offers an import button (an upload, not a browser dialog).  Browsing, reports and diagnostics stay open."""
    st = LIC.status()
    if st.ok:
        _feature_card()
        return
    L = lang()
    with ui.card().classes("w-full max-w-5xl mx-auto md20-card md20-notice").props("data-testid=license-card"):
        ui.label(_("需要 MD20 授權", "MD20 licence needed", "MD20 のライセンスが必要です", "MD20 라이선스가 필요합니다")).classes("md20-section")
        ui.label(st.message(L)).classes("text-sm")
        ui.label(pick(LIC.HOWTO, L)).classes("text-sm")
        with ui.row().classes("items-center gap-2"):
            ui.label(pick(LIC.MACHINE_LABEL, L) + colon(L)).classes("text-sm")
            ui.label(st.machine_code).classes("text-sm font-mono").props("data-testid=machine-code")
            ui.button(icon="content_copy", on_click=lambda: (ui.run_javascript(f"navigator.clipboard.writeText('{st.machine_code}')"), ui.notify(st.machine_code))
                      ).props("flat dense")
        result = ui.column().classes("gap-0")

        async def got(e):
            fname, data = await _upload_payload(e)
            import tempfile
            tmp = Path(tempfile.mkdtemp(prefix="md20lic_")) / "upload.md20license"
            tmp.write_bytes(data[:LIC.MAX_FILE_BYTES + 1])
            result.clear()
            try:
                new = LIC.install(tmp)
            except LIC.LicenseError as exc:
                with result:
                    ui.label(pick(exc.texts, L)).classes("text-sm text-negative").style("white-space: pre-line")
                return
            finally:
                tmp.unlink(missing_ok=True)
            ui.notify(pick(LIC.INSTALLED, L).format(licensee=new.licensee, expires=new.expires or pick(LIC.NO_EXPIRY, L)), type="positive")
            ui.navigate.reload()
        ui.upload(on_upload=got, auto_upload=True, label=_("匯入授權檔 (.md20license)", "Import licence file (.md20license)",
                                                           "ライセンスファイル (.md20license) を取り込む",
                                                           "라이선스 파일(.md20license) 가져오기")
                  ).props("accept=.md20license,.json flat bordered color=primary data-testid=license-upload").classes("w-full")


def _header():
    L = lang()
    _theme_head(L)
    with ui.header().classes("items-center justify-between md20-header"):
        ui.label(t("app_title", L)).classes("text-lg md20-title")
        with ui.row().classes("items-center gap-4"):
            ui.link(t("nav_home", L), "/").classes("text-white no-underline")
            ui.link(t("nav_system", L), "/system").classes("text-white no-underline")

            def change(e):
                set_lang(e.value)
                ui.navigate.reload()
            ui.select({k: pick(v, L) for k, v in RESOURCE_MODES.items()}, value=resource_mode(),
                      on_change=lambda e: (set_resource_mode(e.value), ui.notify(_(
                          "資源用量已更新，從下一個計算步驟開始生效。", "Resource use updated. It applies from the next step.",
                          "リソースの使用量を更新しました。次の計算ステップから反映されます。",
                          "자원 사용량을 바꿨습니다. 다음 계산 단계부터 적용됩니다.")))
                      ).props("dense borderless options-dense").classes("w-56").tooltip(_(
                          "計算可以使用多少電腦資源", "How much of this computer a calculation may use",
                          "計算にこのパソコンの資源をどれだけ使うか", "계산에 이 컴퓨터 자원을 얼마나 쓸지"))
            ui.select(LANG_NAMES, value=L, on_change=change).props("dense borderless options-dense data-testid=lang-select").classes("w-28")
    _license_card()
    # D-67: wherever the user goes (home, system page, another language), the running calculation is one click away
    job = RUNNER.running(STATE["projects_dir"])
    if job is not None:
        href = f"/wf/{job.wf.project.dir.name}/{job.wf.name}"
        with ui.row().classes("w-full items-center gap-3 px-5 py-2 md20-running").props("data-testid=running-banner"):
            ui.html('<span class="md20-pulse" aria-hidden="true"></span>')
            ui.label(_("計算進行中：", "Calculation running: ", "計算中：", "계산 중: ") + f"{job.wf.project.dir.name} / {job.wf.name}").classes("text-sm")
            ui.button(_("回到進度", "Back to progress", "進行状況に戻る", "진행 상황으로 돌아가기"),
                      on_click=lambda h=href: ui.navigate.to(h)).props("dense outline no-caps color=primary")


@ui.page("/system")
def dashboard():
    _header()
    with ui.column().classes("w-full max-w-5xl mx-auto"):
        L = lang()
        ui.label(_("電腦狀態", "Computer status", "パソコンの状態", "컴퓨터 상태")).classes("text-xl font-semibold")
        box = ui.markdown(_("_按下按鈕檢查這台電腦_", "_Press a button to check this computer_",
                            "_ボタンを押すとこのパソコンを診断します_", "_버튼을 누르면 이 컴퓨터를 진단합니다_"))

        async def do_doctor(bench: bool):
            box.set_content(t("doctor_bench_wait", L) if bench else t("doctor_wait", L))
            from nicegui import run as nrun
            rep = await nrun.io_bound(run_doctor, do_benchmark=bench, benchmark_seconds=15.0)
            STATE["doctor"] = rep
            if rep.platform:
                STATE["platform"] = None
            box.set_content(rep.to_markdown(lang()))
            render_drivers(rep)
        with ui.row():
            ui.button(t("doctor_quick", L), on_click=lambda: do_doctor(False))
            ui.button(t("doctor_bench", L), on_click=lambda: do_doctor(True)).props("outline")
        drv_box = ui.column().classes("w-full gap-2")
        _optional_tools(L)

        def render_drivers(rep):
            drv_box.clear()
            plans = (rep.hardware or {}).get("driver_plans") or []
            from ..env.drivers import installer_hint, DriverPlan
            with drv_box:
                for d in plans:
                    dp = DriverPlan(**{k: v for k, v in d.items() if k in DriverPlan.__dataclass_fields__})
                    color = {"OK": "positive", "UPDATE": "warning", "FALLBACK": "grey", "NONE": "warning", "UNKNOWN": "grey"}[dp.status]
                    with ui.card().classes("w-full"):
                        with ui.row().classes("items-center gap-2"):
                            ui.badge(dp.status, color=color)
                            drv = dp.driver or _("未知", "unknown", "不明", "알 수 없음")
                            ui.label(f"{dp.vendor} {dp.gpu} · " + _(f"驅動 {drv} · 目前使用 {dp.platform_now}",
                                                                    f"driver {drv} · now using {dp.platform_now}",
                                                                    f"ドライバー {drv} · 現在の使用先 {dp.platform_now}",
                                                                    f"드라이버 {drv} · 현재 사용 {dp.platform_now}")).classes("font-semibold")
                        ui.label(dp.why).classes("text-sm whitespace-pre-wrap")
                        for st in dp.steps:
                            ui.label(st).classes("text-sm text-primary")
                        ui.label(_("安裝器指令：", "Installer command: ", "インストーラーのコマンド：", "설치 프로그램 명령: ")
                                 + installer_hint(dp)).classes("text-xs font-mono")
                        with ui.row().classes("gap-2"):
                            if dp.download_url:
                                prog = ui.label("").classes("text-sm")

                                async def do_download(url=dp.download_url, prog=prog):
                                    from nicegui import run as nrun
                                    from ..env.drivers import download_driver
                                    prog.set_text(_("下載中…", "Downloading…", "ダウンロード中…", "다운로드 중…"))
                                    try:
                                        dest = await nrun.io_bound(download_driver, url)
                                    except Exception as exc:  # noqa: BLE001
                                        prog.set_text(_("下載失敗：", "Download failed: ", "ダウンロードに失敗しました：", "다운로드 실패: ") + str(exc)); return
                                    prog.set_text(_(f"已下載到 {dest}。請雙擊安裝，這需要管理員權限並重開機，之後再執行一次安裝器。",
                                                    f"Downloaded to {dest}. Double-click it to install (this needs administrator "
                                                    "rights and a restart), then run the installer again.",
                                                    f"{dest} にダウンロードしました。ダブルクリックしてインストールしてください。管理者権限と再起動が必要です。"
                                                    "その後、インストーラーをもう一度実行してください。",
                                                    f"{dest}에 다운로드했습니다. 더블클릭해 설치하십시오. 관리자 권한과 재시작이 필요합니다. "
                                                    "그다음 설치 프로그램을 다시 실행하십시오."))
                                ui.button(_("下載官方驅動", "Download the official driver", "公式ドライバーをダウンロード", "공식 드라이버 다운로드")
                                          + (paren(dp.package_version, L) if dp.package_version else ""),
                                          on_click=do_download).props("color=primary")
                            if dp.download_page:
                                ui.button(_("開啟官方下載頁", "Open the official download page", "公式のダウンロードページを開く", "공식 다운로드 페이지 열기"), on_click=lambda u=dp.download_page: ui.navigate.to(u, new_tab=True)).props("outline")
        ui.separator()
        ui.label(_("流程", "Workflows", "ワークフロー", "워크플로")).classes("text-xl font-semibold")
        rows = list_workflows(STATE["projects_dir"])
        cols = [{"name": k, "label": l, "field": k} for k, l in
                (("project", _("專案", "Project", "プロジェクト", "프로젝트")), ("workflow", _("流程", "Workflow", "ワークフロー", "워크플로")),
                 ("last_step", _("最後步驟", "Last step", "最後のステップ", "마지막 단계")), ("status", t("status", L)),
                 ("updated", _("更新時間", "Updated", "更新日時", "업데이트")))]
        tbl = ui.table(columns=cols, rows=rows, row_key="workflow").props(no_data()).classes("w-full")
        tbl.on("rowClick", lambda e: ui.navigate.to(f"/wf/{e.args[1]['project']}/{e.args[1]['workflow']}"))
        if not rows:
            ui.label(_("還沒有流程。到首頁選一種模式開始。", "No workflows yet. Choose a mode on the home page to start.",
                       "まだワークフローがありません。ホームでモードを選んで始めてください。",
                       "아직 워크플로가 없습니다. 홈에서 모드를 골라 시작하십시오.")).classes("text-gray-500")


def _optional_tools(L: str):
    """D-80: folding environment (setup-fold) and coarse-grained tools (setup-cg): installed or not, the exact install
    command, and a button that shows the install plan.  Nothing is installed from the GUI."""
    from .advanced import tool_rows, setup_preview, TOOL_TEXT
    from ..build.fold import fold_status
    from ..build.martini import availability
    ui.separator()
    ui.label(_("選用工具", "Optional tools", "追加のツール", "선택 도구")).classes("text-xl font-semibold")
    try:
        rows = tool_rows(fold_status(), availability(), L)
    except Exception as exc:  # noqa: BLE001 — a broken probe must not take the status page down
        ui.label(_("無法檢查選用工具：", "Could not check the optional tools: ", "追加のツールを確認できませんでした：",
                   "선택 도구를 확인할 수 없습니다: ") + str(exc)).classes("text-negative text-sm")
        return
    for r in rows:
        with ui.card().classes("w-full md20-card").props(f"data-testid=tool-{r['key']}"):
            with ui.row().classes("items-center gap-2"):
                ui.badge(r["status"], color="positive" if r["installed"] else "grey-7")
                ui.label(r["title"]).classes("font-semibold")
            ui.label(r["detail"]).classes("text-xs font-mono md20-muted")
            ui.label(r["note"]).classes("text-sm")
            ui.label(pick(TOOL_TEXT["install_cmd"], L) + colon(L)).classes("text-sm")
            ui.label(r["command"]).classes("text-sm font-mono")
            out = ui.label("").classes("text-xs font-mono whitespace-pre-wrap")

            async def show(kind=r["key"], out=out):
                from nicegui import run as nrun
                try:
                    lines = await nrun.io_bound(setup_preview, kind, lang())
                except Exception as exc:  # noqa: BLE001
                    lines = [f"{type(exc).__name__}: {exc}"]
                out.set_text("\n".join(lines))
            with ui.row().classes("items-center gap-2"):
                ui.button(pick(TOOL_TEXT["preview"], L), on_click=show).props(f"outline no-caps data-testid=preview-{r['key']}")
                if not r["installed"]:
                    _install_button(r["key"], L)


def _install_button(kind: str, L: str):
    """D-85: run `md20 setup-fold … --warmup` / `md20 setup-cg` from the GUI in the background and show its log."""
    from .advanced import TOOL_TEXT, start_install, install_progress
    from ..util import default_projects_dir
    note = ui.label(pick(TOOL_TEXT["install_fold_note"], L) if kind == "fold" else "").classes("text-sm")
    log = ui.label("").classes("text-xs font-mono whitespace-pre-wrap w-full")

    def poll():
        text, rc = install_progress(kind)
        if not text and rc is None:
            return
        head = pick(TOOL_TEXT["installing"], L) if rc is None else f"{pick(TOOL_TEXT['install_done'], L)} {rc}"
        log.set_text(head + "\n" + text)

    def go():
        start_install(kind, Path(STATE["projects_dir"]) / "_tools")
        poll()
    ui.button(pick(TOOL_TEXT["install_now"], L), on_click=go).props(f"color=primary no-caps data-testid=install-{kind}")
    ui.timer(2.0, poll)
    poll()
    return note


BIND_STATUS = {"PASS": ("已完成", "Done", "完了", "완료"), "PLANNED": ("待計算", "To run", "未計算", "계산 예정"),
               "NOT_STARTED": ("未計算", "Not computed", "未計算", "계산 안 함"), "PENDING": ("待計算", "To run", "未計算", "계산 예정"),
               "PAUSED": ("暫停", "Paused", "一時停止", "일시 정지"), "NEEDS_HUMAN": ("需要決定", "Needs a decision", "判断が必要", "결정 필요"),
               "SKIPPED": ("不計算", "Not computed (see report)", "計算しない", "계산 안 함")}


def _binding_panel(wf: Workflow, project: str, name: str):
    """D-87: binding free energy per ligand, also after the report — add ligands, add one more SMD run to a finished
    one, and rebuild the report from everything computed so far."""
    L = lang()
    card = ui.expansion(_("結合自由能（SMD＋傘狀採樣）：選配體、加做、整合報告",
                          "Binding free energy (SMD and umbrella sampling): choose ligands, add runs, update the report",
                          "結合自由エネルギー（SMD と傘サンプリング）：リガンドの選択、追加、レポートの更新",
                          "결합 자유 에너지(SMD와 우산 샘플링): 리간드 선택, 추가 계산, 보고서 갱신"),
                       value=False).classes("w-full md20-card").props("data-testid=binding-panel")
    with card:
        ui.label(_("MD 做完後，可以一次選一個或幾個配體計算結合自由能；報告產生後也可以回來加做別的配體，或讓同一個配體多做一次"
                   "（新的亂數種子），報告會整合全部結果。多配體系統裡拉一個配體時，其他配體留在口袋裡，結果標為「與其他配體共存」。",
                   "After the MD you can compute binding free energy for one or several ligands at a time. After the report you "
                   "can come back to add other ligands, or run the same ligand once more with a new random seed; the report "
                   "combines every result. In the all-ligands system the other ligands stay in the pocket while one is pulled, "
                   "and the result is labelled 'with the other ligands'.",
                   "MD の後、1 つまたは複数のリガンドの結合自由エネルギーを計算できます。レポートの後でも戻って別のリガンドを追加したり、"
                   "同じリガンドをもう 1 回（新しい乱数の種で）計算したりでき、レポートはすべての結果をまとめます。全リガンドの系で 1 つを"
                   "引き離すとき、ほかのリガンドはポケットに残り、結果は「ほかのリガンドと共存」と表示します。",
                   "MD가 끝나면 리간드 하나 또는 여러 개의 결합 자유 에너지를 계산할 수 있습니다. 보고서가 나온 뒤에도 돌아와서 다른 "
                   "리간드를 추가하거나 같은 리간드를 새 난수 시드로 한 번 더 계산할 수 있으며, 보고서는 모든 결과를 합칩니다. 모든 리간드 "
                   "계에서 하나를 당길 때 다른 리간드는 포켓에 남고, 결과는 '다른 리간드와 공존'으로 표시합니다.")).classes("text-sm")
        tbl = ui.table(columns=[{"name": k, "label": l, "field": k, "align": "left"} for k, l in (
            ("target", _("目標", "Target", "対象", "대상")), ("ligand", _("配體", "Ligand", "リガンド", "리간드")),
            ("context", _("情境", "Context", "状況", "상황")), ("status", _("狀態", "Status", "状態", "상태")),
            ("runs", _("SMD 次數", "SMD runs", "SMD の回数", "SMD 횟수")), ("dg", "ΔG° (kJ mol⁻¹)"))],
            rows=[], row_key="target", selection="multiple").props("dense flat").props(no_data()).classes("w-full")
        note = ui.input(option_text("備註（為什麼選這些）", L)).classes("w-96")

        def rows():
            out = []
            for c in ACT.binding_candidates(wf):
                dg = "—"
                if c["dG_kj"] is not None and c.get("dG_eligible"):
                    dg = f"{c['dG_kj']:.1f}" + (f" ± {c['dG_err']:.1f}" if c["dG_err"] is not None else "")
                elif c["dG_kj"] is not None:          # D-134: a number that failed (or lacks) the sampling assessment is not a ΔG°
                    dg = _("不作為 ΔG°（取樣評估未通過或缺漏）", "not a ΔG° (sampling assessment failed or missing)",
                           "ΔG° として扱わない（取得評価が不合格または欠落）", "ΔG°로 쓰지 않음(샘플링 평가 미통과 또는 누락)")
                elif c["status"] == "PASS" and c["dG_withheld"]:
                    dg = _("不輸出（見報告）", "not reported (see report)", "出力しない（レポート参照）", "출력 안 함(보고서 참조)")
                out.append({"target": c["target"], "ligand": c["ligand"],
                            "context": pick(ACT.CONTEXT_TEXT[c["context"]], lang()) +
                                       (f" ({', '.join(c['co_ligands'])})" if c["co_ligands"] else ""),
                            "status": pick(BIND_STATUS.get(c["status"], (c["status"],) * 4), lang())
                                      + ("" if c["md_complete"] else " · " + _("MD 未完成", "MD not finished", "MD 未完了", "MD 미완료")),
                            "runs": str(c["runs"] or "—"), "dg": dg})
            return out

        def refresh():
            new = rows()
            if new != tbl.rows:
                keep = {r["target"] for r in tbl.selected}
                tbl.rows = new
                tbl.selected = [r for r in new if r["target"] in keep]
                tbl.update()

        def busy() -> bool:
            job = RUNNER.get(wf)
            if job and job.alive():
                ui.notify(t("busy", lang()), type="warning")
                return True
            return False

        def add_targets():
            if busy():
                return
            try:
                r = ACT.add_binding_targets(wf, [x["target"] for x in tbl.selected], note=note.value or "")
            except ValueError as exc:
                ui.notify(str(exc), type="negative"); return
            if getattr(_start(wf), "blocked", False):
                return
            ui.notify(_(f"開始計算：{', '.join(r['added'])}。完成後報告會自動更新。",
                        f"Computing {', '.join(r['added'])}. The report is updated when it finishes.",
                        f"{', '.join(r['added'])} の計算を始めました。終わるとレポートが更新されます。",
                        f"{', '.join(r['added'])} 계산을 시작했습니다. 끝나면 보고서가 갱신됩니다."), type="positive")
            refresh()

        def one_more():
            if busy():
                return
            sel = [x["target"] for x in tbl.selected]
            if len(sel) != 1:
                ui.notify(_("請只選一個已完成的目標。", "Select exactly one finished target.", "完了した対象を 1 つだけ選んでください。",
                            "완료된 대상을 하나만 고르십시오."), type="warning"); return
            try:
                r = ACT.add_smd_run(wf, sel[0], note=note.value or "")
            except ValueError as exc:
                ui.notify(str(exc), type="negative"); return
            if getattr(_start(wf), "blocked", False):
                return
            ui.notify(_(f"{r['target']} 開始第 {r['runs']} 次 SMD。", f"Run {r['runs']} of {r['target']} started.",
                        f"{r['target']} の {r['runs']} 回目の SMD を始めました。", f"{r['target']}의 {r['runs']}번째 SMD를 시작했습니다."),
                      type="positive")
            refresh()

        async def rebuild():
            if busy():
                return
            try:
                # D-103: building the report (figures, embedded 3D) took long enough on the event loop to drop
                # the browser's connection; it now runs in a worker thread
                from nicegui import run as nrun
                await nrun.io_bound(ACT.refresh_report, wf, lang())
            except Exception as exc:  # noqa: BLE001
                ui.notify(f"{type(exc).__name__}: {exc}", type="negative"); return
            ui.notify(_("報告已重新整理。", "The report has been rebuilt.", "レポートを作り直しました。", "보고서를 다시 만들었습니다."),
                      type="positive")
            ui.navigate.to(f"/report/{project}/{name}?lang={lang()}", new_tab=True)
        with ui.row().classes("gap-2"):
            ui.button(_("計算選取的配體", "Compute the selected ligands", "選んだリガンドを計算", "선택한 리간드 계산"),
                      on_click=add_targets).props("color=primary no-caps data-testid=binding-add")
            ui.button(_("選取的配體再做一次 SMD", "One more SMD run for the selected ligand", "選んだリガンドの SMD をもう 1 回",
                        "선택한 리간드 SMD 한 번 더"), on_click=one_more).props("outline no-caps data-testid=binding-more")
            ui.button(_("重新整理報告", "Rebuild the report", "レポートを作り直す", "보고서 다시 만들기"),
                      on_click=rebuild).props("outline no-caps data-testid=report-rebuild")
        refresh()
        ui.timer(5.0, refresh)


class _Blocked:
    """What `_start` returns when no valid licence is installed (D-125): nothing was started.  It has the attributes the
    callers read from a job, so they carry on to the workflow page, where the licence card is shown."""
    blocked = True

    def __init__(self, wf: Workflow):
        self.wf = wf
        self.thread = None

    def alive(self) -> bool:
        return False


def _start(wf: Workflow):
    """D-103: the calculation runs in its own process (md20.gui.worker): it never holds the GUI's GIL, and its
    status and progress are files the GUI reads back after a reconnect or restart.  The worker probes the OpenMM
    platform and builds the pause policy itself (same settings as before: PAUSE file, battery, resource guard)."""
    (wf.project.dir / "PAUSE").unlink(missing_ok=True)
    os.environ["MD20_RESOURCE_MODE"] = resource_mode()
    from ..util.license import FeatureNotLicensed, LicenseRequired
    try:
        job = RUNNER.start_process(wf)
        STATE["feature_block"] = None
        return job
    except FeatureNotLicensed as exc:                # D-128: "your licence does not include X", shown on the feature card
        STATE["feature_block"] = exc.texts()
        ui.notify(pick(exc.texts(), lang()), type="negative", close_button=True, multi_line=True)
        return _Blocked(wf)
    except LicenseRequired:
        ui.notify(pick(LIC.BLOCKED_SHORT, lang()), type="negative", close_button=True)
        return _Blocked(wf)


def _gate_buttons(wf: Workflow, card: dict):
    """One-click decisions on a NEEDS_HUMAN card; options the program cannot carry out stay as text."""
    if card["status"] != "NEEDS_HUMAN" and not card.get("advisory"):
        return
    for a in card.get("actions", []):
        with ui.row().classes("items-center gap-2 w-full"):
            note = ui.input(option_text(a["text_hint"], lang())).classes("w-96") if a["needs_text"] else None

            def do(a=a, note=note):
                job = RUNNER.get(wf)
                if job and job.alive():
                    ui.notify(t("busy", lang()), type="warning"); return
                try:
                    out = apply_gate_action(wf, a, note.value if note else "")
                except (ValueError, KeyError) as exc:
                    ui.notify(str(exc), type="negative"); return
                lab, n, frm, btn = option_text(a["label"], lang()), len(out["invalidated"]), a["from_step"], t("run_continue", lang())
                ui.notify(_(f"已寫入設定：{lab}。會從 {frm} 重跑，共 {n} 個步驟。按「{btn}」執行。",
                            f"Saved to the settings: {lab}. The run restarts from {frm} ({n} steps). Press {btn} to run it.",
                            f"設定に書き込みました：{lab}。{frm} から再実行します（{n} ステップ）。「{btn}」を押して実行してください。",
                            f"설정에 저장했습니다: {lab}. {frm}부터 다시 실행합니다({n}단계). '{btn}'을 눌러 실행하십시오."), type="positive")
            ui.button(option_text(a["label"], lang()), on_click=do).props("outline color=primary no-caps")
    if card.get("manual"):
        ui.label(t("manual_hint", lang())).classes("text-xs text-gray-500")
        for o in card["manual"]:
            ui.label(f"• {option_text(o, lang())}").classes("text-sm text-gray-700")


async def _upload_payload(e) -> tuple[str, bytes]:
    """File name and bytes from a NiceGUI upload event (works with the 1.x/2.x and the 3.x event shapes)."""
    f = getattr(e, "file", None)
    if f is not None:
        data = f.read()
        if hasattr(data, "__await__"):
            data = await data
        return getattr(f, "name", "upload"), data
    content = getattr(e, "content", None)
    return getattr(e, "name", "upload"), (content.read() if content is not None else b"")


def _manual_upload_panel(wf: Workflow):
    """D-50: manual SDF upload with strict naming for compounds whose download failed or was blocked."""
    from ..docking.library import manual_upload_report, check_upload_name, MANUAL_DIR, NAMING_RULES
    from ..advisor import tx
    lib_dir = wf.dir / "screen" / "library"
    man = load_json(lib_dir / "library_manifest.json", {})
    names = sorted((man.get("entries") or {}).keys())
    if not names:
        return
    rep = manual_upload_report(names, lib_dir)
    failed = [n for n, r in (man.get("entries") or {}).items() if r.get("status") != "OK"]
    with ui.expansion(t("hts_manual", lang()),
                      value=bool(failed)).classes("w-full md20-card"):
        ui.label(tx(NAMING_RULES[0], lang())).classes("md20-why")
        if failed:
            ui.label(_("仍缺結構：", "Still missing: ", "構造がまだないもの：", "아직 구조가 없는 것: ") + ", ".join(f"{n}.sdf" for n in failed[:40])).classes("text-sm")
        if rep["bad_name"] or rep["unmatched"]:
            ui.label(_("未使用（檔名不符）：", "Not used (name does not match): ", "未使用（ファイル名が一致しません）：",
                       "사용하지 않음(파일 이름 불일치): ") + ", ".join(rep["bad_name"] + rep["unmatched"])).classes("text-sm text-negative")
        log = ui.column().classes("gap-0")

        async def got(e):
            fname, data = await _upload_payload(e)
            ok, why, save_as = check_upload_name(fname, names)
            with log:
                if not ok:
                    ui.label(f"{fname}{colon(lang())}{t('upload_rejected', lang())}{paren(tx(why, lang()), lang())}").classes("text-sm text-negative")
                    return
                d = lib_dir / MANUAL_DIR
                d.mkdir(parents=True, exist_ok=True)
                for old_f in d.glob("*"):               # one file per compound whatever its case on disk
                    if old_f.name.lower() == save_as.lower() and old_f.name != save_as:
                        old_f.replace(d / save_as)
                (d / save_as).write_bytes(data)
                ui.label(f"{fname}{colon(lang())}{t('upload_ok', lang())}").classes("text-sm text-positive")
            # the library step is re-run so the new file is picked up (downloaded files are cached, not re-fetched)
            st = wf.state()
            for k in ("screen_library", "screen_docking", "screen_selection"):
                st["steps"].pop(k, None)
            from ..util import atomic_write_json
            atomic_write_json(st, wf.state_path)
        ui.upload(on_upload=got, multiple=True, auto_upload=True, label=_("選擇 .sdf 檔", "Choose .sdf files", ".sdf ファイルを選ぶ", ".sdf 파일 선택")).props("accept=.sdf flat bordered color=primary").classes("w-full")


def _figure_gallery(wf: Workflow):
    """D-58: every figure of the project report, with its caption, reading guide and project-specific result."""
    from nicegui import run as nrun
    from ..report.workflow_report import build_workflow_report
    top = ui.row().classes("items-center gap-3")
    box = ui.column().classes("w-full gap-3")
    btn = _("產生或更新圖表", "Build or refresh figures", "図を作成または更新", "그림 만들기 또는 업데이트")
    with top:
        info = ui.label("").classes("text-sm md20-muted")

    def render():
        idx = load_json(wf.dir / "report_figures" / f"index_{lang()}.json", {})
        box.clear()
        figs = idx.get("figures") or []
        made = idx.get("created_at", "—")[:19]
        info.set_text(_(f"共 {len(figs)} 張圖，產生於 {made}", f"{len(figs)} figures, generated {made}",
                        f"図 {len(figs)} 枚、作成日時 {made}", f"그림 {len(figs)}개, 생성 시각 {made}")
                      if figs else _(f"還沒有圖表。流程有結果後，按「{btn}」。", f"No figures yet. Press {btn} once the workflow has results.",
                                     f"まだ図がありません。ワークフローに結果が出たら「{btn}」を押してください。",
                                     f"아직 그림이 없습니다. 워크플로에 결과가 나오면 '{btn}'를 누르십시오."))
        sec = None
        with box:
            for f in figs:
                if f.get("section") != sec:
                    sec = f.get("section")
                    ui.label(sec or "").classes("md20-section")
                with ui.card().classes("w-full md20-card p-3"):
                    ui.image(f"/file?path={f['path']}").classes("w-full max-w-3xl")
                    ui.label(f"{_('圖', 'Figure', '図', '그림')} {f['n']}. {f['title']}" + (paren(f["subject"], lang()) if f.get("subject") else "")).classes("font-semibold text-sm")
                    ui.label(f["caption"]).classes("md20-why")
                    ui.label(_("怎麼看：", "How to read it: ", "読み方：", "읽는 법: ") + f["read"]).classes("text-sm")
                    for x in f.get("findings") or []:
                        ui.label(("⚠ " if x["level"] == "caution" else "• ") + x["text"]).classes(
                            "text-sm " + ("text-negative" if x["level"] == "caution" else ""))

    async def rebuild():
        info.set_text(_("產生中…", "Building…", "作成中…", "만드는 중…"))
        try:
            await nrun.io_bound(build_workflow_report, wf, wf.dir / f"workflow_report_{lang()}.html", lang=lang())
        except Exception as exc:  # noqa: BLE001
            ui.notify(f"{type(exc).__name__}: {exc}", type="negative")
        render()
    with top:
        ui.button(btn, on_click=rebuild).props("outline no-caps")
    render()


@ui.page("/wf/{project}/{name}")
def workflow_page(project: str, name: str):
    _header()
    if safe_name(project) != project or safe_name(name) != name or not (Path(STATE["projects_dir"]) / project / "project.json").is_file():
        ui.label(_("找不到這個專案或流程。", "Project or workflow not found.", "このプロジェクトまたはワークフローが見つかりません。",
                   "이 프로젝트 또는 워크플로를 찾을 수 없습니다.")).classes("text-negative"); return
    proj = Project(Path(STATE["projects_dir"]) / project)
    try:
        wf = Workflow.open(proj, name)          # never creates an empty workflow for a mistyped URL
    except FileNotFoundError:
        ui.label(_(f"找不到流程 {name}。", f"Workflow {name} not found.", f"ワークフロー {name} が見つかりません。",
                   f"워크플로 {name}을(를) 찾을 수 없습니다.")).classes("text-negative"); return
    L = lang()
    run_btn = t("run_continue", L)
    with ui.column().classes("w-full max-w-6xl mx-auto gap-3"):
        ui.label(f"{project} / {name}").classes("text-xl font-semibold")
        status = ui.label("").classes("text-lg")
        msg = ui.markdown("")
        rep_box = ui.column().classes("w-full")
        rep_sig = {"v": None}

        def _bench():
            return getattr(STATE.get("doctor"), "benchmark", None) or None

        def render_replicas(force: bool = False):
            """D-131: the replica plan before a start, with one-click choices (no dialog).  Shown while the MD is not
            finished with all the replicas the settings ask for."""
            card = replica_card(wf, lang=lang(), benchmark=_bench())
            job = RUNNER.get(wf)
            busy = bool(job and job.alive())
            sig = (lang(), card["show"], card["current"], tuple(card["lines"]), busy, tuple(o["label"] for o in card["options"]))
            if sig == rep_sig["v"] and not force:
                return
            rep_sig["v"] = sig
            rep_box.clear()
            if not card["show"]:
                return

            def choose(n):
                j = RUNNER.get(wf)
                if j and j.alive():
                    ui.notify(t("busy", lang()), type="warning"); return
                try:
                    out = ACT.set_replicas(wf, int(n))
                except (ValueError, TypeError) as exc:
                    ui.notify(str(exc), type="negative"); return
                k, nn = out["topup_runs"], out["replicas"]
                ui.notify(_(f"已設定每個系統 {nn} 條重複" + (f"，會補跑缺的 {k} 條，已有的不重算" if k else "") + f"。按「{run_btn}」執行。",
                            f"Set to {nn} replicas per system" + (f". The {k} missing one(s) will run and nothing is recomputed" if k else "") +
                            f". Press {run_btn} to run.",
                            f"系ごとに {nn} 回に設定しました" + (f"。不足の {k} 回を追加で計算し、既存の結果は再計算しません" if k else "") +
                            f"。「{run_btn}」を押して実行してください。",
                            f"계마다 {nn}회로 설정했습니다" + (f". 부족한 {k}회를 추가로 실행하며 이미 있는 것은 다시 계산하지 않습니다" if k else "") +
                            f". '{run_btn}'을 눌러 실행하십시오."), type="positive")
                render_replicas(force=True)
            color = "c98a1a" if card["level"] == "warning" else "2f6f9f"
            with rep_box, ui.card().classes("w-full md20-card").style(f"border-left: 4px solid #{color}").props("data-testid=replica-card"):
                ui.label(card["title"]).classes("md20-section")
                for line in card["lines"]:
                    ui.label(line).classes("text-sm")
                for o in card["options"]:
                    if o["id"] == "custom":
                        continue
                    with ui.row().classes("items-center gap-2 no-wrap"):
                        b = ui.button(o["label"], on_click=lambda n=o["replicas"]: choose(n)).props(
                            f"{'color=primary' if o['replicas'] != card['current'] or o['id'] == 'topup' else 'outline'} no-caps "
                            f"data-testid=replica-{o['id']}" + (" disable" if busy else ""))
                        ui.label(o["note"]).classes("md20-why")
                with ui.row().classes("items-center gap-2"):
                    num = ui.number(next((o["label"] for o in card["options"] if o["id"] == "custom"), ""), value=card["current"],
                                    min=1, max=ACT.MAX_REPLICAS, step=1, format="%d").classes("w-40")
                    ui.button(_("套用", "Apply", "適用", "적용"), on_click=lambda: choose(num.value)).props(
                        "outline no-caps data-testid=replica-custom" + (" disable" if busy else ""))

        confirm_box = ui.column().classes("w-full")
        confirm_sig = {"v": None}

        def render_confirm():
            stp = wf.state()["steps"].get("md_confirm") or {}
            sig = (stp.get("status"), stp.get("at"))
            if sig == confirm_sig["v"]:
                return
            confirm_sig["v"] = sig
            confirm_box.clear()
            if stp.get("status") != "NEEDS_HUMAN":
                return
            card = next((c for c in gate_cards(wf, lang=lang()) if c["title"] == "confirm MD"), None)
            go = next((a for a in (card or {}).get("actions", []) if a["label"].startswith("進入分子動力學")), None)
            with confirm_box, ui.card().classes("w-full md20-card md20-notice md20-notice--info"):
                ui.label(t("confirm_md_title", lang())).classes("md20-section")
                ui.label(_(stp.get("message", ""),
                           "Docking and pose selection are complete. Check the selected poses in the pose table, then decide "
                           "whether to continue to molecular dynamics. This covers building, equilibration and production, "
                           "and can take hours depending on the settings.",
                           "分子ドッキングとポーズ選択が終わりました。ポーズ表で選ばれたポーズを確認し、分子動力学に進むかどうか決めてください。"
                           "系の構築、平衡化、本計算を行い、設定によっては数時間かかります。",
                           "분자 도킹과 포즈 선택이 끝났습니다. 포즈 표에서 선택된 포즈를 확인한 뒤 분자동역학으로 진행할지 결정하십시오. "
                           "계 구축, 평형화, 본 계산을 하며 설정에 따라 몇 시간 걸릴 수 있습니다.")).classes("text-sm")
                from .advanced import selection_lines
                sel = (wf.state()["steps"].get("pose_selection") or {}).get("selection") or {}
                for line in selection_lines(sel, lang()):
                    ui.label("• " + line).classes("text-sm")
                for line in replica_card(wf, lang=lang(), benchmark=_bench())["lines"][:1]:      # D-131: said before the start
                    ui.label(line).classes("text-sm")

                def proceed():
                    job = RUNNER.get(wf)
                    if job and job.alive():
                        ui.notify(t("busy", lang()), type="warning"); return
                    if go:
                        apply_gate_action(wf, go)
                    if getattr(_start(wf), "blocked", False):
                        return
                    ui.notify(_("已確認，開始分子動力學。", "Confirmed. Molecular dynamics is starting.",
                                "確認しました。分子動力学を始めます。", "확인했습니다. 분자동역학을 시작합니다."), type="positive")
                go_btn = _("進入分子動力學", "Proceed to molecular dynamics", "分子動力学に進む", "분자동역학으로 진행")
                with ui.row().classes("gap-2"):
                    ui.button(go_btn, on_click=proceed).props("color=primary no-caps")
                    ui.button(_("先改選姿勢", "Choose another pose first", "先に別のポーズを選ぶ", "먼저 다른 포즈 선택"),
                              on_click=lambda: ui.notify(_(f"在下方姿勢表點選要使用的姿勢，再按「{go_btn}」。",
                                                           f"Click the pose to use in the table below, then press {go_btn}.",
                                                           f"下のポーズ表で使うポーズをクリックしてから「{go_btn}」を押してください。",
                                                           f"아래 포즈 표에서 사용할 포즈를 클릭한 뒤 '{go_btn}'을 누르십시오."))
                              ).props("outline no-caps")
        with ui.row():
            ui.button(run_btn, on_click=lambda: _start(wf))
            ui.button(t("pause", L), on_click=lambda: (wf.project.dir / "PAUSE").touch()).props("outline")
            report_btn = ui.button(t("open_report", L),
                                   on_click=lambda: ui.navigate.to(f"/report/{project}/{name}?lang={lang()}", new_tab=True)).props("outline")
        _binding_panel(wf, project, name)
        # D-153: the pipeline skeleton in four phases, top-to-bottom = first-to-last (views.phase_rows)
        steps = ui.column().classes("w-full md20-card gap-0").style("padding:14px 18px")
        ui.label(t("poses", L)).classes("font-semibold")
        poses = ui.table(columns=[{"name": k, "label": l, "field": k, "align": "left"} for k, l in
                                  (("entry", _("配體", "Ligand", "リガンド", "리간드")), ("rank", _("名次", "Rank", "順位", "순위")),
                                   ("score", _("分數（kcal mol⁻¹）", "Score (kcal mol⁻¹)", "スコア（kcal mol⁻¹）", "점수(kcal mol⁻¹)")),
                                   ("cluster", _("叢集（大小）", "Cluster (size)", "クラスター（サイズ）", "클러스터(크기)")),
                                   ("contacts", _("接觸殘基數", "Contacts", "接触残基数", "접촉 잔기 수")),
                                   ("rmsd_ref", _("與晶體的 RMSD（Å）", "RMSD to crystal (Å)", "結晶との RMSD（Å）", "결정 대비 RMSD(Å)")),
                                   ("md_screen", _("短模擬篩選", "Short-MD screen", "短い MD による選別", "짧은 MD 선별")),
                                   ("tag", ""))], rows=[], row_key="key").props("dense flat").props(no_data()).classes("w-full md20-card")
        reason = ui.markdown("")

        def pick_pose(e):
            row = e.args[1]
            if isinstance(row.get("score"), str):          # placed from a predicted complex: there is no other pose to pick
                return
            job = RUNNER.get(wf)
            if job and job.alive():
                ui.notify(_("流程正在執行。請先暫停再改選姿勢，否則會和背景執行的流程互相覆寫狀態。",
                            "The workflow is running. Pause it before you change the pose, or the two would overwrite each other's state.",
                            "ワークフローは実行中です。ポーズを変える前に一時停止してください。そうしないと実行中の処理と状態を上書きし合います。",
                            "워크플로가 실행 중입니다. 포즈를 바꾸기 전에 일시 정지하십시오. 그렇지 않으면 실행 중인 작업과 상태를 서로 덮어씁니다."),
                          type="warning"); return
            set_pose_choice(wf, row["entry"], row["rank"])
            ent, rk = row["entry"], row["rank"]
            ui.notify(_(f"{ent} 改用第 {rk} 名姿勢。按「{run_btn}」重跑後面的步驟。",
                        f"{ent} now uses pose {rk}. Press {run_btn} to rerun the later steps.",
                        f"{ent} は {rk} 位のポーズに変えました。「{run_btn}」を押すと後のステップを再実行します。",
                        f"{ent}은(는) 이제 {rk}위 포즈를 사용합니다. '{run_btn}'을 누르면 이후 단계를 다시 실행합니다."))
        poses.on("rowClick", pick_pose)
        # ---- WP13: gate cards / live curves / timeline / offline 3D -------------------------------------
        with ui.tabs().classes("w-full") as tabs:
            t_gate, t_screen, t_live, t_umb, t_time, t_3d = (ui.tab(t("gates", L)), ui.tab(t("screening", L)), ui.tab(t("live", L)),
                                                             ui.tab(t("umbrella", L)), ui.tab(t("timeline", L)), ui.tab(t("viewer", L)))
            t_fig = ui.tab(_("圖表", "Figures", "図", "그림"))
        with ui.tab_panels(tabs, value=t_gate).classes("w-full"):
            with ui.tab_panel(t_gate):
                cards_box = ui.column().classes("w-full gap-2")
            with ui.tab_panel(t_screen):
                ui.label(_("高通量篩選用的是縮減搜尋的 Vina 分數，只拿來剔除化合物。勾選要進入下一步的化合物，或直接點排名圖的長條。"
                           "標 ≈ 的化合物和第 1 名差不到 1 kcal/mol，在 Vina 的誤差內，名次沒有統計意義。",
                           "The high-throughput screen uses reduced-search Vina scores, only to discard compounds. Tick the compounds "
                           "to take forward, or click a bar in the ranking chart. Compounds marked ≈ are less than 1 kcal/mol from "
                           "the best one. That gap is within Vina's error, so their order is not meaningful.",
                           "ハイスループットスクリーニングは探索を縮小した Vina スコアを使い、化合物を除くためだけに用います。次に進める化合物にチェックを入れるか、"
                           "順位グラフの棒をクリックしてください。≈ の付いた化合物は 1 位との差が 1 kcal/mol 未満です。Vina の誤差の範囲内なので、順位に意味はありません。",
                           "고처리량 스크리닝은 탐색을 줄인 Vina 점수를 사용하며 화합물을 걸러 내는 데만 씁니다. 다음 단계로 보낼 화합물을 선택하거나 "
                           "순위 그래프의 막대를 클릭하십시오. ≈ 표시가 있는 화합물은 1위와의 차이가 1 kcal/mol 미만입니다. Vina 오차 범위 안이므로 "
                           "순위에 의미가 없습니다.")).classes("text-sm")
                scr_info = ui.label("").classes("text-sm")
                ch_rank = ui.echart(echart_ranking([], lang=lang())).classes("w-full h-96")
                ch_scr = ui.echart(echart_screen([])).classes("w-full h-80")
                scr_tbl = ui.table(columns=[{"name": k, "label": l, "field": k, "sortable": True} for k, l in
                                            (("rank", _("名次", "Rank", "順位", "순위")), ("name", _("化合物", "Compound", "化合物", "화합물")),
                                             ("score", _("分數", "Score", "スコア", "점수")),
                                             ("delta_to_best", _("與最佳差距", "Δ to best", "1 位との差", "1위와의 차이")),
                                             ("heavy_atoms", _("重原子數", "Heavy atoms", "重原子数", "중원자 수")), ("ligand_efficiency", "LE"),
                                             ("cluster_size", _("叢集大小", "Cluster size", "クラスターサイズ", "클러스터 크기")),
                                             ("contacts", _("接觸殘基數", "Contacts", "接触残基数", "접촉 잔기 수")),
                                             ("recommendation_status", _("推薦", "Recommendation", "推奨", "추천")), ("tag", ""))],
                                   rows=[], row_key="key", selection="multiple", pagination=25).props(no_data()).classes("w-full")


                def bar_click(e):
                    data = getattr(e, "data", None)
                    nm = getattr(e, "name", None) or (data.get("name") if isinstance(data, dict) else None)
                    nm = str(nm or "").split("：")[0]
                    row = next((r for r in scr_tbl.rows if r.get("name") == nm), None)
                    if not row:
                        return
                    sel = [r for r in scr_tbl.selected if r.get("key") != row.get("key")]
                    if len(sel) == len(scr_tbl.selected):
                        sel.append(row)
                    scr_tbl.selected = sel
                    scr_tbl.update()
                    ui.notify(_(f"已選 {len(sel)} 個化合物", f"{len(sel)} compounds selected", f"{len(sel)} 個の化合物を選択中",
                                f"화합물 {len(sel)}개 선택됨"))
                try:
                    ch_rank.on_point_click(bar_click)
                    ch_scr.on_point_click(bar_click)
                except AttributeError:      # older NiceGUI without point-click events: the table selection still works
                    pass
                with ui.row().classes("items-end gap-2"):
                    scr_note = ui.input(option_text("備註（為什麼選這些）", L)).classes("w-72")

                    def do_select(mode: str):
                        job = RUNNER.get(wf)
                        if job and job.alive():
                            ui.notify(t("busy", L), type="warning"); return
                        names = [r["name"] for r in scr_tbl.selected]
                        try:
                            out = select_screen_ligands(wf, names, mode, note=scr_note.value or "")
                        except ValueError as exc:
                            ui.notify(str(exc), type="negative"); return
                        n = len(out["selected"])
                        ui.notify(_(f"已選 {n} 個化合物（{mode}）。按「{run_btn}」進入正式對接與分子動力學。",
                                    f"{n} compounds selected ({mode}). Press {run_btn} to go on to full docking and molecular dynamics.",
                                    f"{n} 個の化合物を選びました（{mode}）。「{run_btn}」を押すと本格的なドッキングと分子動力学に進みます。",
                                    f"화합물 {n}개를 선택했습니다({mode}). '{run_btn}'을 누르면 정식 도킹과 분자동역학으로 넘어갑니다."),
                                  type="positive")
                    ui.button(_("各自對接後進入模擬", "Dock each, then simulate", "個別にドッキングしてからシミュレーション",
                                "각각 도킹한 뒤 시뮬레이션"), on_click=lambda: do_select("independent")).props("color=primary")
                    ui.button(_("多配體同時對接後進入模擬", "Dock together, then simulate", "まとめてドッキングしてからシミュレーション",
                                "함께 도킹한 뒤 시뮬레이션"), on_click=lambda: do_select("simultaneous")).props("outline")
                _manual_upload_panel(wf)
            with ui.tab_panel(t_live):
                prog = ui.label("").classes("text-sm")
                bar = ui.linear_progress(value=0, show_value=False).classes("w-full")
                with ui.row().classes("w-full"):
                    step_ax = _("步", "step", "ステップ", "스텝")
                    ch_t = ui.echart(echart_options([], title=_("溫度", "Temperature", "温度", "온도"), x=step_ax, y="K")).classes("w-[48%] h-60")
                    ch_e = ui.echart(echart_options([], title=_("位能", "Potential energy", "ポテンシャルエネルギー", "퍼텐셜 에너지"),
                                                    x=step_ax, y="kJ mol⁻¹")).classes("w-[48%] h-60")
                with ui.row().classes("w-full"):
                    ch_f = ui.echart(echart_options([], title=_("SMD 拉力", "SMD force", "SMD の引っ張り力", "SMD 당김 힘"),
                                                    x="r (nm)", y="kJ mol⁻¹ nm⁻¹")).classes("w-[48%] h-60")
                    ch_w = ui.echart(echart_options([], title=_("SMD 功", "SMD work", "SMD の仕事", "SMD 일"),
                                                    x="r (nm)", y="kJ mol⁻¹")).classes("w-[48%] h-60")
            with ui.tab_panel(t_umb):
                add_btn = _("補採樣", "Add windows", "ウィンドウを追加", "윈도우 추가")
                ui.label(_("細線是每個窗口的取樣分佈，面積是合併後的樣本。紅色是斷點，那裡的 PMF 不可信。"
                           f"程式會自動從大缺口補到小缺口。如果你看到還想補的區間，輸入範圍後按「{add_btn}」。",
                           "Thin lines show the sampling of each window and the filled area shows all samples together. Red marks "
                           "a gap, where the PMF cannot be trusted. Gaps are filled automatically, largest first. To fill a range "
                           f"yourself, enter it and press {add_btn}.",
                           "細い線は各ウィンドウのサンプリング分布、塗りつぶしはまとめたサンプルです。赤は途切れた部分で、そこの PMF は信頼できません。"
                           f"大きな隙間から順に自動で補います。自分で補いたい範囲があれば、範囲を入力して「{add_btn}」を押してください。",
                           "가는 선은 윈도우별 샘플링 분포이고 채워진 면적은 합친 샘플입니다. 빨간색은 끊긴 구간이며 그곳의 PMF는 믿을 수 없습니다. "
                           f"큰 틈부터 자동으로 채웁니다. 직접 채우고 싶은 구간이 있으면 범위를 입력하고 '{add_btn}'를 누르십시오.")).classes("text-sm")
                cov_pick = ui.select({}, label=_("結合目標", "Binding target", "結合の対象", "결합 대상")).classes("w-96")
                cov_info = ui.label("").classes("text-sm")
                ch_cov = ui.echart(coverage_chart({}, lang=L)).classes("w-full h-80")
                with ui.row().classes("items-end gap-2"):
                    rs_lo = ui.number(_("從（nm）", "From (nm)", "開始（nm）", "시작(nm)"), step=0.01, format="%.3f").classes("w-32")
                    rs_hi = ui.number(_("到（nm）", "To (nm)", "終了（nm）", "끝(nm)"), step=0.01, format="%.3f").classes("w-32")
                    rs_k = ui.number(_("k（選填，kJ/mol/nm²）", "k (optional, kJ/mol/nm²)", "k（任意、kJ/mol/nm²）", "k(선택, kJ/mol/nm²)"),
                                     step=100).classes("w-48")
                    rs_note = ui.input(_("備註（為什麼補這段）", "Note (why this range)", "メモ（この範囲を補う理由）",
                                         "메모(이 구간을 채우는 이유)")).classes("w-72")

                    def do_resample():
                        job = RUNNER.get(wf)
                        if job and job.alive():
                            ui.notify(t("busy", L), type="warning"); return
                        if not cov_pick.value or rs_lo.value is None or rs_hi.value is None:
                            ui.notify(_("請選擇結合目標並輸入範圍。", "Choose a binding target and enter a range.",
                                        "結合の対象を選び、範囲を入力してください。", "결합 대상을 고르고 범위를 입력하십시오."),
                                      type="warning"); return
                        target = cov_pick.value.split("|")[0]
                        try:
                            out = resample_range(wf, target, float(rs_lo.value), float(rs_hi.value),
                                                 k=float(rs_k.value) if rs_k.value else None, note=rs_note.value or "")
                        except ValueError as exc:
                            ui.notify(str(exc), type="negative"); return
                        n, kk, sp = len(out["windows"]), f"{out['k']:.0f}", f"{out['spacing_nm']:.3f}"
                        ui.notify(_(f"{target}：這個區間新增 {n} 個窗口（k {kk}，間距 {sp} nm）。按「{run_btn}」執行，已完成的窗口不會重跑。",
                                    f"{target}: {n} windows added in this range (k {kk}, spacing {sp} nm). Press {run_btn} to run them. "
                                    "Finished windows are not run again.",
                                    f"{target}：この範囲にウィンドウを {n} 個追加しました（k {kk}、間隔 {sp} nm）。「{run_btn}」を押して実行してください。"
                                    "完了したウィンドウは再実行しません。",
                                    f"{target}: 이 구간에 윈도우 {n}개를 추가했습니다(k {kk}, 간격 {sp} nm). '{run_btn}'을 눌러 실행하십시오. "
                                    "끝난 윈도우는 다시 실행하지 않습니다."), type="positive")
                    ui.button(add_btn, on_click=do_resample).props("color=primary")
            with ui.tab_panel(t_fig):
                _figure_gallery(wf)
            with ui.tab_panel(t_time):
                time_box = ui.column().classes("w-full gap-1")
            with ui.tab_panel(t_3d):
                # D-104: the list is refreshed every few seconds, so a membrane build shows up while it runs
                # ("live" target first) and the view redraws after each build step
                empty3d = ui.label(_("建模完成後就能看 3D 結構，正式模擬完成後可以播放軌跡。建膜時會即時顯示每一步。",
                                     "The 3D structure appears after building. The trajectory can be played after production. "
                                     "A membrane build is shown live, step by step.",
                                     "系の構築が終わると 3D 構造を表示できます。本計算が終わるとトラジェクトリを再生できます。膜の構築中は各段階をライブで表示します。",
                                     "계 구축이 끝나면 3D 구조를 볼 수 있습니다. 본 계산이 끝나면 궤적을 재생할 수 있습니다. 막 구축 중에는 각 단계를 실시간으로 보여 줍니다.")
                                   ).classes("text-gray-500")
                pick3d = ui.select({}, label=_("結構", "Structure", "構造", "구조")).classes("w-96")
                # D-94: a real <iframe> element.  ui.html() sanitises with DOMPurify since NiceGUI 3.0 and
                # dropped the iframe, so the 3D tab was empty (laptop 11/07).
                frame = ui.element("iframe").style("width:100%;height:560px;border:0").props('data-testid="viewer-frame"')
                v3 = {"targets": [], "src": None, "user": False, "busy": False}

                def show3d():
                    tg = v3["targets"]
                    if pick3d.value is None or not 0 <= int(pick3d.value) < len(tg):
                        return
                    t3 = tg[int(pick3d.value)]
                    src = f"/viewer?project={project}&name={name}&i={pick3d.value}" + (f"&t={t3.get('stamp')}" if t3["mode"] == "live" else "")
                    if src != v3["src"]:
                        v3["src"] = src
                        frame._props["src"] = src
                        frame.update()

                def refresh3d():
                    tg = viewer_targets(wf, lang=lang())
                    old = v3["targets"]
                    prev = old[int(pick3d.value)] if pick3d.value is not None and 0 <= int(pick3d.value) < len(old) else None
                    v3["targets"] = tg
                    opts = {i: t3["label"] for i, t3 in enumerate(tg)}
                    sel = None
                    if prev is not None:
                        sel = next((i for i, t3 in enumerate(tg) if (t3["mode"], t3["key"]) == (prev["mode"], prev["key"])), None)
                    if not v3["user"] and tg and tg[0]["mode"] == "live":
                        sel = 0                    # follow the build unless the student picked a structure themselves
                    if sel is None and tg:
                        sel = 0
                    if opts != pick3d.options or sel != pick3d.value:
                        v3["busy"] = True          # a programmatic change is not the student's choice
                        try:
                            pick3d.set_options(opts, value=sel)
                        finally:
                            v3["busy"] = False
                    empty3d.set_visibility(not tg)
                    pick3d.set_visibility(bool(tg))
                    frame.set_visibility(bool(tg))
                    show3d()
                def picked(_):
                    if not v3["busy"]:
                        v3["user"] = True
                    show3d()
                pick3d.on_value_change(picked)
                refresh3d()
                ui.timer(3.0, refresh3d)
        cards_sig = {"v": None}
        scr_sig = {"v": None}
        cov_sig = {"v": None}
        time_sig = {"v": None}
        step_sig = {"v": None}

        def refresh():
            job = RUNNER.get(wf)
            snap = job.snapshot() if job else {"status": "IDLE", "message": "", "steps": __import__("md20.gui.logic", fromlist=["step_rows"]).step_rows(wf.state()), "history": []}
            L = lang()
            status.set_text(t("status", L) + colon(L) + pick(STATUS_TEXT.get(str(snap["status"]), str(snap["status"])), L))
            render_replicas()
            render_confirm()
            m = pick(snap["message"], L)                  # the runner's own messages are (zh, en, ja, ko) tuples
            msg.set_content(f"```\n{m}\n```" if m else "")
            prows = phase_rows(wf, lang=L)
            psig = [(r["kind"], r.get("key"), r.get("state"), r["label"]) for r in prows]
            if psig != step_sig["v"]:
                step_sig["v"] = psig
                steps.clear()
                with steps:
                    for r in prows:
                        if r["kind"] == "phase":
                            ui.label(r["label"]).classes("md20-section").style("margin:12px 0 4px")
                        else:
                            mod, glyph = theme.gate_state(r["state"] if r["state"] in STATUS_TEXT else None)
                            faint = r["state"] in ("not_started", "not_used")
                            sl = r["status_label"] or pick(STATUS_TEXT.get(r["state"], r["state"]), L)
                            with ui.row().classes("items-center gap-2 w-full").style("padding:3px 0 3px 10px"
                                                  + ("; opacity:.5" if faint else "")):
                                ui.html(f'<span class="md20-glyph" aria-hidden="true">{"○" if faint else glyph}</span>')
                                ui.label(r["label"]).classes("text-sm").style("min-width:220px")
                                ui.label(sl).classes("text-xs text-gray-500")
                                if r["at"]:
                                    ui.label(r["at"]).classes("text-xs text-gray-500")
            rows = pose_table(wf, L)
            for r in rows:
                r["key"] = f"{r['entry']}-{r['rank']}"
                r["tag"] = ("★" if r["recommended"] else "") + ("✔" if r["chosen"] else "") + \
                    (_("⚠碰撞", "⚠clash", "⚠衝突", "⚠충돌") if r["clash"] else "")
            poses.rows = rows
            why = _("推薦理由", "why recommended", "推奨の理由", "추천 이유")
            reason.set_content("\n\n".join(f"**{r['entry']} {why}{colon(L).rstrip()}** {r['reason']}" for r in rows if r["reason"]))
            ls = live_series(snap["history"])
            for ch, k in ((ch_t, "temperature"), (ch_e, "potential"), (ch_f, "smd_force"), (ch_w, "smd_work")):
                ch.options["series"][0]["data"] = ls[k]
                ch.update()
            pg = ls["progress"]
            if pg:
                eta = ""
                if pg.get("eta_s") is not None:
                    m = int(pg["eta_s"] // 60)
                    h, mm = m // 60, m % 60
                    eta = (_(f"，這個階段約剩 {h} 小時 {mm} 分", f", about {h} h {mm} min left in this stage",
                             f"、この段階の残り約 {h} 時間 {mm} 分", f", 이 단계 남은 시간 약 {h}시간 {mm}분") if m >= 60 else
                           _(f"，這個階段約剩 {m} 分", f", about {m} min left in this stage",
                             f"、この段階の残り約 {m} 分", f", 이 단계 남은 시간 약 {m}분"))
                    if pg.get("ns_per_day"):
                        nsd = pg["ns_per_day"]
                        eta += paren(_(f"本機每天 {nsd} ns", f"{nsd} ns per day here", f"このパソコンで 1 日 {nsd} ns",
                                       f"이 컴퓨터에서 하루 {nsd} ns"), L)
                umb = ""
                if ls.get("umbrella"):
                    w, nw = ls["umbrella"]["window"], ls["umbrella"]["n"]
                    umb = paren(_(f"傘狀採樣窗口 {w}，共 {nw} 個", f"umbrella window {w} of {nw}",
                                  f"アンブレラサンプリング {nw} ウィンドウ中 {w} 番目", f"엄브렐라 샘플링 윈도우 {nw}개 중 {w}번째"), L)
                    al = ls["umbrella"].get("alerts") or []
                    if al:                                   # D-101: a gap is news now, not after the round
                        rng = "、".join(f"{a['lo']:.2f}–{a['hi']:.2f}" for a in al[:3])
                        umb += _(f" ⚠ {rng} nm 取樣不連續，見「傘狀採樣覆蓋」分頁", f" ⚠ gap at {rng} nm, see the coverage tab",
                                 f" ⚠ {rng} nm で途切れ。カバー範囲タブを参照", f" ⚠ {rng} nm 끊김, 커버리지 탭 참조")
                prog.set_text(f"{pg['stage']}{colon(L)}{pg['pct']}%" + eta + umb)
                bar.set_value((pg["pct"] or 0) / 100.0)
            tg = coverage_targets(wf, lang=L)
            opts = {f"{t['target']}|{t['dir']}": t["label"] for t in tg}
            if opts != cov_pick.options:
                cov_pick.set_options(opts, value=cov_pick.value if cov_pick.value in opts else (next(iter(opts), None)))
            if cov_pick.value:
                cov = load_json(Path(cov_pick.value.split("|", 1)[1]) / "coverage.json", {})
                if cov.get("updated_at") != cov_sig["v"]:
                    cov_sig["v"] = cov.get("updated_at")
                    ch_cov.options.clear(); ch_cov.options.update(coverage_chart(cov, lang=L)); ch_cov.update()
                    cov_info.set_text(coverage_summary(cov, lang=L))
            srows = screen_table(wf)
            if len(srows) != scr_sig["v"]:
                scr_sig["v"] = len(srows)
                scr_tbl.rows = srows
                ch_scr.options.clear(); ch_scr.options.update(echart_screen(srows)); ch_scr.update()
                ch_rank.options.clear(); ch_rank.options.update(echart_ranking(srows, lang=lang())); ch_rank.update()
                sd = wf.state()["steps"].get("screen_docking") or {}
                nf = len(sd.get("failed") or [])
                scr_info.set_text(_(f"{len(srows)} 個化合物有分數，{nf} 個失敗或略過。細節在閘門與報告。",
                                    f"{len(srows)} compounds have scores and {nf} failed or were skipped. See the gates and the report.",
                                    f"{len(srows)} 個の化合物にスコアがあり、{nf} 個は失敗または省略されました。詳しくはゲートとレポートを見てください。",
                                    f"화합물 {len(srows)}개에 점수가 있고 {nf}개는 실패하거나 건너뛰었습니다. 자세한 내용은 게이트와 보고서를 보십시오.")
                                  if srows else
                                  _("還沒有篩選結果。在 config 的 screen.library 指定化合物庫後再執行。",
                                    "No screening results yet. Set the compound library in screen.library of the config, then run.",
                                    "スクリーニングの結果はまだありません。config の screen.library で化合物ライブラリを指定してから実行してください。",
                                    "아직 스크리닝 결과가 없습니다. config의 screen.library에 화합물 라이브러리를 지정한 뒤 실행하십시오."))
            cards = gate_cards(wf, lang=L)
            if cards != cards_sig["v"]:
                cards_sig["v"] = cards
                cards_box.clear()
                with cards_box:
                    if not cards:
                        ui.label(t("no_gates", L)).classes("text-gray-500")
                    for c in cards:
                        mod, glyph = theme.gate_state(c.get("status"), bool(c.get("advisory")))
                        with ui.card().classes(f"w-full md20-gate md20-gate--{mod}").props(f"data-gate-state={mod}"):
                            with ui.row().classes("items-center gap-2"):
                                ui.html(f'<span class="md20-glyph" aria-hidden="true">{glyph}</span>')
                                ui.badge(card_badge(c, L), color="blue-grey-6" if c.get("advisory") else c["color"])
                                ui.label(f"{card_source(c['source'], L)} · {gate_title(c['title'], L)}").classes("font-semibold")
                            general = gate_general(c["title"], L)
                            if L != "zh" and general:
                                # D-55: the general explanation in this language; the recorded detail (Chinese, with this run's numbers) below
                                ui.label(general).classes("text-sm")
                                if c["explanation"]:
                                    with ui.expansion(_("細節（以中文記錄）", "Details (recorded in Chinese)", "詳細（中国語で記録）",
                                                        "상세 내용(중국어로 기록됨)")).classes("w-full text-xs"):
                                        ui.label(c["explanation"]).classes("text-xs whitespace-pre-wrap")
                            else:
                                ui.label(c["explanation"]).classes("text-sm whitespace-pre-wrap")
                            if c["status"] != "NEEDS_HUMAN" and not c.get("advisory"):
                                for o in c["options"]:
                                    ui.label(f"• {option_text(o, L)}").classes("text-sm text-primary")
                            _gate_buttons(wf, c)
            tl = timeline(wf, limit=120, lang=L)
            if len(tl) != time_sig["v"]:
                time_sig["v"] = len(tl)
                time_box.clear()
                with time_box:
                    for e in reversed(tl):
                        with ui.row().classes("w-full items-start gap-2"):
                            ui.label(to_local(e["at"], "%H:%M:%S")).classes("text-xs text-gray-500 w-16")
                            ui.badge(_("人工", "Manual", "手動", "수동") if e["status"] == "human" else
                                     (t("step", L) if e["kind"] == "step" else _("自動", "Automatic", "自動", "자동")),
                                     color="negative" if e["status"] in ("human", "NEEDS_HUMAN") else
                                     ("primary" if e["kind"] == "step" else "grey"))
                            with ui.column().classes("gap-0"):
                                ui.label(e["title"]).classes("text-sm font-semibold")
                                if e["text"]:
                                    ui.label(e["text"]).classes("text-xs whitespace-pre-wrap")
            report_btn.set_visibility(bool(wf.state()["steps"].get("docking") or wf.state()["steps"].get("md_cases")))
        ui.timer(2.0, refresh)
        refresh()


@app.get("/viewer")
def serve_viewer(project: str, name: str, i: int = 0):
    """Offline 3D viewer page (inline JS, no CDN) for one case of a workflow."""
    from fastapi.responses import HTMLResponse
    if safe_name(project) != project or safe_name(name) != name:
        return HTMLResponse("not allowed", status_code=403)
    proj = Project(Path(STATE["projects_dir"]) / project)
    try:
        wf = Workflow.open(proj, name)
    except FileNotFoundError:
        return HTMLResponse("not found", status_code=404)
    targets = viewer_targets(wf, lang=lang())
    if not 0 <= i < len(targets):
        return HTMLResponse(_("沒有可以檢視的結構。", "There is no structure to show.", "表示できる構造がありません。",
                              "표시할 구조가 없습니다."), status_code=404)
    try:
        return HTMLResponse(viewer_html(scene_for(targets[i]), title=targets[i]["label"], lang=lang()))
    except Exception as exc:  # noqa: BLE001
        return HTMLResponse(_("無法產生 3D 場景：", "The 3D scene could not be built: ", "3D シーンを作成できませんでした：",
                              "3D 장면을 만들 수 없습니다: ") + f"{type(exc).__name__}: {exc}", status_code=500)


@app.get("/report/{project}/{name}")
def serve_report(project: str, name: str, lang: str = "en"):
    """Workflow report in the requested language (D-52); rebuilt from the workflow files on every request."""
    from fastapi.responses import HTMLResponse
    if safe_name(project) != project or safe_name(name) != name:
        return HTMLResponse("not allowed", status_code=403)
    try:
        wf = Workflow.open(Project(Path(STATE["projects_dir"]) / project), name)
    except FileNotFoundError:
        return HTMLResponse("not found", status_code=404)
    from ..report.workflow_report import build_workflow_report
    code = lang if lang in LANGS else "en"
    try:
        p = build_workflow_report(wf, wf.dir / f"workflow_report_{code}.html", lang=code)
    except Exception as exc:  # noqa: BLE001
        return HTMLResponse(f"report failed: {type(exc).__name__}: {exc}", status_code=500)
    return HTMLResponse(p.read_text(encoding="utf-8"))


@app.get("/file")
def serve_file(path: str):
    from fastapi.responses import FileResponse, HTMLResponse
    p = Path(path).resolve()
    root = Path(STATE["projects_dir"]).resolve()
    if root not in p.parents or not p.is_file():
        return HTMLResponse("not allowed", status_code=403)
    return FileResponse(p)


from . import pages_v2  # noqa: E402,F401  (registers the v2 pages: home, teaching, quick and pro forms)


def main(projects_dir: str | None = None, port: int = 8020, show: bool = True, host: str = "127.0.0.1"):
    """Local-only by default: NiceGUI would otherwise listen on 0.0.0.0, and on a classroom Wi-Fi anyone could open
    another student's GUI, start/pause runs, rewrite config and download project files.  `--host 0.0.0.0` opts in."""
    if projects_dir:
        STATE["projects_dir"] = Path(projects_dir)
        STATE["lang"] = None
    Path(STATE["projects_dir"]).mkdir(parents=True, exist_ok=True)
    if host not in ("127.0.0.1", "localhost", "::1"):
        print(f"注意：GUI 對外開放於 {host}:{port}。同一個網路上的任何人都能操作這台工作站，也能下載專案檔。", flush=True)
    # D-93: loading a large system (OpenMM XML) can hold the GIL for tens of seconds; the browser waits instead of
    # showing "connection lost" and reloading the page
    import inspect
    extra = {"reconnect_timeout": 180.0} if "reconnect_timeout" in inspect.signature(ui.run).parameters else {}
    tune_heartbeat()
    ui.run(title="MD20", host=host, port=port, show=show, reload=False, language=QUASAR_LANG[lang()], **extra)
