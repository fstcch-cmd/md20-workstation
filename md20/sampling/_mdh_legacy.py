"""Hardening / sampling-quality library salvaged from MD20 0913 Phase 21B (namespace `MDH`).

Pure numpy except for lazy OpenMM / pymbar imports inside functions.
Kept verbatim apart from this header so provenance is clear; wrappers with
tests live in `md20.sampling.pmf`.
"""
from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import json
import math
import os
import platform as _py_platform
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

KB_KJ_MOL_K = 0.00831446261815324
SCHEMA_VERSION = 4


class MDHardeningError(RuntimeError):
    pass


class ResumeCompatibilityError(MDHardeningError):
    pass


class SamplingQualityError(MDHardeningError):
    pass


@dataclasses.dataclass(frozen=True)
class RuntimeFingerprint:
    openmm_version: str
    platform_name: str
    platform_properties: dict[str, str]
    python_version: str
    machine: str
    system_hash: str
    topology_hash: str
    config_hash: str

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class WindowSamplingStats:
    center_nm: float
    n_raw: int
    equilibration_index: int
    n_equilibrated: int
    statistical_inefficiency: float
    n_effective: float
    n_uncorrelated: int
    mean_nm: float
    sd_nm: float
    drift_nm: float
    center_offset_nm: float
    status: str
    reasons: list[str]


@dataclasses.dataclass
class PairSamplingStats:
    left_center_nm: float
    right_center_nm: float
    overlap_coefficient: float
    standardized_gap: float
    action: str
    proposed_center_nm: float | None


@dataclasses.dataclass
class UmbrellaQualityReport:
    passed: bool
    graph_connected: bool
    window_stats: list[WindowSamplingStats]
    pair_stats: list[PairSamplingStats]
    extend_centers_nm: list[float]
    insert_centers_nm: list[float]
    failures: list[str]
    warnings: list[str]


def canonical_json(data: Any) -> str:
    return json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    path = Path(path)
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            block = fh.read(chunk_size)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def hash_config(config: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_json(config).encode("utf-8"))


def atomic_write_bytes(path: str | Path, payload: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)


def atomic_write_text(path: str | Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def atomic_write_json(path: str | Path, data: Any) -> None:
    path = Path(path)
    if path.exists() and path.stat().st_size > 0:
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(previous, dict): shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
        except Exception:
            pass
    atomic_write_text(
        path,
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True, default=str),
    )


def atomic_write_dataframe_csv(df: Any, path: str | Path, **kwargs: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    os.close(fd)
    try:
        df.to_csv(tmp_name, index=False, encoding="utf-8-sig", **kwargs)
        with open(tmp_name, "rb") as fh:
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)


def safe_load_json(path: str | Path, default: Any = None, *, critical: bool = False) -> Any:
    path = Path(path)
    errors = []
    found = False
    for candidate in [path, path.with_suffix(path.suffix + ".bak")]:
        if not candidate.exists() or candidate.stat().st_size == 0: continue
        found = True
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
            return data
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{candidate.name}: {type(exc).__name__}: {exc}")
    if critical and found:
        raise ResumeCompatibilityError("Critical JSON state is corrupt: " + " | ".join(errors))
    return default


def seed_from_key(key: str, base_seed: int = 20260423) -> int:
    digest = hashlib.sha256(f"{base_seed}|{key}".encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "little") % 2147483647


def available_openmm_platforms() -> list[str]:
    try:
        from openmm import Platform
    except Exception:
        return []
    names = []
    for i in range(Platform.getNumPlatforms()):
        names.append(Platform.getPlatform(i).getName())
    return names


def pick_openmm_platform(
    preference: Sequence[str] = ("CUDA", "HIP", "OpenCL", "CPU"),
    precision: str | None = None,
    deterministic_forces: bool = True,
    device_index: str | None = None,
    require_gpu: bool | None = None,
):
    from openmm import Platform

    if require_gpu is None:
        require_gpu = str(os.environ.get("MSW_REQUIRE_GPU", "1")).strip().lower() not in {"0", "false", "no"}
    if precision is None:
        precision = os.environ.get("MSW_CUDA_PRECISION", "mixed")
    if device_index is None:
        device_index = os.environ.get("MSW_CUDA_DEVICE_INDEX", "0")

    available = available_openmm_platforms()
    if require_gpu:
        if "CUDA" not in available:
            raise MDHardeningError(
                f"GPU 必要模式下找不到 CUDA platform。Detected: {available}. "
                "請切換 Colab NVIDIA GPU runtime 後重新執行 Phase 0。"
            )
        chosen_name = "CUDA"
    else:
        chosen_name = next((name for name in preference if name in available), None)
    if chosen_name is None:
        raise MDHardeningError(f"No OpenMM platform is available. Detected: {available}")

    platform_obj = Platform.getPlatformByName(chosen_name)
    supported = set(platform_obj.getPropertyNames())
    properties: dict[str, str] = {}

    if "Precision" in supported and chosen_name in {"CUDA", "HIP", "OpenCL"}:
        properties["Precision"] = str(precision)
    if "DeterministicForces" in supported and deterministic_forces:
        properties["DeterministicForces"] = "true"
    if device_index is not None and "DeviceIndex" in supported:
        properties["DeviceIndex"] = str(device_index)
    if chosen_name == "CPU" and "Threads" in supported:
        threads = os.environ.get("OPENMM_CPU_THREADS")
        if threads:
            properties["Threads"] = str(threads)

    return chosen_name, platform_obj, properties


def assert_gpu_context(simulation: Any, *, required: bool | None = None) -> str:
    if required is None:
        required = str(os.environ.get("MSW_REQUIRE_GPU", "1")).strip().lower() not in {"0", "false", "no"}
    name = simulation.context.getPlatform().getName()
    if required and name != "CUDA":
        raise MDHardeningError(f"GPU 必要模式要求 CUDA，但目前 Context 使用 {name}。")
    return name


def make_runtime_fingerprint(
    *,
    openmm_version: str,
    platform_name: str,
    platform_properties: Mapping[str, str],
    system_xml_path: str | Path,
    topology_path: str | Path,
    config: Mapping[str, Any],
) -> RuntimeFingerprint:
    return RuntimeFingerprint(
        openmm_version=str(openmm_version),
        platform_name=str(platform_name),
        platform_properties={str(k): str(v) for k, v in platform_properties.items()},
        python_version=_py_platform.python_version(),
        machine=_py_platform.machine(),
        system_hash=sha256_file(system_xml_path),
        topology_hash=sha256_file(topology_path),
        config_hash=hash_config(config),
    )


def compare_fingerprints(
    old: Mapping[str, Any], new: RuntimeFingerprint
) -> tuple[list[str], list[str]]:
    current = new.to_dict()
    critical_keys = ("system_hash", "topology_hash", "config_hash")
    runtime_keys = ("openmm_version", "platform_name", "machine")
    critical = [key for key in critical_keys if old.get(key) != current.get(key)]
    runtime = [key for key in runtime_keys if old.get(key) != current.get(key)]
    return critical, runtime



def save_portable_restart_pair(
    simulation: Any,
    checkpoint_path: str | Path,
    *,
    completed_steps: int | None = None,
) -> dict[str, str]:
    """Save a binary checkpoint and a portable State XML beside it."""
    checkpoint_path = Path(checkpoint_path)
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    state_path = checkpoint_path.with_suffix(".xml")
    meta_path = checkpoint_path.with_suffix(".meta.json")
    chk_tmp = checkpoint_path.with_name(f".{checkpoint_path.name}.tmp")
    xml_tmp = state_path.with_name(f".{state_path.name}.tmp")
    simulation.saveCheckpoint(str(chk_tmp))
    simulation.saveState(str(xml_tmp))
    if not chk_tmp.exists() or chk_tmp.stat().st_size == 0:
        raise MDHardeningError("Checkpoint write produced an empty file")
    if not xml_tmp.exists() or xml_tmp.stat().st_size == 0:
        raise MDHardeningError("State XML write produced an empty file")
    os.replace(chk_tmp, checkpoint_path)
    os.replace(xml_tmp, state_path)
    try:
        import openmm

        openmm_version = getattr(openmm.version, "version", "unknown")
        platform_name = simulation.context.getPlatform().getName()
    except Exception:
        openmm_version = "unknown"
        platform_name = "unknown"
    meta = {
        "schema_version": SCHEMA_VERSION,
        "checkpoint_sha256": sha256_file(checkpoint_path),
        "state_sha256": sha256_file(state_path),
        "openmm_version": str(openmm_version),
        "platform_name": str(platform_name),
        "completed_steps": None if completed_steps is None else int(completed_steps),
        "saved_unix": time.time(),
    }
    atomic_write_json(meta_path, meta)
    return {
        "checkpoint": str(checkpoint_path),
        "state_xml": str(state_path),
        "metadata": str(meta_path),
    }


def load_portable_restart_pair(
    simulation: Any,
    checkpoint_path: str | Path,
    *,
    allow_state_fallback: bool = True,
) -> str:
    checkpoint_path = Path(checkpoint_path)
    state_path = checkpoint_path.with_suffix(".xml")
    meta_path = checkpoint_path.with_suffix(".meta.json")
    meta = safe_load_json(meta_path, default={})
    current_platform = "unknown"
    current_version = "unknown"
    try:
        import openmm

        current_version = getattr(openmm.version, "version", "unknown")
        current_platform = simulation.context.getPlatform().getName()
    except Exception:
        pass

    same_runtime = (
        str(meta.get("platform_name", current_platform)) == str(current_platform)
        and str(meta.get("openmm_version", current_version)) == str(current_version)
    )
    if same_runtime and checkpoint_path.exists():
        try:
            expected = meta.get("checkpoint_sha256")
            if expected and expected != sha256_file(checkpoint_path):
                raise ResumeCompatibilityError("Checkpoint SHA-256 mismatch")
            simulation.loadCheckpoint(str(checkpoint_path))
            return "checkpoint"
        except Exception:
            if not allow_state_fallback:
                raise
    if allow_state_fallback and state_path.exists():
        expected = meta.get("state_sha256")
        if expected and expected != sha256_file(state_path):
            raise ResumeCompatibilityError("State XML SHA-256 mismatch")
        simulation.loadState(str(state_path))
        return "state_xml"
    raise ResumeCompatibilityError(
        f"No compatible checkpoint/State XML pair for {checkpoint_path}"
    )


def save_dual_restart(
    simulation: Any,
    directory: str | Path,
    fingerprint: RuntimeFingerprint,
    prefix: str = "restart",
    completed_steps: int | None = None,
) -> dict[str, str]:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    chk_tmp = directory / f".{prefix}.chk.tmp"
    xml_tmp = directory / f".{prefix}.xml.tmp"
    chk_path = directory / f"{prefix}.chk"
    xml_path = directory / f"{prefix}.xml"

    simulation.saveCheckpoint(str(chk_tmp))
    simulation.saveState(str(xml_tmp))
    if not chk_tmp.exists() or chk_tmp.stat().st_size == 0:
        raise MDHardeningError("OpenMM checkpoint write produced an empty file")
    if not xml_tmp.exists() or xml_tmp.stat().st_size == 0:
        raise MDHardeningError("OpenMM State XML write produced an empty file")
    os.replace(chk_tmp, chk_path)
    os.replace(xml_tmp, xml_path)

    meta = {
        "schema_version": SCHEMA_VERSION,
        "fingerprint": fingerprint.to_dict(),
        "checkpoint_sha256": sha256_file(chk_path),
        "state_sha256": sha256_file(xml_path),
        "completed_steps": None if completed_steps is None else int(completed_steps),
        "saved_unix": time.time(),
    }
    atomic_write_json(directory / f"{prefix}.meta.json", meta)
    return {"checkpoint": str(chk_path), "state_xml": str(xml_path)}


def load_dual_restart(
    simulation: Any,
    directory: str | Path,
    current_fingerprint: RuntimeFingerprint,
    prefix: str = "restart",
    allow_state_fallback: bool = True,
) -> str:
    directory = Path(directory)
    meta_path = directory / f"{prefix}.meta.json"
    meta = safe_load_json(meta_path, default=None)
    if not isinstance(meta, dict):
        raise ResumeCompatibilityError(f"Missing restart metadata: {meta_path}")

    old_fp = meta.get("fingerprint", {})
    critical, runtime = compare_fingerprints(old_fp, current_fingerprint)
    if critical:
        raise ResumeCompatibilityError(
            "Restart is incompatible with current inputs: " + ", ".join(critical)
        )

    chk_path = directory / f"{prefix}.chk"
    xml_path = directory / f"{prefix}.xml"

    if not runtime and chk_path.exists():
        try:
            if meta.get("checkpoint_sha256") != sha256_file(chk_path):
                raise ResumeCompatibilityError("Checkpoint SHA-256 mismatch")
            simulation.loadCheckpoint(str(chk_path))
            return "checkpoint"
        except Exception:
            if not allow_state_fallback:
                raise

    if allow_state_fallback and xml_path.exists():
        if meta.get("state_sha256") != sha256_file(xml_path):
            raise ResumeCompatibilityError("State XML SHA-256 mismatch")
        simulation.loadState(str(xml_path))
        return "state_xml"

    detail = f"runtime mismatches={runtime}" if runtime else "checkpoint unavailable"
    raise ResumeCompatibilityError(f"No compatible restart could be loaded ({detail})")


def validate_topology_system_mapping(
    topology: Any,
    system: Any,
    positions: Any | None = None,
) -> dict[str, int]:
    atoms = list(topology.atoms())
    n_atoms = len(atoms)
    n_particles = int(system.getNumParticles())
    if n_atoms != n_particles:
        raise MDHardeningError(
            f"Topology/System mismatch: topology atoms={n_atoms}, system particles={n_particles}"
        )
    if positions is not None and len(positions) != n_particles:
        raise MDHardeningError(
            f"Position/System mismatch: positions={len(positions)}, system particles={n_particles}"
        )
    indices = [int(atom.index) for atom in atoms]
    if indices != list(range(n_atoms)):
        raise MDHardeningError("Topology atom indices are not contiguous and ordered")
    return {"n_atoms": n_atoms, "n_particles": n_particles}


def state_box_matrix_nm(state: Any) -> np.ndarray | None:
    try:
        vectors = state.getPeriodicBoxVectors(asNumpy=True)
        from openmm import unit

        arr = np.asarray(vectors.value_in_unit(unit.nanometer), dtype=float)
        if arr.shape != (3, 3) or not np.isfinite(arr).all():
            return None
        if abs(np.linalg.det(arr)) < 1e-12:
            return None
        return arr
    except Exception:
        return None


def mdtraj_box_matrix_nm(traj: Any, frame_index: int) -> np.ndarray | None:
    vectors = getattr(traj, "unitcell_vectors", None)
    if vectors is None:
        return None
    arr = np.asarray(vectors[int(frame_index)], dtype=float)
    if arr.shape != (3, 3) or not np.isfinite(arr).all():
        return None
    if abs(np.linalg.det(arr)) < 1e-12:
        return None
    return arr


def conservative_minimum_image_radius_nm(
    box_matrix_nm: Sequence[Sequence[float]] | Sequence[float],
    safety_fraction: float = 0.45,
) -> float:
    """
    以最短週期盒向量估計保守的最小影像安全半徑。方向性 CV 超過此值時，
    週期最近影像可能改變，應擴大水盒或縮短拉伸範圍。
    """
    box = np.asarray(box_matrix_nm, dtype=float)
    if box.shape == (3,):
        lengths = np.abs(box)
    elif box.shape == (3, 3):
        lengths = np.linalg.norm(box, axis=1)
    else:
        raise ValueError("box_matrix_nm must have shape (3,) or (3, 3)")
    if not np.isfinite(lengths).all() or np.min(lengths) <= 0:
        raise ValueError("periodic box lengths must be finite and positive")
    fraction = float(safety_fraction)
    if not 0.0 < fraction < 0.5:
        raise ValueError("safety_fraction must be between 0 and 0.5")
    return float(fraction * np.min(lengths))

def minimum_image_displacement(
    delta: np.ndarray, box_matrix_nm: np.ndarray | None
) -> np.ndarray:
    arr = np.asarray(delta, dtype=float)
    if box_matrix_nm is None:
        return np.array(arr, copy=True)
    box = np.asarray(box_matrix_nm, dtype=float)
    if box.shape == (3,):
        box = np.diag(box)
    if box.shape != (3, 3) or abs(np.linalg.det(box)) < 1e-12:
        return np.array(arr, copy=True)
    frac = np.matmul(arr, np.linalg.inv(box))
    frac -= np.round(frac)
    return np.matmul(frac, box)


def select_periodic_image_for_projection(
    delta_nm: Sequence[float],
    box_matrix_nm: np.ndarray | None,
    direction_vec: Sequence[float],
    reference_xi_nm: float | None,
    image_shell: int = 2,
) -> tuple[float, np.ndarray]:
    delta = np.asarray(delta_nm, dtype=float)
    direction = np.asarray(direction_vec, dtype=float)
    norm = np.linalg.norm(direction)
    if norm < 1e-12:
        raise ValueError("direction_vec has zero norm")
    direction = direction / norm

    if box_matrix_nm is None:
        return float(np.dot(delta, direction)), delta.copy()

    box = np.asarray(box_matrix_nm, dtype=float)
    if box.shape == (3,):
        box = np.diag(box)
    base = minimum_image_displacement(delta, box)
    if reference_xi_nm is None:
        return float(np.dot(base, direction)), base

    best_xi = None
    best_delta = None
    best_error = float("inf")
    for ia in range(-image_shell, image_shell + 1):
        for ib in range(-image_shell, image_shell + 1):
            for ic in range(-image_shell, image_shell + 1):
                candidate = base + ia * box[0] + ib * box[1] + ic * box[2]
                xi = float(np.dot(candidate, direction))
                error = abs(xi - float(reference_xi_nm))
                if error < best_error:
                    best_error = error
                    best_xi = xi
                    best_delta = candidate
    return float(best_xi), np.asarray(best_delta, dtype=float)


def finite_energy_and_positions(simulation: Any) -> tuple[bool, dict[str, float]]:
    try:
        from openmm import unit

        state = simulation.context.getState(getEnergy=True, getPositions=True)
        pe = float(
            state.getPotentialEnergy().value_in_unit(unit.kilojoule_per_mole)
        )
        ke = float(state.getKineticEnergy().value_in_unit(unit.kilojoule_per_mole))
        pos = np.asarray(
            state.getPositions(asNumpy=True).value_in_unit(unit.nanometer), dtype=float
        )
        ok = np.isfinite(pe) and np.isfinite(ke) and np.isfinite(pos).all()
        return bool(ok), {"potential_kj_mol": pe, "kinetic_kj_mol": ke}
    except Exception:
        return False, {}


def assign_force_groups(system: Any) -> dict[int, str]:
    mapping: dict[int, str] = {}
    used: set[int] = set()
    next_group = 0
    for force in system.getForces():
        while next_group in used and next_group < 32:
            next_group += 1
        if next_group >= 32:
            break
        force.setForceGroup(next_group)
        mapping[next_group] = force.__class__.__name__
        used.add(next_group)
        next_group += 1
    return mapping


def force_group_energies_kj_mol(
    context: Any, force_group_map: Mapping[int, str]
) -> dict[str, float]:
    from openmm import unit

    out: dict[str, float] = {}
    for group, name in force_group_map.items():
        state = context.getState(getEnergy=True, groups=1 << int(group))
        value = float(
            state.getPotentialEnergy().value_in_unit(unit.kilojoule_per_mole)
        )
        out[f"{group:02d}_{name}"] = value
    return out


def _finite_1d(samples: Sequence[float], min_samples: int = 4) -> np.ndarray:
    x = np.asarray(samples, dtype=float).reshape(-1)
    x = x[np.isfinite(x)]
    if x.size < min_samples:
        raise SamplingQualityError(
            f"Too few finite samples: {x.size}; required at least {min_samples}"
        )
    return x


def _fallback_statistical_inefficiency(samples: Sequence[float]) -> float:
    x = _finite_1d(samples, min_samples=8)
    x = x - np.mean(x)
    n = len(x)
    var = float(np.dot(x, x) / n)
    if var <= np.finfo(float).eps:
        return float(n)
    nfft = 1 << (2 * n - 1).bit_length()
    fft = np.fft.rfft(x, n=nfft)
    acf = np.fft.irfft(fft * np.conjugate(fft), n=nfft)[:n]
    acf /= np.arange(n, 0, -1)
    acf /= acf[0]
    positive = []
    for value in acf[1:]:
        if not np.isfinite(value) or value <= 0:
            break
        positive.append(float(value))
    return float(np.clip(1.0 + 2.0 * np.sum(positive), 1.0, n))


def detect_equilibration(
    samples: Sequence[float],
    maximum_discard_fraction: float = 0.80,
) -> tuple[int, float, float]:
    x = _finite_1d(samples, min_samples=20)
    max_start = max(0, min(len(x) - 8, int(len(x) * maximum_discard_fraction)))
    try:
        from pymbar import timeseries

        t0, g, neff = timeseries.detect_equilibration(x, fast=True)
        t0 = int(min(max(int(t0), 0), max_start))
        tail = x[t0:]
        g = float(timeseries.statistical_inefficiency(tail, fast=True))
        return t0, max(g, 1.0), float(len(tail) / max(g, 1.0))
    except Exception:
        candidates = np.unique(
            np.linspace(0, max_start, min(30, max_start + 1)).astype(int)
        )
        best = (0, float("inf"), 0.0)
        for t0 in candidates:
            tail = x[int(t0) :]
            if len(tail) < 8:
                continue
            g = _fallback_statistical_inefficiency(tail)
            neff = len(tail) / g
            if neff > best[2]:
                best = (int(t0), float(g), float(neff))
        return best


def subsample_uncorrelated(samples: Sequence[float], g: float) -> np.ndarray:
    x = _finite_1d(samples, min_samples=4)
    try:
        from pymbar import timeseries

        indices = timeseries.subsample_correlated_data(x, g=float(max(g, 1.0)))
        return x[np.asarray(indices, dtype=int)]
    except Exception:
        stride = max(1, int(math.ceil(max(float(g), 1.0))))
        return x[::stride]


def prepare_window_samples(
    samples: Sequence[float],
    center_nm: float,
    *,
    min_effective_samples: float = 100.0,
    max_center_offset_nm: float = 0.10,
    max_drift_sigma: float = 0.50,
    maximum_discard_fraction: float = 0.80,
) -> tuple[np.ndarray, np.ndarray, WindowSamplingStats]:
    raw = _finite_1d(samples, min_samples=20)
    t0, g, neff = detect_equilibration(
        raw, maximum_discard_fraction=maximum_discard_fraction
    )
    eq = raw[t0:]
    uncorr = subsample_uncorrelated(eq, g)
    mean = float(np.mean(eq))
    sd = float(np.std(eq, ddof=1)) if len(eq) > 1 else 0.0
    half = max(1, len(eq) // 2)
    drift = abs(float(np.mean(eq[-half:]) - np.mean(eq[:half])))
    offset = abs(mean - float(center_nm))
    reasons: list[str] = []
    if neff < min_effective_samples:
        reasons.append(f"Neff={neff:.1f}<{min_effective_samples:.1f}")
    if offset > max_center_offset_nm:
        reasons.append(
            f"center offset={offset:.4f} nm>{max_center_offset_nm:.4f} nm"
        )
    if sd <= 1e-10:
        reasons.append("coordinate variance is effectively zero")
    elif drift > max_drift_sigma * sd:
        reasons.append(f"drift={drift:.4f} nm>{max_drift_sigma:.2f} SD")
    stats = WindowSamplingStats(
        center_nm=float(center_nm),
        n_raw=int(len(raw)),
        equilibration_index=int(t0),
        n_equilibrated=int(len(eq)),
        statistical_inefficiency=float(g),
        n_effective=float(neff),
        n_uncorrelated=int(len(uncorr)),
        mean_nm=mean,
        sd_nm=sd,
        drift_nm=drift,
        center_offset_nm=offset,
        status="pass" if not reasons else "extend",
        reasons=reasons,
    )
    return eq, uncorr, stats


def overlap_coefficient(
    samples_a: Sequence[float],
    samples_b: Sequence[float],
    bins: int | str = "fd",
) -> float:
    a = _finite_1d(samples_a, min_samples=8)
    b = _finite_1d(samples_b, min_samples=8)
    pooled = np.concatenate([a, b])
    if bins == "fd":
        edges = np.histogram_bin_edges(pooled, bins="fd")
        if len(edges) < 8:
            edges = np.linspace(float(pooled.min()), float(pooled.max()), 31)
        elif len(edges) > 501:
            edges = np.linspace(float(pooled.min()), float(pooled.max()), 501)
    else:
        edges = np.linspace(float(pooled.min()), float(pooled.max()), int(bins) + 1)
    if len(edges) < 2 or edges[-1] <= edges[0]:
        return 0.0
    ha, _ = np.histogram(a, bins=edges, density=True)
    hb, _ = np.histogram(b, bins=edges, density=True)
    value = np.sum(np.minimum(ha, hb) * np.diff(edges))
    return float(np.clip(value, 0.0, 1.0))


def standardized_gap(samples_a: Sequence[float], samples_b: Sequence[float]) -> float:
    a = _finite_1d(samples_a, min_samples=8)
    b = _finite_1d(samples_b, min_samples=8)
    pooled_sd = math.sqrt(
        max(
            0.5 * (float(np.var(a, ddof=1)) + float(np.var(b, ddof=1))),
            np.finfo(float).eps,
        )
    )
    return abs(float(np.mean(a) - np.mean(b))) / pooled_sd


def _connected_from_pair_overlaps(
    centers: Sequence[float],
    pair_stats: Sequence[PairSamplingStats],
    minimum_overlap: float,
) -> bool:
    if len(centers) <= 1:
        return True
    adjacency = {float(c): set() for c in centers}
    for pair in pair_stats:
        if pair.overlap_coefficient >= minimum_overlap:
            adjacency[pair.left_center_nm].add(pair.right_center_nm)
            adjacency[pair.right_center_nm].add(pair.left_center_nm)
    start = float(centers[0])
    visited = {start}
    stack = [start]
    while stack:
        node = stack.pop()
        for nxt in adjacency[node]:
            if nxt not in visited:
                visited.add(nxt)
                stack.append(nxt)
    return len(visited) == len(centers)


def assess_umbrella_samples(
    samples_by_center: Mapping[float, Sequence[float]],
    *,
    target_overlap: float = 0.20,
    minimum_overlap: float = 0.10,
    min_effective_samples: float = 100.0,
    max_center_offset_nm: float = 0.10,
    max_drift_sigma: float = 0.50,
) -> tuple[UmbrellaQualityReport, dict[float, np.ndarray], dict[float, np.ndarray]]:
    if not 0.0 < minimum_overlap <= target_overlap <= 1.0:
        raise ValueError("Require 0 < minimum_overlap <= target_overlap <= 1")
    centers = sorted(float(c) for c in samples_by_center)
    if len(centers) < 3:
        raise SamplingQualityError("At least three umbrella windows are required")

    equilibrated: dict[float, np.ndarray] = {}
    uncorrelated: dict[float, np.ndarray] = {}
    window_stats: list[WindowSamplingStats] = []
    failures: list[str] = []
    warnings: list[str] = []
    extend_centers: list[float] = []

    for center in centers:
        eq, uncorr, stats = prepare_window_samples(
            samples_by_center[center],
            center,
            min_effective_samples=min_effective_samples,
            max_center_offset_nm=max_center_offset_nm,
            max_drift_sigma=max_drift_sigma,
        )
        equilibrated[center] = eq
        uncorrelated[center] = uncorr
        window_stats.append(stats)
        if stats.status != "pass":
            extend_centers.append(center)
            failures.append(
                f"Window {center:.4f} nm requires more sampling: "
                + "; ".join(stats.reasons)
            )

    pair_stats: list[PairSamplingStats] = []
    insert_centers: list[float] = []
    for left, right in zip(centers[:-1], centers[1:]):
        overlap = overlap_coefficient(equilibrated[left], equilibrated[right])
        gap = standardized_gap(equilibrated[left], equilibrated[right])
        midpoint = 0.5 * (left + right)
        if overlap < minimum_overlap:
            action = "insert"
            insert_centers.append(midpoint)
            failures.append(
                f"Adjacent windows {left:.4f}/{right:.4f} nm have "
                f"overlap={overlap:.3f}<{minimum_overlap:.3f}"
            )
            proposal = midpoint
        elif overlap < target_overlap:
            action = "extend_or_insert"
            insert_centers.append(midpoint)
            warnings.append(
                f"Adjacent windows {left:.4f}/{right:.4f} nm have marginal "
                f"overlap={overlap:.3f}"
            )
            proposal = midpoint
        else:
            action = "accept"
            proposal = None
        pair_stats.append(
            PairSamplingStats(
                left_center_nm=left,
                right_center_nm=right,
                overlap_coefficient=overlap,
                standardized_gap=gap,
                action=action,
                proposed_center_nm=proposal,
            )
        )

    connected = _connected_from_pair_overlaps(centers, pair_stats, minimum_overlap)
    if not connected:
        failures.append("The umbrella overlap graph is disconnected")

    report = UmbrellaQualityReport(
        passed=(not failures) and connected,
        graph_connected=connected,
        window_stats=window_stats,
        pair_stats=pair_stats,
        extend_centers_nm=sorted(set(extend_centers)),
        insert_centers_nm=sorted(set(insert_centers)),
        failures=failures,
        warnings=warnings,
    )
    return report, equilibrated, uncorrelated


def quality_report_to_dict(report: UmbrellaQualityReport) -> dict[str, Any]:
    return {
        "passed": report.passed,
        "graph_connected": report.graph_connected,
        "window_stats": [dataclasses.asdict(x) for x in report.window_stats],
        "pair_stats": [dataclasses.asdict(x) for x in report.pair_stats],
        "extend_centers_nm": report.extend_centers_nm,
        "insert_centers_nm": report.insert_centers_nm,
        "failures": report.failures,
        "warnings": report.warnings,
    }


def _logsumexp(a: np.ndarray, axis: int | None = None) -> np.ndarray:
    arr = np.asarray(a, dtype=float)
    amax = np.max(arr, axis=axis, keepdims=True)
    amax[~np.isfinite(amax)] = 0.0
    out = np.log(np.sum(np.exp(arr - amax), axis=axis, keepdims=True)) + amax
    if axis is not None:
        out = np.squeeze(out, axis=axis)
    return out


def stable_wham_1d(
    sample_lists: Sequence[Sequence[float]],
    centers_nm: Sequence[float],
    force_constant_kj_mol_nm2: float,
    temperature_K: float,
    *,
    bins: int = 200,
    tolerance: float = 1e-8,
    maximum_iterations: int = 50000,
    x_min: float | None = None,
    x_max: float | None = None,
) -> dict[str, Any]:
    samples = [_finite_1d(x, min_samples=4) for x in sample_lists]
    centers = np.asarray(centers_nm, dtype=float)
    if len(samples) != len(centers):
        raise ValueError("sample_lists and centers_nm must have the same length")
    if len(samples) < 2:
        raise SamplingQualityError("WHAM requires at least two windows")

    pooled = np.concatenate(samples)
    if x_min is None:
        x_min = float(np.min(pooled)) - 0.05
    if x_max is None:
        x_max = float(np.max(pooled)) + 0.05
    if x_max <= x_min:
        raise ValueError("Invalid WHAM coordinate range")

    edges = np.linspace(float(x_min), float(x_max), int(bins) + 1)
    grid = 0.5 * (edges[:-1] + edges[1:])
    dx = float(edges[1] - edges[0])
    K = len(samples)
    hist = np.vstack([np.histogram(x, bins=edges)[0] for x in samples]).astype(float)
    N_k = np.array([len(x) for x in samples], dtype=float)
    beta = 1.0 / (KB_KJ_MOL_K * float(temperature_K))
    u_kl = (
        beta
        * 0.5
        * float(force_constant_kj_mol_nm2)
        * (grid[None, :] - centers[:, None]) ** 2
    )

    f_k = np.zeros(K, dtype=float)
    total_hist = np.sum(hist, axis=0)
    log_total_hist = np.full_like(total_hist, -np.inf, dtype=float)
    nonzero = total_hist > 0
    log_total_hist[nonzero] = np.log(total_hist[nonzero])
    logN = np.log(np.maximum(N_k, 1.0))
    converged = False

    for iteration in range(int(maximum_iterations)):
        log_denom = _logsumexp(logN[:, None] + f_k[:, None] - u_kl, axis=0)
        log_p = log_total_hist - log_denom
        log_p[~nonzero] = -np.inf
        log_norm = float(_logsumexp(log_p + math.log(dx), axis=0))
        log_p -= log_norm

        f_new = -_logsumexp(log_p[None, :] - u_kl + math.log(dx), axis=1)
        f_new -= f_new[0]
        delta = float(np.max(np.abs(f_new - f_k)))
        f_k = f_new
        if delta < tolerance:
            converged = True
            break

    probability_density = np.zeros_like(grid)
    probability_density[nonzero] = np.exp(log_p[nonzero])
    pmf = np.full_like(grid, np.nan, dtype=float)
    pmf[nonzero] = -log_p[nonzero] / beta
    pmf[nonzero] -= np.nanmin(pmf[nonzero])

    return {
        "grid_nm": grid,
        "pmf_kj_mol": pmf,
        "probability_density": probability_density,
        "histogram_matrix": hist,
        "edges_nm": edges,
        "f_k_dimensionless": f_k,
        "converged": converged,
        "iterations": iteration + 1,
        "method": "log-space-WHAM",
        "overlap_matrix": None,
    }


def mbar_pmf_1d(
    uncorrelated_sample_lists: Sequence[Sequence[float]],
    centers_nm: Sequence[float],
    force_constant_kj_mol_nm2: float,
    temperature_K: float,
    *,
    bins: int = 200,
    x_min: float | None = None,
    x_max: float | None = None,
) -> dict[str, Any]:
    from pymbar import MBAR

    samples = [_finite_1d(x, min_samples=4) for x in uncorrelated_sample_lists]
    centers = np.asarray(centers_nm, dtype=float)
    if len(samples) != len(centers):
        raise ValueError("sample_lists and centers_nm must have the same length")
    x_n = np.concatenate(samples)
    N_k = np.asarray([len(x) for x in samples], dtype=int)
    beta = 1.0 / (KB_KJ_MOL_K * float(temperature_K))
    u_kn = (
        beta
        * 0.5
        * float(force_constant_kj_mol_nm2)
        * (x_n[None, :] - centers[:, None]) ** 2
    )
    mbar = MBAR(
        u_kn,
        N_k,
        maximum_iterations=20000,
        relative_tolerance=1e-10,
        verbose=False,
    )

    f_k = np.asarray(mbar.f_k, dtype=float)
    logN = np.full(len(N_k), -np.inf, dtype=float)
    positive = N_k > 0
    logN[positive] = np.log(N_k[positive])
    log_denom = _logsumexp(logN[:, None] + f_k[:, None] - u_kn, axis=0)
    log_weights = -log_denom
    log_weights -= float(_logsumexp(log_weights, axis=0))
    weights = np.exp(log_weights)

    if x_min is None:
        x_min = float(np.min(x_n)) - 0.05
    if x_max is None:
        x_max = float(np.max(x_n)) + 0.05
    edges = np.linspace(float(x_min), float(x_max), int(bins) + 1)
    grid = 0.5 * (edges[:-1] + edges[1:])
    weighted_counts, _ = np.histogram(x_n, bins=edges, weights=weights)
    dx = float(edges[1] - edges[0])
    density = weighted_counts / max(float(np.sum(weighted_counts)) * dx, 1e-300)
    valid = density > 0
    pmf = np.full_like(grid, np.nan, dtype=float)
    pmf[valid] = -np.log(density[valid]) / beta
    pmf[valid] -= np.nanmin(pmf[valid])

    overlap_result = mbar.compute_overlap()
    overlap_matrix = np.asarray(overlap_result["matrix"], dtype=float)
    hist = np.vstack([np.histogram(x, bins=edges)[0] for x in samples]).astype(float)
    return {
        "grid_nm": grid,
        "pmf_kj_mol": pmf,
        "probability_density": density,
        "histogram_matrix": hist,
        "edges_nm": edges,
        "f_k_dimensionless": f_k,
        "converged": True,
        "iterations": None,
        "method": "PyMBAR-MBAR",
        "overlap_matrix": overlap_matrix,
        "mbar_overlap_scalar": float(overlap_result["scalar"]),
        "mbar_overlap_eigenvalues": np.asarray(
            overlap_result["eigenvalues"], dtype=float
        ),
    }


def estimate_pmf_1d(
    equilibrated_sample_lists: Sequence[Sequence[float]],
    uncorrelated_sample_lists: Sequence[Sequence[float]],
    centers_nm: Sequence[float],
    force_constant_kj_mol_nm2: float,
    temperature_K: float,
    *,
    bins: int = 200,
    prefer_mbar: bool = True,
    x_min: float | None = None,
    x_max: float | None = None,
) -> dict[str, Any]:
    if prefer_mbar:
        try:
            return mbar_pmf_1d(
                uncorrelated_sample_lists,
                centers_nm,
                force_constant_kj_mol_nm2,
                temperature_K,
                bins=bins,
                x_min=x_min,
                x_max=x_max,
            )
        except Exception as exc:
            result = stable_wham_1d(
                equilibrated_sample_lists,
                centers_nm,
                force_constant_kj_mol_nm2,
                temperature_K,
                bins=bins,
                x_min=x_min,
                x_max=x_max,
            )
            result["fallback_reason"] = repr(exc)
            return result
    return stable_wham_1d(
        equilibrated_sample_lists,
        centers_nm,
        force_constant_kj_mol_nm2,
        temperature_K,
        bins=bins,
        x_min=x_min,
        x_max=x_max,
    )


def _moving_block_resample(
    x: np.ndarray, block_length: int, rng: np.random.Generator
) -> np.ndarray:
    x = _finite_1d(x, min_samples=4)
    n = len(x)
    block_length = max(1, min(int(block_length), n))
    n_blocks = int(math.ceil(n / block_length))
    starts = rng.integers(0, n, size=n_blocks)
    out = []
    for start in starts:
        indices = (np.arange(block_length) + int(start)) % n
        out.append(x[indices])
    return np.concatenate(out)[:n]


def bootstrap_pmf_1d(
    equilibrated_sample_lists: Sequence[Sequence[float]],
    centers_nm: Sequence[float],
    force_constant_kj_mol_nm2: float,
    temperature_K: float,
    *,
    bins: int = 200,
    n_bootstrap: int = 100,
    seed: int = 20260423,
    prefer_mbar: bool = True,
) -> dict[str, Any]:
    eq_lists = [_finite_1d(x, min_samples=20) for x in equilibrated_sample_lists]
    prepared_uncorr = []
    block_lengths = []
    for x in eq_lists:
        g = _fallback_statistical_inefficiency(x)
        prepared_uncorr.append(subsample_uncorrelated(x, g))
        block_lengths.append(max(1, int(math.ceil(g))))

    base = estimate_pmf_1d(
        eq_lists,
        prepared_uncorr,
        centers_nm,
        force_constant_kj_mol_nm2,
        temperature_K,
        bins=bins,
        prefer_mbar=prefer_mbar,
    )
    grid = np.asarray(base["grid_nm"], dtype=float)
    if len(grid) < 2:
        raise SamplingQualityError("PMF grid has fewer than two points")
    half_dx = 0.5 * float(grid[1] - grid[0])
    rng = np.random.default_rng(int(seed))
    boot_pmfs: list[np.ndarray] = []

    for _ in range(int(n_bootstrap)):
        resampled_eq = [
            _moving_block_resample(x, block, rng)
            for x, block in zip(eq_lists, block_lengths)
        ]
        resampled_uncorr = []
        for x in resampled_eq:
            g = _fallback_statistical_inefficiency(x)
            resampled_uncorr.append(subsample_uncorrelated(x, g))
        try:
            result = estimate_pmf_1d(
                resampled_eq,
                resampled_uncorr,
                centers_nm,
                force_constant_kj_mol_nm2,
                temperature_K,
                bins=bins,
                prefer_mbar=prefer_mbar,
                x_min=float(grid.min() - half_dx),
                x_max=float(grid.max() + half_dx),
            )
            pmf = np.asarray(result["pmf_kj_mol"], dtype=float)
            if len(pmf) == len(grid):
                boot_pmfs.append(pmf)
        except Exception:
            continue

    if boot_pmfs:
        arr = np.vstack(boot_pmfs)
        all_nan = np.all(~np.isfinite(arr), axis=0)
        safe_arr = np.array(arr, copy=True)
        safe_arr[:, all_nan] = 0.0
        ci_low = np.nanpercentile(safe_arr, 2.5, axis=0)
        ci_high = np.nanpercentile(safe_arr, 97.5, axis=0)
        base_pmf = np.asarray(base["pmf_kj_mol"], dtype=float)
        ci_low[all_nan] = base_pmf[all_nan]
        ci_high[all_nan] = base_pmf[all_nan]
        bootstrap_success = len(boot_pmfs)
    else:
        ci_low = np.asarray(base["pmf_kj_mol"], dtype=float).copy()
        ci_high = ci_low.copy()
        bootstrap_success = 0

    base["ci95_low_kj_mol"] = ci_low
    base["ci95_high_kj_mol"] = ci_high
    base["bootstrap_success"] = int(bootstrap_success)
    base["bootstrap_requested"] = int(n_bootstrap)
    base["bootstrap_method"] = "moving-block"
    base["bootstrap_pmfs"] = np.vstack(boot_pmfs) if boot_pmfs else None   # per-replicate curves (for derived σ)
    return base


def aligned_pmf_rmse(
    pmf_a: Sequence[float],
    pmf_b: Sequence[float],
    mask: Sequence[bool] | None = None,
) -> float:
    """
    比較兩條只差任意能量常數的 PMF。先以共同有限區域的平均差校正
    能量零點，再計算 RMSE。
    """
    a = np.asarray(pmf_a, dtype=float)
    b = np.asarray(pmf_b, dtype=float)
    if a.shape != b.shape:
        raise ValueError("PMF arrays must have the same shape")
    valid = np.isfinite(a) & np.isfinite(b)
    if mask is not None:
        m = np.asarray(mask, dtype=bool)
        if m.shape != a.shape:
            raise ValueError("mask must have the same shape as PMF arrays")
        valid &= m
    if np.count_nonzero(valid) < 3:
        return float("nan")
    delta = a[valid] - b[valid]
    delta -= float(np.mean(delta))
    return float(np.sqrt(np.mean(delta ** 2)))

def pmf_half_split_rmse(
    first_pmf: Sequence[float], second_pmf: Sequence[float]
) -> float:
    a = np.asarray(first_pmf, dtype=float)
    b = np.asarray(second_pmf, dtype=float)
    valid = np.isfinite(a) & np.isfinite(b)
    if not np.any(valid):
        return float("nan")
    a = a[valid] - np.nanmin(a[valid])
    b = b[valid] - np.nanmin(b[valid])
    return float(np.sqrt(np.mean((a - b) ** 2)))


def archive_stale_directory(directory: str | Path, reason: str) -> Path | None:
    directory = Path(directory)
    if not directory.exists() or not any(directory.iterdir()):
        return None
    archive_root = directory.parent / "_stale_runs"
    archive_root.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    target = archive_root / f"{directory.name}_{stamp}"
    suffix = 1
    while target.exists():
        target = archive_root / f"{directory.name}_{stamp}_{suffix}"
        suffix += 1
    os.replace(directory, target)
    target.mkdir(parents=True, exist_ok=True)
    atomic_write_text(target / "STALE_REASON.txt", str(reason))
    return target


def environment_manifest(extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    import importlib.metadata

    packages = {}
    for name in (
        "openmm",
        "mdtraj",
        "MDAnalysis",
        "pymbar",
        "numpy",
        "pandas",
        "scipy",
        "parmed",
    ):
        try:
            packages[name] = importlib.metadata.version(name)
        except Exception:
            packages[name] = None
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "python": _py_platform.python_version(),
        "platform": _py_platform.platform(),
        "machine": _py_platform.machine(),
        "packages": packages,
        "openmm_platforms": available_openmm_platforms(),
        "created_unix": time.time(),
    }
    if extra:
        manifest["extra"] = dict(extra)
    return manifest
