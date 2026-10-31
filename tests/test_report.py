from pathlib import Path
import zipfile

from md20.project import Project
from md20.engine import make_protocol, run_protocol, FakeBackend
from md20.report import build_run_report, reproducibility_bundle, methods_paragraph


def test_report_and_bundle(tmp_path: Path):
    p = Project.create(tmp_path, "rep")
    c = p.new_case("c")
    proto = make_protocol("classroom")
    for s in proto.stages:
        if s.ensemble != "MIN":
            s.length_ps = 10.0; s.checkpoint_interval_ps = 5.0; s.report_interval_ps = 0.2
    r = c.new_run(proto.to_dict())
    run_protocol(r.dir, proto, lambda spec, dt: FakeBackend(timestep_fs=dt, temperature_k=spec.temperature_k, ensemble=spec.ensemble),
                 identity={"case_id": c.case_id, "run_id": r.run_id}, decisions=p.decisions, batch_steps=250)
    out = build_run_report(r)
    html = out.read_text(encoding="utf-8")
    assert "data:image/png;base64" in html and "決策日誌" in html and "restraint ladder" in html
    assert "NPT 平衡" in html and "通過" in html
    z = reproducibility_bundle(r)
    names = zipfile.ZipFile(z).namelist()
    assert "BUNDLE_MANIFEST.json" in names and any(n.endswith("report.html") for n in names)
    assert any("production_complete.json" in n for n in names) and not any("chunk_" in n for n in names)
    en = methods_paragraph({"run": r.manifest(), "case": c.manifest(), "build": {}, "stages": {}}, "en")
    assert "OpenMM" in en
