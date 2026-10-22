# Intern UAT (PR-08)

Interns walk through one script per role on **campus.localhost** and report every mismatch. Role guides: `docs/usage/roles/`.

## Test logins
Site `campus.localhost`. Password for all: `Campus@Pilot2026` (demo only). Logins are in `docs/usage/demo-data.md`
(for example `admissions@`, `faculty@`, `hod@`, `coe@`, `accounts@`, `student@`, `guardian@` at `sxcce.example.edu`).
Staff go to `/app`; student and guardian go to `/campus-portal`. Use a separate browser profile per role, or log out first.

## How to run
1. Pick your script (`uat/<role>.md`). Run the steps in order. Core path order: admission-officer, accounts, faculty, coe, student; then the other roles.
2. Each step has an expected result. Match it: pass. Anything else: file feedback.
3. Negative checks (marked N) must fail or show nothing; if they succeed that is a **Critical** bug.
4. Do not edit or delete demo records you did not create. Make your own test records.
5. Scripts do not need developer tools; never use Administrator.

## Reporting
Use the **UAT Feedback** list (proposal below). Until it exists, use one row per problem in the shared sheet with the same columns.

| Field | Content |
|---|---|
| Role | login you used |
| Script step | file and step, e.g. `faculty.md step 4` |
| Expected / Actual | one line each |
| Severity | Critical (data leak, wrong money or marks), High (path blocked), Medium (wrong but workaround), Low (wording, layout) |
| Screenshot | attach; include the URL bar |

## Feedback capture: recommendation (coordinator decides)
No existing campus doctype fits: Student Grievance is for students and carries a committee workflow, Feedback Response is
anonymous course feedback, and ERPNext Issue sits in Support, outside the campus areas and roles. Proposal, **docs only, no code written**:

**UAT Feedback** DocType in `campus_platform`, module-less simple form, autoname `UAT-.####`.
- Fields: `tester_role` (Data, default current user), `script` (Select: the 12 scripts), `step` (Data), `expected` (Small Text), `actual` (Small Text), `severity` (Select: Critical/High/Medium/Low), `screenshot` (Attach Image), `status` (Select: New/Triaged/Fixed/Won't Fix, default New), `coordinator_notes` (Small Text).
- Permissions: a new role `UAT Tester` (create, read own via `if_owner`; no delete); `System Manager` and the coordinator read all and edit status.
- Desk: list view with columns severity, script, step, status, owner; filter by status; shown through a link in Administration (or a standalone shortcut), and a tester user created per intern with roles of the role under test plus `UAT Tester`.
- Remove the DocType and role before go-live.
