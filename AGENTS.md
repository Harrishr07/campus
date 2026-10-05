# AGENTS.md - Project Context for AI Coding Agents

> Read this file first. It explains WHAT we are building, WHY, and HOW you should work. Companion document: `docs/Frappe_Higher_Education_Layer_BRD.md` (requirement IDs like M06-03 refer to it).

## 1. One-paragraph intent

We are building a **higher-education extension layer on top of Frappe Education / ERPNext** for Indian colleges. Frappe Education is a good school-level core (students, guardians, programs, courses, fees, attendance, basic assessment, portal) but it does not run a real autonomous college. Our layer adds the missing operations and compliance workflows so that **one system can run an autonomous engineering college end to end**, and accreditation data (NAAC, NBA, NIRF) is produced as a by-product of daily operations rather than a last-minute spreadsheet exercise.

## 2. Who we build for

Three segments only (for now):

| Segment | Main compliance driver | Lifecycle path |
|---|---|---|
| Arts & Science | NAAC, NIRF (university/UGC) | Affiliated -> Autonomous -> Deemed university |
| Nursing | INC + NAAC, NIRF | Affiliated -> (Autonomous/Deemed where eligible) |
| Engineering | NBA (main), plus NAAC, NIRF, AICTE | Affiliated -> Autonomous -> Deemed |

**Design persona:** the principal / IQAC coordinator / Controller of Examinations of an *autonomous engineering college* (about 6-8 departments, 1,200-1,800 students, 120-180 faculty, hostel, transport, R&D cell, funded projects). When a design choice is unclear, choose what this person needs. Do not design for K-12 schools.

## 3. Core product principles (follow these when making decisions)

1. **Layer, don't fork.** Build as separate Frappe app(s) that depend on `education` and `erpnext`. Never edit core app code. Use custom DocTypes, Custom Fields (via fixtures), hooks, doc events, and workflows. Upgrades of Frappe/ERPNext/Education must not break us.
2. **Reuse before build.** Prefer existing ERPNext/Education DocTypes (Student, Program, Course, Fees, Employee, Project, Cost Center, Asset, Stock, Payroll) and link to them. Add new DocTypes only where nothing fits.
3. **Regulations are data, not code.** NAAC/NBA/NIRF metrics, grading schemes, eligibility rules, fee heads, approval chains and regulation years must be configurable records. Regulator formats change often; metric formulas must be versioned.
4. **Regulation-year aware.** Curriculum, grading and exam rules attach to a regulation year/batch. Older batches keep older rules.
5. **Institution Status switch.** A setting (Affiliated / Autonomous / Deemed) turns module packs and workflows on or off so one customer can graduate without migration.
6. **Accreditation as by-product.** Every module that produces accreditation-relevant data should tag it to a criterion/metric and keep evidence links, so IQAC reports are generated from live data.
7. **Everything approvable is auditable.** Use a generic multi-level approval workflow pattern (delegation, SLA escalation, comment trail, versioned documents) rather than one-off logic per module.
8. **Confidentiality of exam data.** Question papers, dummy numbers and valuation data need strict role/field-level permissions and time-bound release.
9. **Multi-institution ready.** One trust may run arts, nursing and engineering colleges with shared services (hostel, transport, library) but separate academic records. Model with Company/Institution scoping from day one.
10. **Integrate rather than rebuild** for commodity areas (library via Koha/SOUL, LMS, WhatsApp/SMS, payment gateways, GPS, biometrics).

## 4. Module map (see BRD for full requirement IDs)

| Code | Module | Priority theme |
|---|---|---|
| M01 | Governance, IQAC & accreditation engine (NAAC/NBA/NIRF, committees) | P0 |
| M02 | Academic governance (BoS -> Academic Council -> Governing Council) | P0 |
| M03 | Curriculum, CBCS, outcome-based education (CO-PO attainment) | P0 |
| M04 | Admissions (counselling, management quota, lateral entry) | P0/P1 |
| M05 | Student lifecycle & services (GPA, TC, scholarships, grievance) | P0/P1 |
| M06 | Controller of Examinations (hall ticket to revaluation, transcripts) | P0 |
| M07 | Faculty lifecycle (workload, timetable, appraisal/API, CAS) | P0/P1 |
| M08 | Research & funded projects incl. PFMS (sanction, budget heads, UC/SOE, EAT export) | P0 |
| M09 | Finance extensions on ERPNext (fee heads, cost-centre mapping, grant ledgers) | P0 |
| M10 | Hostel & mess | P0/P1 |
| M11 | Transport | P1/P2 |
| M12 | Labs & facilities (incl. nursing clinical rotations) | P1 |
| M13 | Library (integrate Koha/SOUL) | P3 |
| M14 | Training, placement, internships | P1 |
| M15 | Alumni | P2 |
| M16 | Communication (WhatsApp/SMS/email/push) | P0 |
| M17 | Platform: multi-campus, roles, workflow engine, integrations | P0 |

**Suggested build order:** Phase 0 validate -> Phase 1 foundation (M17, M16, M03 core, M04, M05, M09) -> Phase 2 autonomy core (M06, M02, M07) -> Phase 3 compliance & research (M01, M03 OBE, M08) -> Phase 4 campus operations (M10, M11, M12, M14) -> Phase 5 extend (M15, M13, nursing, deemed pack).

## 5. Domain glossary (so you do not guess)

- **Autonomous college:** still affiliated to a university but sets its own syllabus, exams and results.
- **Deemed university:** institution granted university status; has its own degrees and wider governance.
- **NAAC:** accreditation body; produces SSR (Self-Study Report) and yearly AQAR. **NBA:** programme accreditation for engineering (CO-PO attainment). **NIRF:** national ranking data submission. **AICTE / UGC / INC:** regulators for technical education / universities / nursing.
- **IQAC:** Internal Quality Assurance Cell that collects accreditation data year-round.
- **COE:** Controller of Examinations; runs hall tickets, question papers, valuation, results, revaluation.
- **CIA / ESE:** Continuous Internal Assessment / End Semester Examination.
- **BoS / AC / GC:** Board of Studies / Academic Council / Governing Council (syllabus approval chain).
- **CBCS:** Choice-Based Credit System. **PEO/PO/PSO/CO:** programme and course outcome hierarchy.
- **API / CAS:** faculty Academic Performance Indicator / Career Advancement Scheme.
- **PFMS:** Public Financial Management System. **EAT:** Expenditure, Advance, Transfer module. **UC:** Utilisation Certificate. **SOE:** Statement of Expenditure. **PI:** Principal Investigator.
- **TNEA:** Tamil Nadu engineering counselling (first-class pilot context).
- **TC:** transfer certificate. **TPO:** training and placement officer. **ILMS:** integrated library management system. **IRINS:** INFLIBNET research information network.

## 6. Known unknowns - do NOT assume, ask or flag

- Coverage of Frappe Education/ERPNext was judged from public docs, GitHub, forums and competitor pages, **not a code audit**. Before building any module, inspect the installed `education` and `erpnext` apps and report what already exists (DocTypes, fields, reports, workflows). Say so explicitly if something marked "None" in the BRD actually exists.
- PFMS: unclear whether college-level agencies get API access. Default to **structured file export/import** (EAT/UC/SOE-compatible) and keep an adapter interface for a future API.
- Regulator templates (NAAC, NBA, NIRF, agency UC/SOE formats): do not invent official field lists. Use placeholders, clearly named config records, and flag that the real templates must be supplied.
- University-specific exam rules vary. Never hardcode grading, grace marks, pass criteria or eligibility thresholds (75% attendance is a configurable default only).
- Effort/cost estimates in earlier discussion were rough. Do not rely on them.

## 7. How to work (rules for the agent)

1. **Start with a short plan** per task: affected DocTypes, reused vs new, permissions, workflows, reports, tests. Wait for approval on schema changes that touch core links (Student, Program, Fees, Employee, Company).
2. **Frappe conventions:** one app per bounded area or a single `campus` app with modules per code (M01...); DocType JSON + Python controller + client script; roles and permission levels defined explicitly; fixtures for Custom Fields/Workflows/Roles; patches for data migrations; `bench` commands for migrate/tests.
3. **Naming:** prefix custom DocTypes and fields consistently (e.g., module-based) to avoid clashes with upstream. Keep BRD IDs in docstrings or comments (`# M06-05`).
4. **Tests:** write unit tests for rules (GPA/CGPA, attendance eligibility, CO-PO attainment, fee heads, UC/SOE totals). Use fixtures for regulation-year scenarios.
5. **Security and privacy:** student data is personal data (India DPDP Act). Apply least-privilege roles, field-level permissions for marks/exam data, audit logs, consent and opt-out for messaging.
6. **Performance:** run bulk jobs (hall tickets, results, fee generation, notifications) as background jobs, idempotent and resumable.
7. **Localisation:** English plus Tamil-ready strings (use translation functions), Indian number/date formats, INR, GST/TDS awareness.
8. **Reports:** every module ships the reports its accreditation metrics need, with export to Excel/PDF.
9. **No scope creep:** only Arts & Science, Nursing, Engineering. No K-12 features. No new LMS.
10. **Document as you go:** update the BRD status column or a CHANGELOG for each completed requirement ID; record assumptions you made.

## 8. Definition of done (per requirement)

- Meets the BRD requirement text and priority intent.
- Reuses existing ERPNext/Education DocTypes where possible; no core edits.
- Configurable (no hardcoded regulation values); regulation-year aware where relevant.
- Roles/permissions and audit trail defined; sensitive fields protected.
- Tests pass; migration/patch tested on an existing site.
- Report/export exists if the requirement feeds NAAC/NBA/NIRF/PFMS.
- Short usage note added for implementation consultants.

## 9. First tasks suggested for the agent

1. **Audit** installed `frappe/education` and `erpnext`: list DocTypes, workflows, reports, portal pages; produce a coverage matrix against BRD modules (M01-M17) and flag corrections.
2. **Scaffold** the extension app(s), settings DocType (Institution Status, Regulation Year defaults), roles, and a generic multi-level approval workflow pattern.
3. **Spike one vertical slice**: M08 funded project (sanction -> budget heads -> ERPNext Project/Cost Center ledger -> UC/SOE draft export), because it is a distinct gap with low overlap with upstream.
4. **Spike a second slice**: M06 exam cycle skeleton (exam notification -> registration -> hall ticket -> mark entry -> result), to validate regulation-year and permission design.

## 10. Business context (for tone and prioritisation)

Owner is a B2B technology marketer / marketing-systems builder at OneBook with ERPNext/Frappe, Next.js, React Native and automation experience. The goal is a commercial product with a strong go-to-market story: "accreditation-ready by design on open-source ERPNext". Prefer practical, checklist-style outputs, concise explanations, and working prototypes over long theory. When trade-offs exist, state them briefly and recommend one option.
