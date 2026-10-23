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
6. A path such as **Admissions > Enquiries > Lead** means: the Admissions entry in the desk dock (open **OneBook Campus** from the Apps screen, or the area icon on the desktop), then the **Enquiries** section of its sidebar, then **Lead**. Each area's sidebar starts with Home and ends with Reports and Setup.

## Reporting
Every tester login (on a demo site) holds the **UAT Tester** role. Open **Administration > UAT > UAT Feedback** (or `/app/uat-feedback`) and click **Add UAT Feedback** for each problem.
The student and guardian logins are portal-only and cannot open the desk: report their findings from a staff login, naming `student.md` / `guardian.md` as the script.

| Field | Content |
|---|---|
| Tester (login) | Filled in for you; the login you used |
| Script, Step | The script file and step, e.g. `faculty`, step `4` (negative checks: `N1`) |
| Expected / Actual | One line each |
| Severity | Critical (data leak, wrong money or marks), High (path blocked), Medium (wrong but workaround), Low (wording, layout) |
| Screenshot | Attach; include the URL bar |

You see only your own rows and cannot change Status or Coordinator Notes. The coordinator (role **UAT Coordinator** or System Manager) sees every row, sets Status (New, Triaged, Fixed, Won't Fix) and writes notes.

## Remove before go-live
UAT Feedback and the UAT Tester / UAT Coordinator roles are for the UAT period. The kit grants the tester role only on demo or developer-mode sites. Before go-live delete the UAT Feedback DocType (after exporting the rows) and both roles.
