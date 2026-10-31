# Spec: `md20.docking` (port of MD20 v6.1 Project 1, Phases 2–10)

Goal: AutoDock Vina docking inside the md20 package, feeding `md20.build` directly, with the two
original modes and smart pose selection. Pure Python + `vina` (python package) + `meeko` + RDKit.
Everything must degrade gracefully when `vina`/`meeko` are missing (clear NEEDS_HUMAN gate, no crash).

## Modules (create under `md20/docking/`)
1. `ligands.py` — `prepare_ligands(sources: list[str|Path], out_dir, *, ph=7.4, seed=2026) -> list[DockLigand]`
   - sources: SDF/MOL/SMILES file lines or raw SMILES strings. Keep largest fragment, AddHs, ETKDG + MMFF.
   - Peptide auto-detect (≥2 amide bonds and ≥15 heavy atoms) → flag `is_peptide`.
   - Write `<name>.sdf` (reference chemistry, the single source of truth) and `<name>.pdbqt` via Meeko
     (`meeko.MoleculePreparation` + `PDBQTWriterLegacy`); record formal charge, MW, rotatable bonds, HBA/HBD.
   - Returns dataclass with paths + descriptors; `gates` dict in the same three-state style as `md20.build.gates`.
2. `receptor.py` — `prepare_receptor_pdbqt(receptor_pdb, out_dir) -> dict`
   - Use `md20.build.receptor.prepare_receptor` first (clean PDB, hydrogens at pH), then Meeko
     `mk_prepare_receptor` python API if available, else Open Babel CLI if on PATH, else NEEDS_HUMAN.
   - Output `receptor.pdbqt`, plus `receptor_clean.pdb` reused by MD (same file → no divergence).
3. `box.py` — `define_box(receptor_pdb, *, mode, center=None, size=None, reference_ligand_pdb=None, padding=4.0)`
   - modes: `manual`, `reference` (box around a reference ligand's heavy atoms + padding Å),
     `whole_receptor` (blind docking). Returns dict center/size (Å) and a short reason string.
4. `vina_runner.py` — `dock(receptor_pdbqt, ligands: list[DockLigand], box, out_dir, *, mode="independent"|"simultaneous",
   scoring="vina"|"vinardo", exhaustiveness=8, num_modes=9, energy_range=3.0, seed=2026, cpu=0) -> DockingResult`
   - `independent`: each ligand docked alone → per-ligand pose list.
   - `simultaneous`: all ligands set together (`Vina.set_ligand_from_file(list)`), poses are **joint poses**;
     split the multi-ligand output PDBQT into per-ligand blocks per MODEL while keeping `joint_pose_id`.
   - Use the `vina` python API (`from vina import Vina`); write `*_out.pdbqt`, parse scores (`v.energies()`),
     save `docking_scores.csv` (ligand, pose_id, joint_pose_id, affinity, rmsd_lb, rmsd_ub).
   - Resumable: skip ligands with existing outputs unless `overwrite=True`.
5. `poses.py` — `split_poses(out_pdbqt, ligand: DockLigand, out_dir) -> list[Pose]`
   - PDBQT pose → SDF via Meeko `PDBQTMolecule` + `RDKitMolCreate` (keeps bond orders from the reference).
   - Each `Pose` has: sdf path, affinity, pose_id, joint_pose_id, heavy-atom centroid, `contacts` (# receptor heavy
     atoms within 4 Å), `rmsd_to_reference` (if reference ligand given).
6. `select.py` — `recommend_poses(result, *, mode) -> Selection`
   - independent: per ligand, recommend best affinity unless a lower-ranked pose has ≥30 % more contacts and
     within 0.5 kcal/mol (explain). Reason string per ligand (teaching).
   - simultaneous: recommend the joint pose with best total affinity whose ligands have no inter-ligand clash
     (<1.5 Å heavy-atom distance). All ligands must share one `joint_pose_id`; `validate_selection()` raises a
     readable error on mixed joint ids.
   - `Selection.to_dict()` is what the GUI/CLI persists; user overrides go through `override(ligand, pose_id)`.
7. `handoff.py` — `to_md_inputs(selection, receptor_clean_pdb) -> dict` returning what `md20.build.pipeline.build_case`
   needs: `receptor`, `ligand_references` (the reference SDFs), `ligand_poses` (selected pose SDFs), mode.
8. `md20/docking/__init__.py` exports; CLI subcommands in `md20/cli.py`: `md20 dock prepare|box|run|poses|select`
   (keep the existing CLI structure; add a `dock` sub-parser with sub-actions).

## Tests (`tests/test_docking.py`)
- Pure-Python tests that run **without vina/meeko/rdkit**: box geometry math (reference/whole_receptor), score CSV
  parsing from a fixture string, pose selection logic with synthetic `Pose` objects (independent + simultaneous,
  including the clash and joint-id validation), and the PDBQT MODEL splitter on a fixture text.
- Integration tests guarded by `pytest.importorskip("vina")`, `importorskip("meeko")`, `importorskip("rdkit")`:
  dock benzamidine into trypsin from `tests/data/3ptb_pocket.pdb` IF that file exists (it may be added later);
  otherwise skip.

## Rules
- Follow the package conventions: `from __future__ import annotations`, dataclasses, `md20.util.atomic_write_json`,
  `md20.util.DecisionLog` for every automatic choice (record with a Traditional-Chinese `why`).
- No Colab/Drive/ipywidgets. No `fcntl`. Paths via `pathlib`. Windows-safe file names (`md20.util.safe_name`).
- Lazy-import vina/meeko/rdkit inside functions so `import md20.docking` never fails.
- Keep user-facing messages in Traditional Chinese; identifiers in English.
- Run `python -m pytest -q` before finishing; all existing tests must still pass.
