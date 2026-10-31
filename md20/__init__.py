"""MD20 teaching workstation.

Package layout
--------------
md20.util      cross-platform helpers (paths, atomic JSON, locks, cheap hashes, decision log)
md20.env       Doctor: hardware probe, OpenMM platform ladder, benchmark
md20.project   on-disk project / case / run store (replaces Google-Drive JSON + lease)
md20.build     receptor cleanup, ligand parameter ladder, system assembly, three-state gates
md20.engine    resumable chunked MD engine with a backend abstraction (OpenMM or Fake)
md20.analysis  log parsing, acceptance tests, automatic figures
md20.cli       command-line entry point (`md20 ...`)

Design rules (from the project spec):
1. One source of truth for chemistry (RDKit mol + original mmCIF); PDB is a coordinate carrier only.
2. Every automatic decision is written to the decision log with a reason.
3. Gates have three outcomes: PASS / AUTO_FIXED (with diff) / NEEDS_HUMAN (plain-language explanation).
4. Small before big: cheap smoke tests precede expensive steps.
"""

__version__ = "0.1.0a0"
