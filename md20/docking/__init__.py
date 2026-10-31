"""Docking (port of MD20 v6.1 Project 1, Phases 2–9) — Windows-first, no OpenBabel dependency.

Modes (same as the original notebook):
  independent   every receptor × every ligand (HTS ranking)
  simultaneous  several ligands docked together into one box (co-occupancy mechanism, joint poses)

Pipeline: receptor PDBQT (own writer) → ligand PDBQT (Meeko) → Vina/Vinardo → poses back to RDKit via
Meeko (bond orders preserved) → pose analysis + recommendation with reasons → pose SDFs ready for MD.
"""
from .receptor_pdbqt import receptor_to_pdbqt, ad4_type
from .box import Box, box_from_coords, box_from_pdb_residue, box_whole_receptor
from .poses import PoseInfo, analyse_poses, recommend_pose, cluster_poses
from .run import dock, DockingResult, LigandInput

__all__ = ["receptor_to_pdbqt", "ad4_type", "Box", "box_from_coords", "box_from_pdb_residue", "box_whole_receptor",
           "PoseInfo", "analyse_poses", "recommend_pose", "cluster_poses", "dock", "DockingResult", "LigandInput"]
