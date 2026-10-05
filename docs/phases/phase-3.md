# Phase 3 - Compliance & research (IQAC engine, OBE attainment, funded projects + PFMS)

Goal: IQAC produces a pre-validated AQAR from live data with evidence and traceability. The college computes
CO/PO/PSO attainment per its regulation's policy. The R&D cell runs funded projects from sanction to
Utilisation Certificate and PFMS export, with grant accounting per blueprint D9.

BRD: M01-01..07, M03-02, M03-03, M08-01..12 (M08-13..15 deferred to Phase 5).
Prerequisites: Phase 1 platform (P1-T04..T10), data point functions (P1-T27); Phase 2 CIA question-wise
marks with CO tags (P2-T13), valuation question-wise marks (P2-T18), results (P2-T19), COE data points (P2-T24),
faculty data points (P2-T05, P2-T09), Body & Meeting (P2-T01, P2-T02).
References: `docs/research/naac-reference-notes.md` (AQAR structure, SXCCE OBE rule), blueprint 9.3 and 9.4, D9.
Official regulator templates are **not** available yet. Seed structure only, label placeholders, and keep export layouts as configurable mappings.

Exit demo: AQAR 2025-26 cycle for Demo College → compute all quantitative metrics → 3 metrics flagged by
pre-validation (missing evidence, word limit, 2.1.2 > 4.1) → fixed → IQAC approval → Excel + PDF export with
source drill-down for 2.6.3 → CO/PO attainment for B.E. CSE batch 2022 with 80/20 and 60/40 weights →
DST sanction with 4 heads → purchases → re-appropriation → UC for FY 2025-26 from GL → PFMS EAT export file.

---

## A. IQAC & accreditation engine (M01)

### P3-T01 Framework and node tree
BRD: M01-01, M01-02 | Depends on: P1-T01 | Size: M
Deliverables: Accreditation Framework (code, version, valid from/to, segments, status Draft/Published/Retired), Framework Node (tree: node type, code, title, answer type Number/Percent/Choice/Narrative/File/Table, choices, word limit, unit, period, formula, department-wise flag, owner role, evidence slots child).
"Clone to new version" action. Published frameworks are immutable.
Seed: `NAAC-AQAR-RAF2017` skeleton with the criterion → key indicator → metric → sub-metric codes and short titles seen in the SXCCE AQAR 2023-24, plus Extended Profile nodes (1.1, 2.1-2.3, 3.1-3.3, 4.1-4.4). Text marked "placeholder - replace with official template".
Acceptance criteria
1. The seeded tree has all 7 criteria and the metric IDs from the research note. Codes are unique per framework.
2. Editing a published framework is blocked. Cloning produces an editable Draft with identical nodes.
Tests: I - seed integrity, publish lock, clone fidelity.

### P3-T02 Data point registry and formula evaluation
BRD: M01-02, NFR auditability | Depends on: T01, P1-T27, P2-T24 | Size: M
Deliverables: decorator `@campus_metric("students_admitted")` registering functions from every module. Data Point DocType synced from the registry (key, module, description, parameters).
Evaluator: formula over data point keys and other node codes (e.g. `round(total_students / full_time_teachers, 2)`) via `frappe.safe_eval` with a whitelisted namespace. Cycle detection between node formulas.
Snapshot format: `{inputs: {key: {value, records:[doctype/name…]}}, formula, result, computed_at, engine_version}`.
Acceptance criteria
1. Every metric function from Phases 1-2 appears as a Data Point after migrate.
2. A formula referencing an unknown key or a cyclic node reference fails validation on save.
3. A formula can't access anything outside the whitelisted namespace (no `frappe.db`, no imports).
Tests: U - evaluator, cycle detection, sandbox escape attempts. I - registry sync.

### P3-T03 Accreditation cycle and metric values
BRD: M01-02, M01-03 | Depends on: T02, P1-T09, P1-T07 | Size: L
Deliverables: Accreditation Cycle (framework, company, period, status Collecting → Validating → IQAC Review → Approved → Submitted, owners per criterion), Metric Value (cycle, node, department, computed value, manual value, override reason, narrative, choice, status Draft/Computed/Verified/Locked, snapshot).
"Compute all" bulk run. Override requires a reason + approval. Narrative editor with a live word count. Criterion owners get tasks.
Acceptance criteria
1. Computing the demo cycle fills every Number/Percent node that has a formula. Drill-down from 2.6.3 lists the exact student result records used.
2. Re-computing after a data change updates Computed values but never overwrites Verified or Locked ones (shows "source changed" instead).
3. An override without approval keeps the computed value as the effective one.
4. After Approved, all values are Locked.
Tests: I - compute, recompute rules, override flow, lock.

### P3-T04 Evidence registry and public disclosure
BRD: M01-01, principle 6 | Depends on: T01 | Size: M
Deliverables: Evidence (file or URL, nodes multi-link, academic year, department, owner, source dynamic link, public flag, stable public URL `/disclosure/<slug>`). "Attach as evidence" action on Meeting, Circular, Feedback Campaign, Faculty Achievement, Sanction, Placement records (and any doctype via a hook list in Campus Settings).
Public disclosure page grouped by year and type (like the SXCCE IQAC page): IQAC minutes, academic calendar, AQARs, feedback reports, best practices.
Acceptance criteria
1. Evidence from a source record stays linked if the source file is replaced (new version, same public URL).
2. Non-public evidence is never served at the public URL.
3. A metric's evidence slots show filled/missing per cycle.
Tests: I - URL stability, public/private access, slot completeness.

### P3-T05 Pre-validation and readiness dashboard
BRD: M01-03 | Depends on: T03, T04 | Size: M
Deliverables: Validation Rule (framework-level, data: rule type required-evidence / word-limit / comparison between nodes / range / non-empty, message). Validation run per cycle with a results list. Readiness dashboard (completion % per criterion, missing evidence, rule failures, owner).
Acceptance criteria
1. The demo cycle flags exactly the 3 seeded problems (missing evidence, word limit, 2.1.2 > 4.1).
2. A cycle can't move to IQAC Review with blocking failures. Warnings are allowed with a comment.
Tests: U - each rule type. I - status gate.

### P3-T06 Exports
BRD: M01-03 | Depends on: T03, T05 | Size: M
Deliverables: Export Template (framework, format Excel/PDF, mapping of nodes to sheet/cell or section, per-metric Data Template sheets with record listings). Exporter producing the AQAR Excel and PDF (PDF layout follows AQAR Part A / Extended Profile / Part B ordering). NBA SAR and NIRF templates as placeholder mappings.
Acceptance criteria
1. Exported Excel values equal the Locked metric values. Each Data Template sheet lists the snapshot records.
2. Changing the mapping (moving a cell) changes the export without code changes.
Tests: I - export vs values, mapping change.

### P3-T07 Feedback engine
BRD: M01-05, M03-03 (indirect), M07-04 | Depends on: P1-T10 | Size: L
Deliverables: Feedback Form (questions: Likert 1-5, choice, text; optional CO link per question), Feedback Campaign (form, audience: course offering students / alumni / employers / teachers / parents; window; anonymous flag; reminder schedule), Feedback Response (anonymous responses store no user link, only a one-time token to stop duplicates), analysis report (per question, per course, per faculty), Action Taken note.
Seeds: Course exit survey, Programme exit survey, Student Satisfaction Survey, Curriculum feedback (students/teachers/employers/alumni).
Acceptance criteria
1. Anonymous responses can't be traced to a user even by System Manager (no user, IP or timestamp finer than a day stored).
2. One response per eligible respondent per campaign.
3. Course exit survey CO scores are exposed via `iqac.api.indirect_co_scores(offering)`.
Tests: I - anonymity (inspect stored rows), duplicate prevention, CO score aggregation.

### P3-T08 IQAC operations: meetings, committees, regulator tracker, MoUs
BRD: M01-04, M01-06, M01-07 | Depends on: P2-T01, P2-T02 | Size: M
Deliverables: IQAC calendar (meetings of Body Type IQAC + planned activities), ATR from Action Items, Committee compliance report (meetings held vs required, composition), Regulator Submission Type + Regulator Submission (due rule, reminders at 30/7/1 days, status, documents), Institutional MoU (partner, purpose, period, activities; used by 3.7.2, placement, research).
Acceptance criteria
1. A committee below its minimum meetings for the year is flagged on the compliance report.
2. Regulator reminders go to the owner and escalate to the Principal after the due date.
Tests: I - compliance calc, reminder schedule.

## B. Outcome-based education (M03)

### P3-T09 Outcomes and mapping matrices
BRD: M03-02 | Depends on: P1-T12 | Size: M
Deliverables: Program Educational Objective, Program Outcome (seed NBA PO1-PO12 per program), Program Specific Outcome, Course Outcome (course + curriculum, CO code, statement, Bloom level), CO-PO Matrix (course + curriculum, CO × PO/PSO correlation 0-3; approval by HOD/BoS), PEO-Mission mapping. Prints: CO-PO matrix, course outcome sheet.
Acceptance criteria
1. A CO-PO matrix can't be approved with a CO that maps to nothing, or a PO with zero total correlation across the curriculum (warning listed in the coverage report).
2. Matrices are versioned with the curriculum. A 2022-batch offering uses the R2022 matrix.
Tests: I - validation, version resolution.

### P3-T10 Attainment policy and runs
BRD: M03-03 | Depends on: T09, T07, P2-T13, P2-T18, P2-T19 | Size: L
Deliverables: Attainment Policy (per regulation: direct/indirect weights, direct split CIA/ESE, student threshold %, level bands, target level, PO indirect weight from programme exit survey). CO Attainment Run (offering: per CO, % of students ≥ threshold on CO-tagged CIA questions and ESE questions → levels → direct → final with indirect). PO Attainment Run (program, batch, year: Σ(CO final × correlation)/Σ correlation, plus indirect).
Reports: CO attainment by course/faculty, PO/PSO attainment by program/batch, target gap, NBA course-file print.
Acceptance criteria
1. With the SXCCE policy (80/20; direct = 60 ESE + 40 CIA; threshold 60%; bands 40/50/60), the fixture course gives the hand-computed CO and PO levels.
2. Changing the policy for R2026 doesn't change R2022-batch results.
3. The run snapshot lists the questions and students used per CO.
Tests: U - attainment maths with fixture tables. I - end-to-end run, policy isolation.

### P3-T11 Course plan and adherence
BRD: M03 (AQAR 2.3.4) | Depends on: P2-T07 | Size: S
Deliverables: Course Plan (offering; planned topics by week with CO), delivery log from Course Schedule (topic covered field on schedule/attendance), adherence % report, HOD review sign-off (R2022 cl. 12.9: at least 3 times a semester).
Acceptance criteria
1. Adherence % = delivered planned topics / planned topics to date. HOD reviews are counted per semester.
Tests: I - adherence calc, review count.

## C. Research & funded projects (M08)

### P3-T12 Research masters and settings
BRD: M08-01 | Depends on: P1-T03 | Size: S
Deliverables: Funding Agency, Funding Scheme (budget head template, overhead %, instalment pattern, UC format), Grant Budget Head (head → expense account(s) / item groups), Research Centre, Journal (ISSN, indexing flags, UGC-CARE), IPR Type, Research Settings (per company: grant liability account parent, grant income account, deferred capital grant account, interest treatment, PFMS unique agency code).
Acceptance criteria
1. A scheme can't be used if any of its heads lacks an account mapping for the company.
Tests: I - mapping validation.

### P3-T13 Calls and proposals
BRD: M08-02 | Depends on: T12, P1-T07 | Size: S
Deliverables: Research Call (agency, scheme, deadline), Research Proposal (PI, co-PIs, budget by head, internal review via approval engine, submission date, outcome). Report: proposal pipeline.
Acceptance criteria
1. A proposal can be submitted to the agency only after internal approval. Deadline reminders go to the PI.
Tests: I - approval gate, reminders.

### P3-T14 Sanction, project set-up, receipts
BRD: M08-03, M08-05 | Depends on: T12 | Size: L
Deliverables: Sanction (order no/date, agency, scheme, PI/co-PIs, duration, heads child (sanctioned per year), instalments child, conditions). On submit: ERPNext Project, Cost Center (under the research cost centre), Budget per head-account (Stop or Warn per scheme), liability account "Grant Received in Advance - <sanction>".
Grant Receipt: instalment received → Payment Entry/Journal Entry crediting the liability. Extension: revised end date with order.
Acceptance criteria
1. Submitting a sanction creates exactly one Project, Cost Center and Budget set. Cancelling it (before any transaction) removes them.
2. A receipt credits the sanction's liability, never income.
3. Seed money (agency "Institution") works the same way.
Tests: I - set-up artefacts, receipt accounting, cancel rollback.

### P3-T15 Expenditure tagging, budget control, re-appropriation
BRD: M08-04, M08-05 | Depends on: T14 | Size: M
Deliverables: `oc_budget_head` on Purchase Order Item, Purchase Invoice Item, Journal Entry Account, Expense Claim Detail (required when the project belongs to a sanction). Head → account validation. Budget control through ERPNext Budget.
Re-appropriation Request (from head, to head, amount, agency approval letter) → Budget amendment.
Acceptance criteria
1. A PI line for the "Equipment" head posting to a consumables account is rejected.
2. Spending above the head budget is stopped (or warned) per the scheme setting.
3. After an approved re-appropriation, the new limits apply and the change is logged on the sanction.
Tests: I - validation, budget stop/warn, re-appropriation effect.

### P3-T16 Grant income recognition and capital grants
BRD: M08-05, D9 | Depends on: T15 | Size: M
Deliverables: Grant Income Recognition (period, sanction(s); JE debiting liability and crediting grant income for revenue expenditure in the period, idempotent per period). Asset purchase from a sanction → JE moving the amount from liability to Deferred Capital Grant. Monthly release in line with depreciation. Interest on grant funds per Research Settings (liability default).
Acceptance criteria
1. After recognition, (liability balance) = receipts + interest (if liability) − expenditure recognised − capitalised grants, per sanction, matching the fixture.
2. Running recognition twice for the same period posts nothing new.
3. Grant P&L for a fully spent revenue grant nets to zero (expense = grant income).
Tests: U - recognition amount calc. I - JEs, idempotency, balance reconciliation.

### P3-T17 Utilisation Certificate and Statement of Expenditure
BRD: M08-06 | Depends on: T16 | Size: M
Deliverables: Utilisation Certificate (sanction, period: opening unspent, grants received, interest, total available, expenditure by head (from GL via project + head mapping), closing unspent; certification block; versioned; approval PI → Accounts → Principal), Statement of Expenditure (head-wise, sanctioned vs spent). Prints: GFR 12-A style UC (placeholder until the agency format is supplied), SOE. Reports: UC due/overdue, grant ledger by head.
Acceptance criteria
1. UC figures equal GL figures for the period. A posted backdated entry after UC approval flags the UC as "source changed".
2. UC can't be approved while unreconciled entries without a budget head exist for the project.
Tests: I - UC vs GL fixture, change detection, approval gate.

### P3-T18 PFMS EAT export
BRD: M08-07 | Depends on: T17 | Size: M
Deliverables: PFMS adapter interface (`export_expenditure`, `export_advance`, `export_transfer`, `import_status`). File adapter producing the EAT bulk-upload file (column layout configurable as a mapping because the official spec isn't supplied yet). PFMS Export Batch (period, sanction, rows from Payment Entries/PIs, validation), vendor check (Supplier `oc_pfms_vendor_code`, bank details present), status import updating rows.
Acceptance criteria
1. A batch excludes and reports payments to vendors without a PFMS code or bank details.
2. Re-exporting a period only includes rows not already exported successfully.
3. The column mapping can be changed without code.
Tests: I - row selection, vendor check, idempotency, status import.

### P3-T19 Project execution, staff and closure
BRD: M08-08, M08-09 | Depends on: T14 | Size: M
Deliverables: Progress Report (period, milestones from Project tasks, deliverables), Mid-term Review. Project Staff appointment (JRF/SRF/PA as Employee with employment type Project Staff, fellowship salary structure charged to the project cost centre, end date = sanction end). Project Closure (final UC, unspent refund JE/Payment, Asset Movement handover to department, close Project).
Acceptance criteria
1. Project staff salary posts to the project with head "Manpower" and counts in the UC.
2. Closure is blocked until the final UC is approved and unspent is refunded or retained per agency letter.
Tests: I - salary posting, closure gate.

### P3-T20 Consultancy
BRD: M08-10 | Depends on: T12 | Size: M
Deliverables: Consultancy Project (client Customer, estimate, agreement, deliverables, revenue-share rule institution/faculty/staff %), Sales Invoice with GST via india_compliance, revenue-share distribution on receipt → Additional Salary for faculty.
Report: Consultancy revenue (AQAR 3.5.1, NIRF).
Acceptance criteria
1. GST is applied per the place of supply. Revenue share is created only after payment is received, matching the rule %.
Tests: I - invoice GST, share calc and posting.

### P3-T21 IPR and publications
BRD: M08-11, M08-12 | Depends on: T12, P2-T05 | Size: M
Deliverables: Invention Disclosure → Patent (lifecycle Filed / Published / Examined / Granted / Licensed, costs, revenue share), Publication (type journal/conference/book/chapter; authors as Employees/Students/external; journal; indexing; DOI with Crossref metadata fetch; citations), faculty profile aggregation.
Reports + data points: AQAR 3.3.x, 3.4.3, 3.4.4, 3.4.5, 3.4.6; NIRF IPR and publications.
Acceptance criteria
1. Entering a DOI fills title, journal, year and authors from Crossref (mocked in tests). Duplicate DOIs are rejected.
2. A publication by 3 faculty counts once per institution and once per faculty in the respective reports.
Tests: I - DOI fetch (mock), duplicate, counting rules.

### P3-T22 Research reports and data points
BRD: M17-06, NIRF RPC | Depends on: T14-T21 | Size: S
Deliverables: Reports: Sanction register, Grant ledger, Budget vs actual by head, UC due, PFMS status, Grants received (3.2.1), Teachers with projects (3.2.2), Research guides (3.2.3), Departments funded (3.2.4), NIRF sponsored research and consultancy (3-year amounts and counts). Data points for each.
Acceptance criteria
1. Data points match the reports and fixture. They compute in the AQAR demo cycle (T03).
Tests: I - each data point.

---

## Phase 3 exit checklist
- [ ] Exit demo run. AQAR Excel/PDF exported with drill-down evidence.
- [ ] D9 accounting walkthrough reviewed with an accountant (sign-off noted in blueprint D9).
- [ ] Anonymity audit of feedback storage.
- [ ] Usage notes for IQAC, OBE, research. Blueprint status updated.
