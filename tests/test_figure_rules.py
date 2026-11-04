"""D-89: line charts — the key never covers the data, x always increases, every line is named, one colour per series."""
import json

import numpy as np
import pytest

matplotlib = pytest.importorskip("matplotlib")

from md20.analysis.plots import legend_outside, _mpl
from md20.analysis.stream import production_times_ps
from md20.report import figures as FG


def test_legend_moves_outside_and_does_not_overlap():
    plt = _mpl()
    fig, ax = plt.subplots(figsize=(6.4, 2.6))
    for i in range(6):
        ax.plot(np.arange(10), np.random.rand(10) + i, label=f"docked_multi L0{i + 1}")
    ax.legend(ncol=4)
    legend_outside(fig)
    assert ax.get_legend() is None and len(fig.legends) == 1
    fig.canvas.draw()
    r = fig.canvas.get_renderer()
    lb = fig.legends[0].get_window_extent(r)
    axb = ax.get_window_extent(r)
    assert lb.x0 >= axb.x1                                   # entirely to the right of the plotting area
    assert [t.get_text() for t in fig.legends[0].get_texts()][0] == "docked_multi L01"
    plt.close(fig)


def test_time_axis_never_draws_a_reset_as_time():
    x, lab = FG.time_axis([0.0, 0.001, 0.002, 0.0, 0.001, 0.002], 6)
    assert lab.startswith("Saved frame") and list(x) == [1, 2, 3, 4, 5, 6]
    x, lab = FG.time_axis([0.01, 0.02, 0.03], 3)
    assert lab == "Time (ns)" and list(x) == [0.01, 0.02, 0.03]


def test_production_times_span_the_whole_run(tmp_path):
    st = tmp_path / "stages" / "production"; st.mkdir(parents=True)
    st.joinpath("production_complete.json").write_text(json.dumps({"timestep_fs": 2.0, "result": {
        "steps": 1_000_000, "dcd_paths": ["a.dcd", "b.dcd"]}}))      # 2 ns in two chunk files of 100 frames
    t = production_times_ps(tmp_path, counts=[100, 100])
    assert len(t) == 200 and t[0] == pytest.approx(10.0) and t[-1] == pytest.approx(2000.0) and np.all(np.diff(t) > 0)
    t2 = production_times_ps(tmp_path, counts=[100, 100], stride=10)
    assert len(t2) == 20 and t2[10] == pytest.approx(1010.0)


def test_series_keep_their_colour_and_get_styles_past_the_palette():
    FG.reset_colours()
    a = FG.series_style("docked_multi L01")
    for i in range(20):
        FG.series_style(f"s{i}")
    assert FG.series_style("docked_multi L01") == a
    styles = {FG.series_style(f"s{i}")["ls"] for i in range(20)}
    assert len(styles) > 1                                   # more series than colours → line styles differ


def test_timeseries_figure_with_chunked_times(tmp_path):
    """The case from the laptop: six ligands, ten chunk files each starting at 0 → frame axis, named lines, key outside."""
    FG.reset_colours()
    t_bad = list(np.tile(np.arange(10) / 1000.0, 10))
    series = {f"docked_multi L0{i}": (t_bad, np.random.randint(0, 4, 100)) for i in range(1, 7)}
    p = FG.timeseries(series, "Ligand–protein hydrogen bonds", tmp_path / "hb.png")
    assert p and (tmp_path / "hb.png").stat().st_size > 1000
