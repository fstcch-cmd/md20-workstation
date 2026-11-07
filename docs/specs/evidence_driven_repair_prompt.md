# MD20: Evidence-Driven Repair and Next-Generation Development

## Role, scope, and objective

Act as the lead MD scientist, scientific-software architect, and verification engineer for MD20.

Repository: https://github.com/fstcch-cmd/md20-workstation

Historical audit baseline: f3ecf7178052025c8b3898af0a667f170c090350, inspected on 2026-11-07.

This prompt requests implementation and verification, not another feature wishlist. Start by reconciling the findings with the current LOCAL checkout, which may be newer than the audited GitHub snapshot. Preserve working features and user changes. Treat all baseline findings as dated evidence to verify, not proof that the latest code still contains every defect.

The near-term goal is a reproducible research workstation with defensible scientific interpretation. The long-term goal is a bounded-autonomous molecular-research platform that can select justified next actions, communicate uncertainty, and generate coherent reports.

Keep the platform general-purpose. Treat fermentation metabolites, functional-food compounds, and bioactive peptides as an important application profile, not a reason to remove other supported workflows.

Do not change repository visibility, publish releases, push commits, access unrelated repositories, upload research data, introduce paid services, or start substantial simulations without explicit authorization. Local code changes and lightweight tests within the approved development scope may proceed. Preserve dirty worktrees and raw results. Do not reset or overwrite user work.

Before each substantial stage, briefly state what you will change, why, and how you will verify it. Proceed with safe implementation after presenting the plan; pause only for material scientific choices, missing authority, or resource commitments.

## 1. Establish the current truth

Inspect repository instructions, current branch/commit, uncommitted changes, configuration, dependencies, workflow code, tests, report generation, release metadata, and available CI evidence. Read STATUS, HANDOFF, WORKBOARD, and relevant specifications, but resolve their cumulative or contradictory statements against current code and test artifacts.

For each finding, classify it as:

- Still reproducible.
- Partially fixed.
- Already fixed.
- Unverified.
- Superseded.

Record the current file/function, reproduction or evidence, consequence, proposed fix, and regression test. Do not attribute an old implementation to the present branch without checking.

Distinguish these capability states:

1. Implemented in source.
2. Tested with synthetic/mocked data.
3. Tested with a real engine.
4. Scientifically benchmarked for a specified use.
5. Included in a released installer.

Do not equate these states or infer a completion percentage from commit/test counts.

At the audit baseline, a17 was the latest actual prerelease; package/README information referenced a19, while development notes described unreleased a20 changes. The preceding completed CI had 14 of 15 jobs successful and a metal-geometry failure. The audited latest CI was still running and already had a metal failure. Refresh these facts rather than copying them as current status.

## 2. Preserve what already works

The audited version already contained Vina docking, OpenMM preparation/MD, restart support, SMD/umbrella/WHAM/MBAR analysis, bounded adaptive window insertion/extension, and automated reports.

Recent work also included scientific assessment, interaction fingerprints/persistence, common-basis PCA, mapped delta-RMSF, tICA/MSM qualifications, hydrogen-bond networks, hydration descriptors, candidate comparability, evidence matrices, independent GUI workers, live membrane-construction snapshots, and action/cost reporting.

Reuse these modules. Avoid parallel implementations, a second assessment engine, or a wholesale rewrite. The action-cost report is report-only; real adaptive execution exists separately in the binding workflow. Preserve that distinction.

## 3. Repair priorities: observation, reason, correction, acceptance

### R1 — Analyze all independent replicas

Baseline evidence:

- md20/workflow.py, Workflow.analyse, selected run_ids[0].
- Cross-system comparability/common-basis paths also selected the first run.

Why this matters:

A project can contain multiple simulations while its principal figures and conclusions describe only one. A favorable trajectory can conceal contradictory replicas. Frames, umbrella windows, and repeated pulls sharing one parent simulation are not independent replicas.

Required correction:

- Model case → independent MD replica → descendant pull/window lineage explicitly.
- Analyze every eligible replica separately and retain its identity.
- Aggregate only compatible observables using a declared estimand and justified weighting.
- Separate within-trajectory variability from between-replica uncertainty.
- Use autocorrelation-aware/block or hierarchical uncertainty methods where justified; do not present correlated frames as independent samples.
- Preserve failed, incomplete, and excluded replicas with reasons.
- Never concatenate replica boundaries for event durations or kinetic transitions.

Acceptance:

- Three deliberately divergent replicas remain visible and affect the summary.
- One replica yields unavailable between-replica uncertainty, not an invented interval.
- Several pulls from one parent do not increase the independent-replica count.
- Incompatible conditions block the affected comparison without suppressing unrelated valid analyses.

### R2 — Use one scientific assessment across every output

Baseline evidence:

md20/report/evidence.py could mark MD as supported from COMPLETE alone, and binding as supported from PASS plus a non-null delta-G. Other comparison paths used stricter scientific eligibility.

Why this matters:

Execution success is not scientific qualification. Contradictory badges, captions, rankings, and summaries can mislead readers.

Required correction:

- Separate execution status, diagnostic outcomes, claim eligibility, and comparison eligibility.
- Route the GUI, evidence matrix, captions, rankings, executive summary, exports, and action planner through the same versioned assessment.
- Record diagnostic values, units, thresholds, their justification, evidence IDs, unknowns, and overrides.
- Keep missing evidence unknown; never convert it to PASS.
- Scope eligibility to the claim: a trajectory may support a descriptive contact observation while failing an affinity claim.
- Treat human overrides as recorded decisions, not transformations of failed evidence into scientific validity.

Acceptance:

- Successful execution and a numerical delta-G with failed sampling cannot produce a supported affinity claim anywhere.
- Missing/legacy assessment requires explicit qualification or reanalysis.
- A disconnected statistical-overlap graph cannot be rescued by a solver-success flag or a visually smooth PMF.
- All four languages communicate identical restrictions.

### R3 — Separate scientific analysis resolution from plot resolution

Baseline evidence:

Memory-protection striding in md20/analysis/traj.py propagated into extended analysis. Common-basis inputs were capped at roughly 250 frames. Some persistence wording implied all stored frames were analyzed.

Why this matters:

Decimation can erase brief interruptions, merge contact events, distort populations, and hide transitions. Attractive plots cannot recover unobserved events.

Required correction:

- Separate source data, estimator inputs, and display-only downsampling.
- Stream applicable contact/event calculations at the original stored cadence.
- Carry event state across computational chunks, but respect physical gaps, restarts, and replica boundaries.
- Record source/effective cadence, stride, observation length, censoring, and resolution limitations.
- Expose and justify any PCA/clustering subsampling; evaluate representative sampling sensitivity rather than promising that a larger frame cap guarantees convergence.
- Qualify or withhold results that lack sufficient temporal resolution.

Acceptance:

- Changing plotting stride does not change full-resolution estimates.
- Chunked and unchunked implementations agree within declared tolerances.
- Tests cover short interruptions, irregular timestamps, gaps, left/right censoring, and replica boundaries.
- Contact persistence is never relabeled residence time or k_off.

### R4 — Version caches and migrate old results safely

Baseline evidence:

Analysis reuse was driven largely by a PASS manifest, allowing old results to omit newly introduced analysis/qualification fields.

Required correction:

- Introduce a dependency-aware analysis fingerprint covering relevant input hashes, topology/selections, protocol metadata, algorithm/schema versions, thresholds, and dependency-sensitive settings.
- Invalidate only affected descendants.
- Recompute analysis without unnecessarily rerunning MD.
- Preserve prior results and provenance; use atomic output replacement.
- Detect missing/replaced files rather than trusting paths.
- Support explicit migration or invalidation of legacy manifests.

Acceptance:

Unchanged inputs reuse results; relevant changes recompute the correct analyses; interrupted regeneration cannot replace a complete report with partial output; old reports remain distinguishable from newly validated results.

### R5 — Repair physical-model and diagnostic failures honestly

Metal baseline:

A zinc integration test reported HIS119–Zn near 2.324 angstrom against a 2.02 angstrom target, marginally outside its 0.30 angstrom tolerance.

Required correction:

Reproduce the failure and inspect atom mapping, histidine protonation, bonded terms, exclusions, competing nonbonded forces, and parameter provenance. Separate code defects from model inadequacy. Do not loosen thresholds, discard inconvenient frames, or reclassify a scientific failure as infrastructure merely to obtain green CI. Material changes to physical parameters/models need approval and documented validation.

Membrane baseline:

tools/diag_membrane_nan.py intentionally recorded failures and returned zero. That exit code is useful for collecting diagnostics but cannot prove scientific acceptance. Membrane construction/ion-water crowding remained under investigation.

Required correction:

- Preserve diagnostic collection and add a separate artifact validator.
- Check expected run counts, missing records, build errors, NaNs, and artifact completeness.
- Distinguish construction-seed from velocity-seed variation.
- Preserve regression cases for ion/water overlap and membrane-patch/added-water crowding.
- Do not remove structural metal ions through solvent-ion cleanup.
- Report observed failure counts under named protocols, not universal stability.

Also preserve chemically valid interaction definitions: donor/acceptor typing and hydrogen-bond geometry, charge-aware salt bridges, multi-label interactions, PBC-aware distances, and chain/insertion-code-aware residue identities. Unknown peptide charges must remain unknown, not silently neutral.

Acceptance:

The original cases become reproducible regression tests; missing artifacts fail validation; repeated real-engine checks use approved budgets; unresolved model limitations remain visible.

### R6 — Keep PMF, standard binding free energy, and advanced claims distinct

Required correction:

- Maintain a clear distinction between path-specific PMF, conditional co-occupancy results, and qualified standard-state binding free energy.
- Audit reaction-coordinate definition, Jacobian treatment where applicable, restraint geometry, accessible volume, standard state, endpoint behavior, orientation, overlap connectivity, effective samples, and replica sensitivity.
- Do not silently modify the physical protocol to make a standard delta-G appear.
- Implement new restraint/reference-state treatments only after an explicit method design, approval where required, and a suitable reference-system test.
- Never equate MBAR availability with a complete FEP/RBFE/ABFE workflow.
- Never infer mixture synergy from co-occupancy or sum docking scores as if they were thermodynamic free energies.

Advanced descriptors:

Keep current tICA/MSM exploratory until data, state discretization, lag-time sensitivity, transition coverage, and appropriate validation support stronger claims. A single trajectory is not automatically sufficient or automatically invalid; qualification must consider its sampling, while the current conservative reporting restriction should remain until validated changes are approved. Do not claim kinetic rates from unvalidated state models.

Hydration density/occupancy is not hydration free energy. Network centrality suggests testable hypotheses; it does not establish causal residues. Replace deterministic mechanistic prose with evidence-linked hypotheses.

Acceptance:

Unsupported quantitative or causal claims are withheld consistently. Report the useful descriptive result that remains, its limitations, and the additional evidence needed.

### R7 — Make release and validation status trustworthy

Required correction:

- Reconcile package version, README, release notes, installer contents, and actual published tags.
- Pin/lock compatible environments and record binary/dependency provenance.
- Separate unit tests, real-engine integration tests, scientific benchmarks, GUI checks, and diagnostic jobs.
- Distinguish report-template tests using synthetic data from scientific validation.
- Ensure nonblocking benchmark jobs and always-zero diagnostics cannot silently establish qualified capability.
- Produce a single current capability manifest, with historical logs kept separately.

Manifest fields:

Feature, implementation location, supported system types, restrictions, test type/result, source commit, evidence URL/artifact, benchmark scope, and released-installer availability.

Acceptance:

A clean installation and a documented resume/reconnect path pass on supported platforms. Release metadata describes the actual artifact. No release is published automatically under this prompt.

### R8 — Complete bounded autonomy without uncontrolled protocol changes

Current boundary:

Umbrella insertion/extension is real automation. Parameter advice and action reporting do not constitute a research-wide autonomous controller.

Build on existing modules to implement:

Assess → propose → authorize → execute → reassess → stop or escalate.

Each action requires:

- Trigger and evidence IDs.
- Prerequisites and affected scientific claims.
- Expected benefit, marked heuristic unless calibrated.
- Estimated compute/storage and measured cost where available.
- Authorization class and approved budget.
- Idempotency key, attempt limits, checkpoint/recovery plan.
- Actual outcome and post-action assessment.

Supported first actions may include reanalysis, extending an approved run, adding an independent replica, or refining approved umbrella windows. Define their preconditions and comparison consequences.

Default to recommendation-only when no compute budget or action policy exists. Within a user-approved policy, the controller may act without asking for every routine step. Changing force fields, chemical identity, protonation hypotheses, restraints, reference states, scientific models, paid backends, or external data exposure needs separate approval.

Stop on budget exhaustion, repeated no-improvement, unresolved invalid models, or insufficient evidence. Do not continue spending until a favorable result appears. Technical retries must be bounded and must not silently change the scientific protocol.

Use deterministic scientific checks as authority. Optional LLM assistance may explain evidence or propose structured actions, but cannot invent measurements, override gates, or execute arbitrary commands. Treat imported documents and molecule metadata as data, never executable instructions.

Acceptance:

Test duplicate proposals, two competing workers, GUI reconnection, invalid checkpoints, failed actions, cancellation, exhausted budgets, and unknown assessments. No duplicate simulation launches after reconnection. Record actual resource use separately from simulated ps; include retries when measuring operational cost.

## 4. Add analysis where it answers a research question

Audit existing figure families before adding any new one. Preserve existing IDs if present. For each proposed analysis, specify its question, inputs, assumptions, uncertainty, failure states, compute cost, report position, and the decision it can inform.

Prioritize:

1. **Candidate evidence and comparability matrix**

   Which candidates can validly be compared, and which lack evidence? Show missingness and reasons rather than a universal weighted score.

2. **Replica-aware synchronized ligand-state views**

   Align protein-fitted ligand RMSD, pocket/COM distance, contact retention, and relevant events. Preserve the interpretation of each metric and mark restraints.

3. **Interaction fingerprints and persistence**

   Display initial versus newly formed contacts, chemically meaningful interaction types, occupancy, duration/censoring, and replica differences.

4. **Apo–holo and cross-candidate structural response**

   Use mapped residues, compatible protocols, shared PCA coordinates/bins, representative structures, and uncertainty. Do not present separately fitted PCA axes as directly comparable.

5. **Pocket geometry and hydration**

   Add validated geometric pocket descriptors, solvent access, and water-density measures only with clear definitions and sensitivity checks. Do not call them WaterMap/GIST-equivalent thermodynamics.

6. **SMD/umbrella interpretation**

   Link force/work features to structural events, actual window coverage, statistical-overlap connectivity, convergence diagnostics, and qualified PMF. Do not rank equilibrium affinity by peak pulling force.

7. **Robustness and autonomous-action outcome**

   Show replica/protocol sensitivity and what each automatic action actually improved, failed to improve, or cost.

8. **Experimental-feedback view**

   Connect candidate-level evidence to specific next experiments while preserving assay conditions, concentration, controls, batch, and biological-replicate identities.

Advanced opt-in tracks:

- **F19 MM/GBSA or MM/PBSA:** explicitly unimplemented at the baseline; begin with a method/backend design and reference benchmark. Report force-field/solvation choices, entropy treatment, uncertainty, and applicability. Per-residue decomposition is not an exact causal partition of affinity.
- **Alchemical RBFE/ABFE:** requires parameterization, atom mapping, thermodynamic cycles, lambda sampling, overlap/convergence and appropriate corrections. Do not implement it as a plotting feature.
- **Enhanced sampling, constant-pH methods, QM/MM, and ML potentials:** future modules gated by scientific need, compatible backends, validation, and compute authorization.
- **Publication graphics:** add a reusable rendering/export layer with vector plots, high-resolution TIFF, stable colors/units/fonts, and reproducible structural scenes. Treat scientific rendering as an optional adapter with dependency/license checks.

Do not introduce all advanced tracks simultaneously. Complete a reliable narrow vertical slice before expanding supported chemistry and methodology.

## 5. Redesign reports around an explicit narrative

The reader should move from broad context to focused evidence, then return to a concise decision. Use this order:

1. Research question, target, candidates, controls, and decision scope.
2. Study design, provenance, available evidence, and major quality limitations.
3. All-candidate overview and valid comparisons.
4. Global structural behavior and replica consistency.
5. Focused ligand-state and interaction analysis.
6. Selected candidate deep dives: representative structures, pocket/hydration hypotheses, conformational response.
7. Energetics and sampling quality, with diagnostics before quantitative conclusions.
8. Integrated interpretation, competing explanations, confidence limits, and experimental priorities.
9. Methods, complete diagnostics, secondary plots, and raw-data links in appendices.

A brief qualified executive summary may appear at the front, but it must be generated after assessment and link back to supporting evidence.

Every main-text figure must have:

- One explicit question.
- Defined selections, units, time range and replica/sample counts.
- A data-linked observation.
- A bounded interpretation.
- Uncertainty/limitations and a next-step implication.

Use overview → comparable candidates → selected cases → molecular detail → synthesis. Avoid repeating the same conclusion with many plots. Move low-information plots to appendices, but never hide failures or contradictory replicas there. Preserve excluded-candidate reasons in the main report.

Synchronize figure numbering, cross-references, source links, structure/frame IDs, captions, summary statements, and language. Prefer clear 2D contours and uncertainty displays when 3D surfaces obscure evidence. Figure count is not a success metric.

Acceptance:

A reader can identify what was tested, what was observed, what remains uncertain, which candidates merit follow-up, and why, without reading the source code. Every major conclusion traces to evidence and an eligibility decision.

## 6. Benchmark the product before claiming commercial equivalence

Distinguish three validation layers:

**A. Engineering integration**

Clean installation, file integrity, restarts, cancellation, resource accounting, deterministic fixtures, and regression coverage.

**B. Scientific reliability**

Approved representative systems, independent replicas, relevant physical/chemical checks, convergence and uncertainty, parameter/protocol sensitivity, positive/negative controls, and external reference data where suitable.

**C. Product readiness**

Released-installer verification, representative user workflows, documented failure handling, version migration, support limits, and third-party license/dependency review.

Existing short real-engine tests establish integration evidence; they do not establish long-timescale convergence or predictive accuracy.

For experimental benchmarking, match assay conditions and estimands, disclose heterogeneous data, prevent calibration/test leakage, retain failed cases, and use held-out systems when assessing generalization. Predefine useful acceptance criteria and report uncertainty.

Do not claim an arbitrary percentage of commercial capability. Shared use of OpenMM does not guarantee equivalent results. Commercial platforms also have automated workflows. Compare particular capabilities, chemical scope, validation, usability, and total operational requirements.

## 7. Delivery sequence and definition of done

### Milestone 1 — Truth and critical repairs

Complete the current-state audit; implement reproducible R1–R4 defects and targeted tests; diagnose R5 failures; correct overclaims and status reporting.

### Milestone 2 — One integrated validated report

Deliver one end-to-end vertical slice from multiple independent replicas through qualification, comparison, figures, and synthesis. Demonstrate legacy-cache migration and missing/failed-data behavior. Real calculations must stay within an approved budget.

### Milestone 3 — Bounded autonomy

Integrate the policy/action ledger with existing adaptive execution; prove dry-run, authorization, idempotency, resource limits, recovery, and stopping behavior before enabling unattended runs.

### Milestone 4 — Advanced capabilities

Select one justified advanced analysis or free-energy pilot; define its benchmark and acceptance criteria before implementation. Keep other advanced tracks explicitly deferred.

For each completed change deliver:

- The reproduced defect and why it matters.
- Changed files/functions and a concise design rationale.
- Tests actually executed, commands/results, and skipped or blocked tests.
- Before/after evidence without invented scientific results.
- Migration/backward-compatibility notes.
- Updated capability status and remaining limits.

Provide a final handoff with: completed work, verified fixes, current blockers, residual scientific risks, release readiness, and the next three priorities. Maintain a resumable progress record if work spans sessions.

Do not stop after producing documentation if safe code changes can be completed. Conversely, do not call scaffold code, synthetic tests, or a proposed benchmark a completed validated capability. When blocked, finish independent safe work and specify the exact input, decision, or authorization needed.

## Evidence pointers for the historical audit

Resolve current line numbers after inspecting the local branch.

- md20/workflow.py — analysis replica selection, comparison inputs, cache reuse.
- md20/report/evidence.py — execution-driven support labels.
- md20/analysis/traj.py and extended.py — analysis/display cadence and wiring.
- md20/analysis/persistence.py, common_basis.py, toolbox.py — advanced analysis assumptions and qualifications.
- md20/sampling/assessment.py, adaptive.py, binding.py, multi.py — scientific gates, actual refinement execution, and comparison semantics.
- md20/report/auto_actions.py — report-only action/cost summary.
- md20/report/workflow_report.py and figure_text.py — report order, qualifications, and mechanistic prose.
- tools/diag_membrane_nan.py — diagnostic collection versus acceptance.
- tests/test_workflow_integration.py and tests/test_metal_integration.py — test scale and metal regression.
- docs/specs/master_iteration_2026-11-07.md — outstanding autonomy/reference-state/F19 work.

Pinned source:

https://github.com/fstcch-cmd/md20-workstation/tree/f3ecf7178052025c8b3898af0a667f170c090350

Historical CI:

https://github.com/fstcch-cmd/md20-workstation/actions/runs/42374500293

https://github.com/fstcch-cmd/md20-workstation/actions/runs/42380662439

Official comparison references; verify relevant versions before implementation:

https://www.3ds.com/support/documentation/resource-library/t62-2025-discovery-studio-2026

https://www.schrodinger.com/platform/products/fep/

https://www.schrodinger.com/platform/products/fep/fep-protocol-builder/

Begin now with the current-state reconciliation, a prioritized defect table, and the first safe repair/test cycle.