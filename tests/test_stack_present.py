"""In the openmm-stack CI jobs (MD20_STACK=1) every core package must import.  Without this guard a broken
dependency turns the docking / HTS / metal integration tests into SKIPPED and the job stays green — which is
exactly how Windows shipped without meeko (gemmi missing) while CI looked fine."""
import importlib
import os

import pytest

CORE = ["openmm", "pdbfixer", "rdkit", "openff.toolkit", "openmmforcefields", "mdtraj", "pymbar", "meeko", "nicegui", "openpyxl"]


@pytest.mark.skipif(not os.environ.get("MD20_STACK"), reason="only meaningful where the full stack is expected (MD20_STACK=1)")
@pytest.mark.parametrize("mod", CORE)
def test_core_package_imports(mod):
    importlib.import_module(mod)


@pytest.mark.skipif(not os.environ.get("MD20_STACK"), reason="only meaningful where the full stack is expected (MD20_STACK=1)")
def test_vina_available():
    try:
        import vina  # noqa: F401
    except ImportError:
        from md20.docking.vina_cli import ensure_vina_exe
        assert ensure_vina_exe()
