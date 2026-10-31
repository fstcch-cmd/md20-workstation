from md20.env.doctor import recommend_tier, estimate_eta_hours


def test_recommend_tier_scales_with_system_size():
    r = recommend_tier(50.0)                       # laptop GPU, 24k atoms
    assert r["recommended"] == "teaching"          # 10.7 ns → ~5 h; research 101.5 ns → ~49 h > 48
    r2 = recommend_tier(50.0, n_atoms_system=96000, max_hours=12)  # 4× bigger → 12.5 ns/day; 10.7 ns needs ~20 h
    assert r2["recommended"] == "classroom"
    r3 = recommend_tier(0.5)
    assert r3["recommended"] == "classroom" and not any(x["fits"] for x in r3["rows"])
    assert estimate_eta_hours(0, 1) == float("inf")


def test_nvidia_file_diagnosis():
    from md20.env.winfix import diagnose_nvidia_files, suppress_windows_error_dialogs
    assert "殘留" in diagnose_nvidia_files({"nvcuda.dll": False, "nvopencl.dll": True, "nvidia-smi.exe": False})
    assert diagnose_nvidia_files({"nvcuda.dll": True, "nvopencl.dll": True, "nvidia-smi.exe": True}) is None
    assert diagnose_nvidia_files({}) is None
    suppress_windows_error_dialogs()  # no-op off Windows, must not raise
