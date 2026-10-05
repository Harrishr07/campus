# OneBook Campus

A higher-education layer on [Frappe Education](https://github.com/frappe/education) and [ERPNext](https://github.com/frappe/erpnext) for Indian colleges.

Frappe Education covers the school-level core: students, programs, courses, fees, attendance and basic assessment.
`campus` adds what an **autonomous college** needs to run end to end:

- regulation-year curriculum and credits (CBCS)
- Controller of Examinations operations
- academic governance (BoS → Academic Council → Governing Body)
- funded research and PFMS reporting
- hostel, transport, labs, placement and alumni

Accreditation data for **NAAC, NBA and NIRF** is captured as a by-product of these daily operations, so it doesn't have to be rebuilt in spreadsheets at submission time.

It targets three segments: **Arts & Science, Nursing and Engineering**. The design persona is the principal, IQAC coordinator or Controller of Examinations of an autonomous engineering college. K-12 is out of scope.

## Principles

1. **Layer, don't fork.** Never edit frappe, erpnext, hrms or education. Use custom DocTypes, custom fields (`oc_` prefix), hooks and doc events.
2. **Reuse before build.** Link to existing ERPNext and Education DocTypes, such as Student, Program, Course, Sales Invoice, Project, Employee and Asset.
3. **Regulations are data.** Grading, pass rules, attendance thresholds, credit limits, fee heads, approval chains and NAAC metric formulas are versioned records, not code.
4. **Regulation-year aware.** Every student resolves to a regulation (e.g. `R2022`, `R2026`). Older batches keep their own rules.
5. **One Company per college.** A trust is the parent group company and can own shared services such as the hostel. Academic records are scoped with `oc_company` and User Permissions.
6. **Everything approvable is auditable.** A generic approval engine handles multi-level approval, delegation and SLA escalation, and keeps an immutable trail.
7. **Confidential data stays confidential.** Exam papers, dummy numbers and pre-release marks are restricted by role. Aadhaar is stored encrypted, shown masked, and every reveal is logged.

## Requirements

- Frappe / ERPNext / HRMS / Education: `version-16`
- [India Compliance](https://github.com/resilient-tech/india-compliance) (`version-16`), for GST and TDS
- [frappe_whatsapp](https://github.com/shridarpatil/frappe_whatsapp), for the WhatsApp channel
- Python 3.14, Node 24, MariaDB, Redis

## Installation

```bash
cd ~/frappe-bench
bench get-app --branch version-16 erpnext
bench get-app --branch version-16 hrms
bench get-app --branch version-16 education
bench get-app --branch version-16 https://github.com/resilient-tech/india-compliance
bench get-app https://github.com/shridarpatil/frappe_whatsapp
bench get-app https://github.com/OneBook-ERP/campus

bench --site <site> install-app erpnext hrms education india_compliance frappe_whatsapp campus
```

Load the demo data set: a trust with two colleges, B.E./M.E. programs, regulations AU-R2021, R2022 and R2026, users for each role, and students.

```bash
bench --site <site> execute campus.tests.demo.make_demo --kwargs "{'scale': 'small'}"   # or 'full' (900 students)
```

## Development

```bash
# dev site
bench --site education.localhost migrate

# tests run on a dedicated site only (scripts/test.sh refuses any other site)
bench --site campus-test.localhost set-config allow_tests true
apps/campus/scripts/test.sh                       # full suite
bench --site campus-test.localhost run-tests --app campus --module campus.tests.test_bulk
```

Conventions:

- **Custom fields:** defined in code with `create_custom_fields` (idempotent), called from `after_install` and `after_migrate`. No fixture JSON.
- **Cross-module calls:** go only through `campus.<module>.api`.
- **BRD reference:** each controller or module docstring carries its BRD requirement ID, e.g. `"""M06-05 ..."""`.
- **Bulk work:** goes through `campus.campus_platform.bulk.run_bulk`. Jobs are resumable and idempotent per item key, and handlers are DB-only and never commit.
- **Concurrency (MariaDB REPEATABLE READ):** after a `FOR UPDATE` lock, every re-check must be a locking read.
- **Pre-commit:** ruff, eslint and prettier (`pre-commit install`).

## Architecture

One app, one Frappe module per BRD area:

| Module | BRD | What it holds |
|---|---|---|
| Campus Platform | M17 | Institution Profile, Module Packs, Shared Service Agreement, Regulation, Positions, Approval engine, Verifiable Documents (QR + `/verify/<code>`), Bulk Run |
| Campus Messaging | M16 | Message Templates (en/ta), consent, send API with channel fallback (WhatsApp → SMS → email), broadcasts, circulars |
| Curriculum | M03 | Course Category, Curriculum (versions, L-T-P-C), Elective Group, Curriculum/Registration Rules, course offerings, Course Registration |
| Admissions | M04 | Quotas, counselling authorities, document and eligibility rules, refund rules, encrypted Aadhaar |
| Student Services | M05 | Onboarding, attendance eligibility and condonation, certificates and TC, grievances, scholarships |
| Campus Finance | M09 | Fee heads, fine rules, challans, bank collection import, receipts, cross-company student ledger |
| Examinations | M06 | Exam sessions, CIA, hall tickets, seating, question papers, valuation, results, revaluation |
| Academic Governance | M02 | Bodies, meetings, resolutions, academic proposals |
| Faculty | M07 | Workload, timetable solver, achievements, appraisal |
| IQAC | M01 | Accreditation frameworks, metric engine, evidence, AQAR/SSR exports, feedback |
| Research | M08 | Sanctions, budget heads, UC/SOE, PFMS export, consultancy, IPR, publications |
| Hostel, Transport, Labs, Placement, Alumni, Library Integration | M10–M15 | Campus operations (Phase 4–5) |

## Documentation

| Document | Contents |
|---|---|
| [AGENTS.md](AGENTS.md) | Product intent, principles, glossary, rules for contributors and AI agents |
| [docs/Frappe_Higher_Education_Layer_BRD.md](docs/Frappe_Higher_Education_Layer_BRD.md) | Business requirements (M01–M17, requirement IDs) |
| [docs/blueprint.md](docs/blueprint.md) | Solution blueprint: decisions D1–D14, masters, transactions, settings, prints, reports, integrations per module |
| [docs/phases/](docs/phases/) | Phase task docs with acceptance criteria and test logic (`README.md` = conventions) |
| [docs/research/](docs/research/) | NAAC AQAR/SSR structure notes; Anna University and UGC autonomous-college rules (R2021/R2022/R2026) |

## Status

| Phase | Scope | Status |
|---|---|---|
| 1 Foundation | Platform, messaging, curriculum core, admissions, student services, finance, portal | In progress (branch `phase-1`) |
| 2 Autonomy core | Examinations, governance, faculty | Planned |
| 3 Compliance & research | IQAC engine, OBE attainment, research and PFMS | Planned |
| 4 Campus operations | Hostel, transport, labs/clinical, placement | Planned |
| 5 Extend | Alumni, library, nursing and deemed packs, integrations, hardening | Planned |

## License

GNU GPL v3. See [license.txt](license.txt).
