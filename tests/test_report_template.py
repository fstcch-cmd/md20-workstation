"""D-59: the report template (tools/report_template.py) must exercise every figure kind the report can draw —
a new kind in figure_text.FIG without template data fails here.  RDKit-only kinds are required where RDKit exists (CI)."""
import importlib.util
import json
from pathlib import Path

from md20.report.figure_text import FIG

ROOT = Path(__file__).resolve().parents[1]
RDKIT_KINDS = {"properties", "chem_space", "interaction_2d"}


def test_template_covers_every_figure_kind(tmp_path):
    spec = importlib.util.spec_from_file_location("report_template", ROOT / "tools" / "report_template.py")
    rt = importlib.util.module_from_spec(spec); spec.loader.exec_module(rt)
    assert rt.main(tmp_path) == 0
    for lang in ("en", "zh"):
        html = (tmp_path / f"MD20_report_template_{lang}.html").read_text(encoding="utf-8")
        idx = next(tmp_path.glob(f"_work_{lang}/**/report_figures/index_{lang}.json"))
        kinds = {f["kind"] for f in json.loads(idx.read_text(encoding="utf-8"))["figures"]}
        missing = set(FIG) - kinds
        has_rdkit = importlib.util.find_spec("rdkit") is not None
        assert missing == set() if has_rdkit else missing <= RDKIT_KINDS, (lang, sorted(missing))
        assert "synthetic demo data" in html or "合成示範資料" in html
