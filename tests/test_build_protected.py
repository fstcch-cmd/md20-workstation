# -*- coding: utf-8 -*-
"""D-166 核心編譯層的純邏輯測試（容器無 Cython，只測清單與 strip 計畫）。"""
from __future__ import annotations

from pathlib import Path

import pytest

from tools import build_protected as bp

ROOT = Path(__file__).resolve().parents[1]


def test_core_modules_all_exist():
    missing = bp.verify_modules_exist(ROOT)
    assert missing == [], f"核心模組清單指到不存在的檔案：{missing}"


def test_plan_never_compiles_package_init():
    plan = bp.plan_build(bp.CORE_MODULES + ("md20/build/__init__.py",))
    assert "md20/build/__init__.py" in plan["skipped"]
    assert "md20/build/__init__.py" not in plan["compile"]


def test_plan_compiles_and_drops_each_core_module():
    plan = bp.plan_build()
    # 每個核心模組都要被編譯且其 .py 被移除
    assert plan["compile"] == list(bp.CORE_MODULES)
    assert plan["drop_py"] == list(bp.CORE_MODULES)
    # 授權內部必須在核心清單（護城河的重點）
    assert "md20/util/license.py" in plan["compile"]


def test_strip_only_removes_py_when_extension_present(tmp_path):
    # 建一個假出貨樹：一個模組有 .so、一個沒有
    (tmp_path / "md20/util").mkdir(parents=True)
    (tmp_path / "md20/sampling").mkdir(parents=True)
    py1 = tmp_path / "md20/util/license.py"
    py2 = tmp_path / "md20/sampling/binding.py"
    py1.write_text("x=1", encoding="utf-8")
    py2.write_text("y=2", encoding="utf-8")
    # 只有 license 有編譯產物
    (tmp_path / "md20/util/license.cpython-311-x86_64-linux-gnu.so").write_text("", encoding="utf-8")
    plan = {"drop_py": ["md20/util/license.py", "md20/sampling/binding.py"]}
    removed = bp.strip_sources(tmp_path, plan)
    assert removed == ["md20/util/license.py"]
    assert not py1.exists()      # 有產物 → .py 移除
    assert py2.exists()          # 無產物 → fail-safe 保留 .py，不出一個缺模組的 build


def test_strip_handles_pyd_windows(tmp_path):
    (tmp_path / "md20/util").mkdir(parents=True)
    py = tmp_path / "md20/util/stamp.py"
    py.write_text("x=1", encoding="utf-8")
    (tmp_path / "md20/util/stamp.cp311-win_amd64.pyd").write_text("", encoding="utf-8")
    removed = bp.strip_sources(tmp_path, {"drop_py": ["md20/util/stamp.py"]})
    assert removed == ["md20/util/stamp.py"]
    assert not py.exists()


def test_compile_core_fails_closed_without_cython():
    # 容器無 Cython：必須丟 RuntimeError（fail closed），不得默默略過
    try:
        import Cython  # noqa: F401
        pytest.skip("此環境有 Cython，略過 fail-closed 測試")
    except Exception:
        pass
    with pytest.raises(RuntimeError):
        bp.compile_core(ROOT)


def test_release_workflow_compiled_core_defaults_false():
    wf = (ROOT / ".github/workflows/release-windows.yml").read_text(encoding="utf-8")
    assert "compiled_core" in wf, "release workflow 需有 compiled_core 輸入"
    # 預設 false：預設發行流程不變
    import re
    # 允許 default: "false" 或 default: false
    assert re.search(r"compiled_core[\s\S]{0,200}?default:\s*[\"']?false[\"']?", wf), \
        "compiled_core 預設必須是 false（預設發行不變）"


def test_no_key_or_encryption_in_build_tool():
    src = (ROOT / "tools/build_protected.py").read_text(encoding="utf-8")
    # 這一層不碰金鑰／加密／動態 exec（方案一）
    for banned in ("AES", "GCM", "encrypt", "decrypt", "getenv", "SECRET", "exec("):
        assert banned not in src, f"build_protected 不應出現 {banned}（方案一只編譯、不加密、不碰金鑰）"
