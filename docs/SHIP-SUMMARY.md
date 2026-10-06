# Ship summary: OneBook Campus pilot slice (6 Oct 2026)

## What works end to end (demo site: education.localhost)
Admit applicant (desk Admit button) → fee invoices + payments → course registration → attendance eligibility (R2022 vs R2026 rules) → CIA/ESE marks → Result Run (grades, SGPA/CGPA, SA/AB codes) → publish → Grade Sheet with QR verified at /verify/<code> → student & guardian portal (/campus-portal: fees, attendance, results, circulars) → NAAC 2.6.3 pass % with drill-down to source records.
Plus the Phase 1 foundations: company scoping, institution profile/packs, regulations, positions, approval engine, bulk runner, messaging (WhatsApp/SMS/email with consent), broadcasts/circulars, curriculum + registration, admissions (seat matrix, allotment import, encrypted Aadhaar), finance (fee heads, fines, challans, bank import, refunds on cancellation).
674 tests pass on campus-test.localhost.

## Run the demo
See docs/DEMO.md (logins, demo password, 15-minute click-path, real-vs-stubbed). Rebuild data:
`bench --site education.localhost execute campus.tests.demo.make_demo --kwargs "{'scale':'slice'}"` (refuses on non-demo sites unless developer_mode / site_config campus_demo_site / explicit flag).
Manual checks still needed: portal at 360 px in browser devtools; click the Admit and Issue Grade Sheet buttons once.

## Code
- Repo apps/campus, branch `phase-1` (48 commits ahead of `main`), HEAD as of this summary. Nothing pushed.
- `wip/p1-t18-onboarding`: paused, unreviewed onboarding work.
- Rulings made autonomously: docs/rulings.md (57).
- Deferred minor findings: ~31, listed in the SDD ledgers (apps/campus/.superpowers/sdd/thin-slice/progress.md and /workspace/.superpowers/sdd/phase-1/progress.md); none block the demo per the final review.

## Open before real students/data
1. P1-T17 fix round 2 (Lead permission hook blocks ERPNext Sales users on company-less Leads; +91 number normalisation; oc_lead pre-index duplicate check) — agent was stopped; not done.
2. Rebuild campus-test.localhost (its db password / encryption key appeared in an agent transcript).
3. Auditor sign-off on grant accounting (blueprint D9).
4. Confirm the pilot's own regulations (SXCCE R2022/R2026 used as fixtures).

## Recommended next steps
1. Show the demo to the pilot college; collect feedback.
2. Let feedback pick the next work: remaining Phase 1 tasks (T18-T22, T24-T28), full exam cycle (Phase 2), full IQAC engine (Phase 3).
3. Merge `phase-1` into `main` and push when you're happy (your call).
