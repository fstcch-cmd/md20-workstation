#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D-166（方案一）：出貨 build 的核心模組 Cython 編譯層。

誠實定位
--------
這一層只把核心 .py 編譯成 C 擴充（.pyd/.so），並從出貨樹移除對應的 .py 原始碼。
它提高「把授權檢查剝掉」的成本（讀 C 擴充比讀 .py 難得多），但**不是不可破**：
Python 擴充仍可被逆向。真正的護城河是「出貨 build 不含核心原始碼」這件事本身
（見 docs/specs/licensing.md 第 4 層、D-128 §6），編譯是達成它的手段，不是加密。

這一層**不處理任何金鑰、不加密、不做執行期解密、不動態 exec**。因此也不需要任何
GitHub Secret。驗證邏輯（md20/util/license.py）內容完全不變，只是改以編譯形式出貨。

預設不啟用：release workflow 的 `compiled_core` 輸入預設 false，預設發行與現行逐位元相同
（git archive 原始碼）。只有 opt-in 時才走本工具的編譯路徑。

容器限制
--------
開發容器裝不了 Cython、也不能連網安裝。本模組的「清單」與「strip 計畫」是純函式，
可離線測試；真正的 `cythonize` 只在 CI／發行 runner 執行（opt-in）。
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

# 核心模組：引擎、參數化、閘門判定、授權內部（D-128 §6 的「核心層」）。
# 刻意不含：i18n、report、gui、cli、advisor、students（UI／文字層，非護城河），
# 以及各 package 的 __init__.py（保持為薄 .py，編譯會破壞 import 與 package data）。
CORE_MODULES: tuple[str, ...] = (
    "md20/util/license.py",        # 授權驗證內部（RSA-PSS；內容不變，只改出貨形式）
    "md20/util/stamp.py",          # 產出戳記
    "md20/workflow.py",            # 流程編排與 DECISION_KEYS（閘門串接）
    "md20/build/assemble.py",      # 系統組裝與去碰撞閘門
    "md20/build/metal.py",         # 金屬位點閘門與力
    "md20/build/metal_params.py",  # 金屬擬合參數
    "md20/build/pipeline.py",      # 建模管線
    "md20/sampling/binding.py",    # 結合自由能核心
    "md20/sampling/funnel.py",     # 漏斗約束與標準態
    "md20/sampling/_mdh_legacy.py",# WHAM/MBAR/bootstrap 核心
    # D-181／D-182：MD20 Lite。版本判定與上限數字，以及三個「留在 Lite 安裝包裡、只靠上限擋」的完整版能力模組。
    # 編譯後 Lite 出貨樹不含它們的 .py（Lite 發行必須開 compiled_core，見 docs/specs/lite_edition.md §9、§10）。
    "md20/edition.py",             # 版本判定、Lite 上限、完整版功能登錄表
    "md20/sampling/adaptive.py",   # 傘狀採樣窗口規劃與自動補窗
    "md20/engine/longrun.py",      # 長時間模擬規劃
    "md20/analysis/extended.py",   # 進階分析（tICA、MSM、氫鍵網路、水合）
)


def _is_package_init(rel: str) -> bool:
    return rel.endswith("__init__.py")


def plan_build(modules: tuple[str, ...] = CORE_MODULES) -> dict:
    """純函式：回傳要編譯與要從出貨樹移除的檔案清單。不碰檔案系統。

    規則：每個核心模組 → 編譯成擴充、並從出貨樹移除其 .py；絕不編譯 package 的
    __init__.py（會破壞 import）。回傳可供測試斷言與供 strip_sources 使用。
    """
    compile_list: list[str] = []
    drop_py: list[str] = []
    skipped: list[str] = []
    for rel in modules:
        if _is_package_init(rel):
            skipped.append(rel)  # 安全護欄：永不編譯 __init__.py
            continue
        if not rel.endswith(".py"):
            skipped.append(rel)
            continue
        compile_list.append(rel)
        drop_py.append(rel)
    return {"compile": compile_list, "drop_py": drop_py, "skipped": skipped}


def verify_modules_exist(root: Path, modules: tuple[str, ...] = CORE_MODULES) -> list[str]:
    """回傳清單中在 root 下實際不存在的模組（應為空）。"""
    return [m for m in modules if not (root / m).is_file()]


def strip_sources(build_dir: Path, plan: dict) -> list[str]:
    """把已編譯模組的 .py 從出貨樹移除（保留編譯出的 .pyd/.so）。

    僅在對應的編譯產物已存在時才移除該 .py（fail-safe：產物不在就保留 .py，
    避免出貨出一個缺模組、根本跑不起來的 build）。回傳實際移除的清單。
    """
    removed: list[str] = []
    for rel in plan["drop_py"]:
        py = build_dir / rel
        stem = py.with_suffix("")
        has_ext = any(
            stem.with_suffix(ext).exists() or list(py.parent.glob(py.stem + "*" + ext))
            for ext in (".pyd", ".so")
        )
        if py.exists() and has_ext:
            py.unlink()
            removed.append(rel)
    return removed


def compile_core(root: Path, plan: dict | None = None) -> list[str]:
    """用 Cython 把核心模組編譯成 C 擴充。只在有 Cython 的 runner 執行（opt-in）。

    容器無 Cython 時 import 會失敗並丟 RuntimeError，呼叫端（workflow）應視為
    建置失敗（fail closed），不得默默出未編譯版本。
    """
    plan = plan or plan_build()
    try:
        from Cython.Build import cythonize
        from setuptools import Extension
        from setuptools.dist import Distribution
    except Exception as exc:  # pragma: no cover - 容器無 Cython
        raise RuntimeError(
            "compiled_core 需要 Cython/setuptools；此環境沒有。"
            "編譯只能在安裝了 Cython 的發行 runner 上跑（opt-in）；"
            "此處丟例外而非略過，確保 fail closed（不會默默出未編譯版本）。"
        ) from exc
    exts = [
        Extension(rel[:-3].replace("/", "."), [str(root / rel)])
        for rel in plan["compile"]
    ]
    ext_modules = cythonize(exts, language_level="3", quiet=True)  # pragma: no cover
    # 就地 build_ext：把 .pyd/.so 產在對應 .py 旁，之後 strip_sources 再移除 .py。
    dist = Distribution({"ext_modules": ext_modules})  # pragma: no cover
    cmd = dist.get_command_obj("build_ext")  # pragma: no cover
    cmd.inplace = 1  # pragma: no cover
    cmd.ensure_finalized()  # pragma: no cover
    cmd.run()  # pragma: no cover
    return plan["compile"]  # pragma: no cover


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="D-166 核心 Cython 編譯層（無加密、無金鑰）")
    ap.add_argument("--root", default=".", help="repo 根目錄")
    ap.add_argument("--plan-only", action="store_true", help="只印編譯／移除計畫，不編譯")
    args = ap.parse_args(argv)
    root = Path(args.root)
    plan = plan_build()
    missing = verify_modules_exist(root)
    if missing:
        print("核心模組清單有不存在的檔案（清單過期）：", missing)
        return 2
    print("將編譯：")
    for m in plan["compile"]:
        print("  ", m)
    print("出貨樹將移除（編譯成功後）：", len(plan["drop_py"]), "個 .py")
    if args.plan_only:
        return 0
    compile_core(root, plan)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
