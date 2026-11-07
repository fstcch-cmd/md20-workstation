"""Single current capability manifest (R7, D-136): docs/capabilities.json -> docs/CAPABILITIES.md, plus checks.

The manifest answers, per feature: where it is implemented, which system types it supports, its restrictions, which
tests of which TYPE ran in which CI job, the last known result with commit and evidence URL, the benchmark scope, and
which PUBLISHED installer contains it.  Five states are kept distinct and never inferred from one another:
implemented / synthetic-tested / real-engine-tested / scientifically benchmarked / in a released installer.
Historical logs stay in docs/STATUS.md and docs/DECISIONS.md.

  python tools/capability_manifest.py --check    verify (exit 1 on any problem; used by CI and tests/test_capability_manifest.py)
  python tools/capability_manifest.py --write    regenerate docs/CAPABILITIES.md from docs/capabilities.json
  python tools/capability_manifest.py --stale    informational: features whose files changed since their evidence commit
                                                 (needs git history; never fails)

--check verifies: schema and vocabularies; every implementation path (and ::symbol) and test file exists; test types
match the CI job class; no state contradicts its evidence (e.g. "real-engine-tested" needs a real_engine test in a
BLOCKING real-engine job; "benchmarked: yes" needs a blocking benchmark job; evidence needs commit + URL); the
released_installer value names a really published tag; package/README/student-doc versions agree with the published
tags; the .md is in sync; every workflow job is listed, and non-blocking / diagnostic / benchmark jobs say "not
qualification" in their displayed job name; CI runs this check.  Pure Python (json, re, subprocess for --stale only).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "docs" / "capabilities.json"
MARKDOWN = ROOT / "docs" / "CAPABILITIES.md"
SCHEMA = "md20.capabilities/1"
TEST_TYPES = ("unit", "synthetic", "real_engine", "gui", "diagnostic", "benchmark")
JOB_CLASSES = ("unit", "real_engine", "benchmark", "diagnostic", "gui", "release")
STATE_VOCAB = {
    "implemented": ("yes", "partial", "no"),
    "synthetic_tested": ("yes", "no"),
    "real_engine_tested": ("yes", "partial", "failing", "no"),
    "scientifically_benchmarked": ("none", "observed", "yes"),
}
RESULT_STATUS = ("pass", "fail", "partial", "stale", "unverified")
UNRELEASED = "unreleased (main only)"
FEATURE_KEYS = ("id", "feature", "implementation", "supported_system_types", "restrictions", "tests", "states",
                "last_known_result", "benchmark_scope", "released_installer")
TAG_RE = re.compile(r"v0\.1\.0a\d+")


def load(path: Path = MANIFEST) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------------------------- workflows
def scan_workflows(root: Path) -> dict:
    """{workflow file: {job key: {"name": displayed name or None, "continue_on_error": bool}}} from the YAML text.
    A deliberately small line parser (no PyYAML in the pure-python CI job): jobs sit at 2-space indent under `jobs:`."""
    out: dict = {}
    for f in sorted((root / ".github" / "workflows").glob("*.yml")):
        jobs: dict = {}
        cur = None
        in_jobs = False
        for line in f.read_text(encoding="utf-8").splitlines():
            if re.match(r"^jobs:\s*$", line):
                in_jobs = True
                continue
            if not in_jobs:
                continue
            if line and not line.startswith((" ", "#")):
                in_jobs = False
                continue
            m = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
            if m:
                cur = m.group(1)
                jobs[cur] = {"name": None, "continue_on_error": False}
                continue
            if cur is None:
                continue
            m = re.match(r"^    name:\s*(.+?)\s*$", line)
            if m:
                jobs[cur]["name"] = m.group(1).strip("\"'")
            if re.match(r"^    continue-on-error:\s*true\s*$", line):
                jobs[cur]["continue_on_error"] = True
        out[f.name] = jobs
    return out


# ---------------------------------------------------------------------------------------------- checks
def _symbol_defined(text: str, symbol: str) -> bool:
    last = symbol.split(".")[-1]
    return re.search(rf"^\s*(?:async\s+)?(?:def|class)\s+{re.escape(last)}\b|^\s*{re.escape(last)}\s*[:=]", text, re.M) is not None


def _job_ids(manifest: dict) -> dict:
    ids = {}
    for j in manifest.get("ci_jobs", []):
        ids[j["id"]] = j
        for g in j.get("groups", []) or []:
            ids[f"{j['id']}[{g}]"] = j
    return ids


def _is_none(scope) -> bool:
    return str(scope or "none").strip().lower().startswith("none")


def check_versions(manifest: dict, root: Path) -> list[str]:
    p = []
    v = manifest.get("versions", {})
    pub, never = v.get("published_releases", []), v.get("never_published", [])
    latest = v.get("latest_published_release")
    if latest not in pub:
        p.append(f"versions.latest_published_release {latest!r} is not in published_releases")
    if set(pub) & set(never):
        p.append(f"tags both published and never_published: {sorted(set(pub) & set(never))}")
    py = (root / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', py, re.M)
    init = (root / "md20" / "__init__.py").read_text(encoding="utf-8")
    m2 = re.search(r'^__version__\s*=\s*"([^"]+)"', init, re.M)
    pv, iv = (m.group(1) if m else None), (m2.group(1) if m2 else None)
    if pv != v.get("package_version"):
        p.append(f"pyproject.toml version {pv!r} != manifest package_version {v.get('package_version')!r}")
    if iv != pv:
        p.append(f"md20/__init__.py __version__ {iv!r} != pyproject.toml version {pv!r}")
    if f"v{pv}" in pub:
        p.append(f"package version {pv} equals a published tag: a dev tree must carry a .dev version")
    readme = (root / "README.md").read_text(encoding="utf-8")
    if latest and latest not in readme:
        p.append(f"README.md does not name the latest published release {latest}")
    # no student-facing document may point at a release that was never published
    docs = [root / "README.md", root / "docs" / "WINDOWS_QUICKSTART.md"] + sorted((root / "docs" / "students").glob("*.md"))
    for d in docs:
        if not d.is_file():
            continue
        for n, line in enumerate(d.read_text(encoding="utf-8").splitlines(), 1):
            for tag in TAG_RE.findall(line):
                if tag not in pub and not re.search(r"從未|未發行|never|unpublished|開發中|dev", line, re.I):
                    p.append(f"{d.relative_to(root)}:{n} names {tag}, which was never published")
    for draft in v.get("unpublished_release_note_drafts", []):
        if not (root / draft).is_file():
            p.append(f"unpublished release-note draft {draft} listed but missing")
        tag = Path(draft).stem
        if tag in pub:
            p.append(f"{draft} is listed as unpublished but {tag} is published")
    return p


def check_features(manifest: dict, root: Path) -> list[str]:
    p: list[str] = []
    jobs = _job_ids(manifest)
    seen = set()
    for f in manifest.get("features", []):
        fid = f.get("id", "?")
        if fid in seen:
            p.append(f"duplicate feature id {fid}")
        seen.add(fid)
        for k in FEATURE_KEYS:
            if k not in f:
                p.append(f"{fid}: missing field {k}")
        if any(k not in f for k in FEATURE_KEYS):
            continue
        for item in f["implementation"]:
            path, _, sym = item.partition("::")
            fp = root / path
            if not fp.is_file():
                p.append(f"{fid}: implementation path not found: {path}")
            elif sym:
                try:
                    if not _symbol_defined(fp.read_text(encoding="utf-8"), sym):
                        p.append(f"{fid}: symbol {sym} not defined in {path}")
                except UnicodeDecodeError:
                    p.append(f"{fid}: cannot read {path} to look for {sym}")
        for t in f["tests"]:
            if t.get("type") not in TEST_TYPES:
                p.append(f"{fid}: test {t.get('file')} has unknown type {t.get('type')!r}")
            if not (root / t.get("file", "")).is_file():
                p.append(f"{fid}: test file not found: {t.get('file')}")
            ci = t.get("ci_job")
            job = jobs.get(ci)
            if job is None:
                if ci != "none":
                    p.append(f"{fid}: test {t.get('file')} names unknown ci_job {ci!r}")
                continue
            cls, ty = job.get("class"), t.get("type")
            if ty == "benchmark" and cls != "benchmark":
                p.append(f"{fid}: benchmark test {t['file']} sits in a {cls} job")
            if ty == "diagnostic" and cls != "diagnostic":
                p.append(f"{fid}: diagnostic {t['file']} sits in a {cls} job")
            if ty == "real_engine" and cls != "real_engine":
                p.append(f"{fid}: real_engine test {t['file']} sits in a {cls} job ({ci})")
            if cls in ("benchmark", "diagnostic") and ty not in ("benchmark", "diagnostic"):
                p.append(f"{fid}: a {ty} test is filed under the {cls} job {ci}")
        st = f["states"]
        for key, vocab in STATE_VOCAB.items():
            if st.get(key) not in vocab:
                p.append(f"{fid}: states.{key}={st.get(key)!r} not in {vocab}")
        if any(st.get(k) not in vocab for k, vocab in STATE_VOCAB.items()):
            continue
        by_type = {}
        for t in f["tests"]:
            by_type.setdefault(t["type"], []).append(jobs.get(t.get("ci_job")))
        res, scope = f["last_known_result"], f["benchmark_scope"]
        # --- never infer one state from another: each needs its own matching evidence
        if st["implemented"] == "no" and (st["synthetic_tested"] != "no" or st["real_engine_tested"] != "no"):
            p.append(f"{fid}: not implemented but tested")
        if st["synthetic_tested"] == "yes" and not any(j and "synthetic_tested" in j.get("counts_for", []) for ty in ("unit", "synthetic") for j in by_type.get(ty, [])):
            p.append(f"{fid}: synthetic_tested=yes without a unit/synthetic test in a job that counts for it")
        if st["real_engine_tested"] != "no" and not any(j and j.get("blocking") and j.get("class") == "real_engine" and "real_engine_tested" in j.get("counts_for", [])
                                                        for j in by_type.get("real_engine", [])):
            p.append(f"{fid}: real_engine_tested={st['real_engine_tested']} without a real_engine test in a BLOCKING real-engine job")
        if st["real_engine_tested"] == "failing" and res.get("status") != "fail":
            p.append(f"{fid}: real_engine_tested=failing but last_known_result.status={res.get('status')}")
        if st["real_engine_tested"] == "yes" and res.get("status") not in ("pass", "stale"):
            p.append(f"{fid}: real_engine_tested=yes but last_known_result.status={res.get('status')}")
        if st["scientifically_benchmarked"] != "none":
            if _is_none(scope):
                p.append(f"{fid}: scientifically_benchmarked={st['scientifically_benchmarked']} but benchmark_scope is none")
            if not by_type.get("benchmark"):
                p.append(f"{fid}: scientifically_benchmarked={st['scientifically_benchmarked']} without a benchmark test")
            if st["scientifically_benchmarked"] == "yes" and not any(j and j.get("blocking") for j in by_type.get("benchmark", [])):
                p.append(f"{fid}: benchmarked=yes needs a BLOCKING benchmark job; non-blocking results are 'observed' at most")
        elif not _is_none(scope):
            p.append(f"{fid}: benchmark_scope describes a benchmark but scientifically_benchmarked=none (use 'observed' or start the scope with 'none')")
        # --- evidence
        if res.get("status") not in RESULT_STATUS:
            p.append(f"{fid}: last_known_result.status {res.get('status')!r} not in {RESULT_STATUS}")
        elif res["status"] != "unverified":
            if not res.get("commit") or not str(res.get("evidence_url", "")).startswith("https://github.com/"):
                p.append(f"{fid}: status {res['status']} needs a commit and an https://github.com/ evidence_url")
            if not f["tests"]:
                p.append(f"{fid}: status {res['status']} without any test")
        if res.get("status") == "stale" and not res.get("changed_since_evidence"):
            p.append(f"{fid}: status stale must list changed_since_evidence")
        # --- released installer
        rel = f["released_installer"]
        pub = manifest.get("versions", {}).get("published_releases", [])
        if rel != UNRELEASED:
            tag = re.match(r"(v0\.1\.0a\d+)(?!\d)", rel)      # exact tag: 'v0.1.0a19' must not pass as a prefix match of 'v0.1.0a1'
            if not tag:
                p.append(f"{fid}: released_installer {rel!r} is neither {UNRELEASED!r} nor a published tag")
            elif tag.group(1) not in pub:
                p.append(f"{fid}: released_installer names {tag.group(1)}, which was never published (neither {UNRELEASED!r} nor a published tag)")
    return p


def check_ci_jobs(manifest: dict, root: Path) -> list[str]:
    p: list[str] = []
    actual = scan_workflows(root)
    listed = {(j["workflow"], j["job"]): j for j in manifest.get("ci_jobs", [])}
    for j in manifest.get("ci_jobs", []):
        if j.get("class") not in JOB_CLASSES:
            p.append(f"ci_jobs {j.get('id')}: unknown class {j.get('class')!r}")
        if j.get("id") != f"{j.get('workflow')}:{j.get('job')}":
            p.append(f"ci_jobs {j.get('id')}: id must be '<workflow>:<job>'")
        for s in j.get("counts_for", []):
            if s not in ("synthetic_tested", "real_engine_tested"):
                p.append(f"ci_jobs {j['id']}: counts_for {s!r} unknown")
        if j.get("class") in ("benchmark", "diagnostic") and (j.get("blocking") or j.get("counts_for")):
            p.append(f"ci_jobs {j['id']}: a {j['class']} job must be non-blocking and count for nothing")
    for wf, jobs in actual.items():
        for key, info in jobs.items():
            entry = listed.get((wf, key))
            if entry is None:
                p.append(f"workflow job {wf}:{key} is not listed in the manifest ci_jobs")
                continue
            if info["continue_on_error"] and entry.get("blocking"):
                p.append(f"{wf}:{key} has continue-on-error but the manifest says blocking")
            needs_label = (not entry.get("blocking")) or entry.get("class") in ("benchmark", "diagnostic") or info["continue_on_error"]
            if needs_label and "not qualification" not in (info["name"] or "").lower():
                p.append(f"{wf}:{key} is non-blocking/diagnostic/benchmark: its displayed name (name:) must say 'not qualification'")
    for (wf, key) in listed:
        if key not in actual.get(wf, {}):
            p.append(f"manifest lists {wf}:{key} but no such workflow job exists")
    # wiring
    ci = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    if "tools/capability_manifest.py --check" not in ci:
        p.append("ci.yml does not run 'python tools/capability_manifest.py --check'")
    dm = (root / ".github" / "workflows" / "diag-membrane.yml").read_text(encoding="utf-8")
    if "tools/validate_membrane_diag.py" not in dm:
        p.append("diag-membrane.yml does not run tools/validate_membrane_diag.py")
    return p


def check_structure(manifest: dict) -> list[str]:
    p = []
    if manifest.get("schema") != SCHEMA:
        p.append(f"schema must be {SCHEMA!r}")
    for k in ("as_of", "versions", "evidence_baseline", "state_definitions", "test_types", "ci_jobs", "features"):
        if k not in manifest:
            p.append(f"missing top-level key {k}")
    return p


def check_markdown_in_sync(manifest: dict, md_path: Path = MARKDOWN) -> list[str]:
    want = render_markdown(manifest)
    if not md_path.is_file():
        return [f"{md_path.name} is missing (run: python tools/capability_manifest.py --write)"]
    have = md_path.read_text(encoding="utf-8").replace("\r\n", "\n")
    if have != want:
        return [f"{md_path.name} is out of sync with capabilities.json (run: python tools/capability_manifest.py --write)"]
    return []


def run_checks(root: Path = ROOT, manifest_path: Path | None = None, md_path: Path | None = None) -> list[str]:
    mp = manifest_path or root / "docs" / "capabilities.json"
    try:
        manifest = load(mp)
    except (OSError, ValueError) as exc:
        return [f"cannot read {mp}: {exc}"]
    problems = check_structure(manifest)
    if problems:
        return problems
    problems += check_features(manifest, root)
    problems += check_ci_jobs(manifest, root)
    problems += check_versions(manifest, root)
    problems += check_markdown_in_sync(manifest, md_path or root / "docs" / "CAPABILITIES.md")
    return problems


# ---------------------------------------------------------------------------------------------- rendering
def _esc(s) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def render_markdown(m: dict) -> str:
    v, eb, a = m["versions"], m["evidence_baseline"], m["as_of"]
    L = ["# MD20 能力清單（Capability manifest）", "",
         "> 由 `tools/capability_manifest.py --write` 從 `docs/capabilities.json` 產生，**不要手改**（`--check` 會擋下不同步）。",
         "> 規格：`docs/specs/capabilities.md`。只寫現況；歷史紀錄在 `docs/STATUS.md` 與 `docs/DECISIONS.md`。", "",
         m["about"], "",
         "## 版本事實", "",
         f"- 套件版本（pyproject／`md20.__version__`）：`{v['package_version']}`（開發中，未發行）",
         f"- 已發行的最新版本：**{v['latest_published_release']}**；已發行共 {len(v['published_releases'])} 版：{', '.join(v['published_releases'])}",
         f"- 從未發行：{', '.join(v['never_published'])}（發行說明草稿：{', '.join(v['unpublished_release_note_drafts'])}）",
         f"- 查證：{v['published_evidence']}",
         f"- {v['release_policy']}", "",
         "## 證據基準", "",
         f"- commit `{eb['commit']}`，CI run {eb['ci_run_url']}",
         f"- 為什麼選它：{eb['why_this_commit']}",
         f"- 結果：{eb['summary']}",
         f"- 查證方式：{eb['facts_checked_by']}",
         f"- {eb['skips_are_not_passes']}",
         f"- 清單對應的樹：`{a['tree_commit']}`（{a['date']}）。{a['note']}", "",
         "## 五種狀態（彼此獨立，不得互相推論）", ""]
    for k, d in m["state_definitions"].items():
        L.append(f"- **{k}**：{d}")
    L += ["", "測試類型：" + "；".join(f"`{k}` = {d}" for k, d in m["test_types"].items()), "",
          "## CI job 分類（誰能當資格、誰不能）", "",
          "| job | 類別 | 阻擋 | 可支持的狀態 | 580cbff 結果 | 說明 |", "|---|---|---|---|---|---|"]
    for j in m["ci_jobs"]:
        L.append(f"| `{j['id']}` | {j['class']} | {'是' if j['blocking'] else '**否**'} | {', '.join(j['counts_for']) or '—（不能當資格）'} | {_esc(j['baseline'])} | {_esc(j['note'])} |")
    L += ["", "## 總覽", "",
          "| 功能 | 實作 | 合成測試 | 真實引擎 | 科學 benchmark | 已發行安裝程式 | 最後已知結果 |", "|---|---|---|---|---|---|---|"]
    for f in m["features"]:
        s, r = f["states"], f["last_known_result"]
        L.append(f"| [{_esc(f['feature'])}](#{f['id']}) | {s['implemented']} | {s['synthetic_tested']} | {s['real_engine_tested']} | {s['scientifically_benchmarked']} | {_esc(f['released_installer'])} | {r['status']} |")
    for f in m["features"]:
        s, r = f["states"], f["last_known_result"]
        L += ["", f'<a id="{f["id"]}"></a>', f"## {f['feature']}", "", f"`{f['id']}`", ""]
        L.append("**實作**：" + ("、".join(f"`{x}`" for x in f["implementation"]) or "—"))
        L.append("")
        L.append("**支援的系統類型**：" + "；".join(f["supported_system_types"]))
        L.append("")
        L.append("**限制**：")
        L += [f"- {x}" for x in f["restrictions"]] or ["- —"]
        L += ["", "**測試**：", ""]
        if f["tests"]:
            L += ["| 檔案 | 類型 | CI job |", "|---|---|---|"] + [f"| `{t['file']}` | {t['type']} | `{t['ci_job']}` |" for t in f["tests"]]
        else:
            L.append("無。")
        L += ["", f"**狀態**：implemented=`{s['implemented']}`｜synthetic_tested=`{s['synthetic_tested']}`｜real_engine_tested=`{s['real_engine_tested']}`｜scientifically_benchmarked=`{s['scientifically_benchmarked']}`｜released_installer=`{f['released_installer']}`"]
        L.append("")
        res = f"**最後已知結果**：`{r['status']}`"
        if r.get("commit"):
            res += f"，commit `{r['commit']}`，證據 {r['evidence_url']}"
        res += f"。依據：{r['basis']}"
        if r.get("changed_since_evidence"):
            res += "。證據之後改動的檔案（現況沒有 CI 結果）：" + "、".join(f"`{x}`" for x in r["changed_since_evidence"])
        if r.get("note"):
            res += f"。{r['note']}"
        L.append(res)
        L.append("")
        L.append(f"**benchmark 範圍**：{f['benchmark_scope']}")
        L.append("")
        L.append(f"**已發行安裝程式**：{f['released_installer']}" + (f"（{f['released_installer_note']}）" if f.get("released_installer_note") else ""))
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------------------------------------- stale report
def stale_report(manifest: dict, root: Path = ROOT) -> tuple[list[str], list[str]]:
    """(lines, notes).  For each feature with an evidence commit: files changed between it and HEAD.  Needs git history."""
    lines, notes = [], []
    for f in manifest["features"]:
        r = f["last_known_result"]
        if not r.get("commit"):
            continue
        files = sorted({x.partition("::")[0] for x in f["implementation"]} | {t["file"] for t in f["tests"]})
        try:
            out = subprocess.run(["git", "diff", "--name-only", r["commit"], "HEAD", "--", *files], cwd=root,
                                 capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError) as exc:
            notes.append(f"git unavailable: {exc}")
            return lines, notes
        if out.returncode != 0:
            notes.append(f"cannot compare with {r['commit']} (not in local history; shallow clone?): {out.stderr.strip()[:100]}")
            return lines, notes
        changed = [x for x in out.stdout.split() if x]
        claimed = set(r.get("changed_since_evidence", []))
        if changed and r["status"] in ("pass", "partial", "fail") and not claimed:
            lines.append(f"{f['id']}: status {r['status']} but changed since {r['commit']}: {', '.join(changed)}")
        elif not changed and r["status"] == "stale":
            lines.append(f"{f['id']}: marked stale but nothing changed since {r['commit']}")
    return lines, notes


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true", help="verify the manifest; exit 1 on any problem")
    g.add_argument("--write", action="store_true", help="regenerate docs/CAPABILITIES.md")
    g.add_argument("--stale", action="store_true", help="informational: statuses older than the code (needs git history)")
    a = ap.parse_args(argv)
    if a.write:
        MARKDOWN.write_text(render_markdown(load()), encoding="utf-8", newline="\n")
        print(f"wrote {MARKDOWN.relative_to(ROOT)}")
        return 0
    if a.stale:
        lines, notes = stale_report(load())
        for n in notes:
            print("note:", n)
        for ln in lines:
            print("STALE?", ln)
        print(f"{len(lines)} feature(s) whose status is older than their code" if not notes else "stale report incomplete")
        return 0
    problems = run_checks()
    for pr in problems:
        print("PROBLEM:", pr)
    if problems:
        print(f"capability manifest: {len(problems)} problem(s)")
        return 1
    m = load()
    print(f"capability manifest OK: {len(m['features'])} features, {len(m['ci_jobs'])} CI jobs, latest published {m['versions']['latest_published_release']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
