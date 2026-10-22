# Phase task docs - conventions

Each phase doc (`phase-1.md` … `phase-5.md`) can be picked up on its own. It lists its prerequisites
(what earlier phases must have delivered), its tasks, acceptance criteria and test logic.
Background: `AGENTS.md`, `docs/Frappe_Higher_Education_Layer_BRD.md`, `docs/blueprint.md`, `docs/research/*`.

| Phase | Theme | BRD modules |
|---|---|---|
| 1 | Foundation | M17, M16, M03 core, M04, M05, M09, portal shell |
| 2 | Autonomy core | M06, M02, M07 |
| 3 | Compliance & research | M01, M03 OBE, M08 |
| 4 | Campus operations | M10, M11, M12, M14 |
| 5 | Extend | M15, M13, nursing pack, deemed pack, P2/P3 integrations, migration toolkit |

## Task format

```
### P<phase>-T<nn> Title
BRD: ids | Depends on: task ids | Size: S (≤2d) / M (3-5d) / L (1-2w)
Deliverables: DocTypes, fields, hooks, reports, prints, APIs
Acceptance criteria: numbered, testable statements
Tests: U = unit (no DB / pure rules), I = integration (FrappeTestCase on test site), M = manual UAT script
```

## Environment

- Bench: `/workspace/development/education-bench`, dev site `education.localhost` (port 8003).
- **Tests run on `campus-test.localhost` only** (created in P1-T01), never on the dev site.
  `bench --site campus-test.localhost run-tests --app campus [--module campus.<module>.…]`
- Apps: frappe, erpnext, hrms, education, india_compliance, frappe_whatsapp, campus.
- Always pass `--site`. Migrate with `bench --site <site> migrate`.

## Naming rules

- App `campus`, modules per blueprint section 2.1.
- Custom fields on upstream DocTypes: `oc_` prefix, shipped as fixtures (`fixtures/custom_field.json`, filtered by `fieldname like 'oc_%'`).
- New DocTypes: plain English names, checked against frappe/erpnext/hrms/education before creation.
- BRD ID in the controller docstring, e.g. `"""M06-05 Result processing."""`.
- Cross-module calls only through `campus.<module>.api` (blueprint D7).

## Standard demo data (fixture `campus/tests/demo.py`, used by every phase)

- Trust company: **Demo Educational Trust** (group company, owns hostel/transport).
- College: **Demo College of Engineering** (child company, Engineering, Autonomous since 2022-05-26, affiliated to Anna University).
- Second college: **Demo Arts & Science College** (child company, Affiliated) for scoping tests.
- Programs: B.E. CSE, B.E. ECE (8 semesters), M.E. CSE.
- Regulations: `AU-R2021` (pre-autonomy batches), `R2022`, `R2026`, with rule values from
  `docs/research/anna-university-autonomous-rules.md`.
- Academic years 2022-23 … 2026-27, odd/even terms.
- 60 students per program batch (enough to test the relative-grading cohort threshold of 30).
- Users per role: principal, hod_cse, faculty_1..3, coe, exam_confidential, iqac, accounts, warden, student_1, guardian_1.

## Definition of done (every task)

1. Acceptance criteria met and demonstrated on `education.localhost` with demo data.
2. U/I tests written and green on `campus-test.localhost`. Rule logic has U tests for every rule branch.
3. No edits to frappe/erpnext/hrms/education code. Custom fields, roles and workflows exported as fixtures.
4. Rule values are records (no hardcoded thresholds), and regulation-aware where the BRD says so.
5. Role permissions defined. Sensitive fields use permlevel or restricted doctypes.
6. Bulk operations run as background jobs, idempotent, with progress and per-row errors.
7. Strings wrapped in `_()`. INR and Indian date formats.
8. Report/export exists where the requirement feeds NAAC/NBA/NIRF/PFMS.
9. Usage note added to `docs/usage/<module>.md`. Status updated in `docs/blueprint.md` section 12.
