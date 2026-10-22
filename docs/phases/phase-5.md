# Phase 5 - Extend (Alumni, Library, Nursing & Deemed packs, integrations, migration, hardening)

Goal: complete the long tail: alumni and giving, library integration, segment packs (Nursing INC,
Deemed university), P2/P3 integrations (DigiLocker/ABC, ORCID/Scopus/IRINS, biometrics, extra gateways, e-sign,
OMR), full migration toolkit, research long tail (PhD, ethics, instruments), and production hardening.

BRD: M15-01..04, M13-01/03/04, M08-13/14/15, M17-04 (e-sign), M17-05, M17-07, M16-04 (mobile), M09-06,
M06-09, M01 (perspective plan), segment variations (BRD section 9), NFRs (BRD section 10).
Prerequisites: Phases 1-4 complete, or at least the tasks named in each "Depends on".
Tasks here are largely independent of each other and can be scheduled by pilot demand.

---

## A. Alumni (M15)

### P5-T01 Alumni registration, directory, chapters
BRD: M15-01 | Depends on: P2-T22 | Size: M
Deliverables: Alumni (student link, verified, employer, designation, location, chapter, consent), Alumni Chapter, self-registration web form (matches register no + DOB, otherwise department verification), directory in the portal (opt-in fields only), auto-create Alumni on graduation.
Acceptance criteria
1. Graduating students get Alumni records automatically. The directory shows only fields the alumnus opted to share.
Tests: I - auto-create, verification, privacy filter.

### P5-T02 Events, jobs, mentorship, contributions
BRD: M15-02, M15-04 | Depends on: T01, P3-T07 | Size: M
Deliverables: Alumni Event + attendance, Alumni Job Post (moderated), Mentorship Pairing (alumnus ↔ students), Alumni Contribution (non-financial: guest lecture, placement help, MoU), alumni feedback via Feedback Campaign.
Reports: Contribution summary, Chapter activity. Data points for AQAR 5.4.1.
Acceptance criteria
1. Job posts are visible to students only after TPO approval.
Tests: I - moderation, reports.

### P5-T03 Donations and 80G
BRD: M15-03 | Depends on: T01, P1-T25 | Size: M
Deliverables: Donation Campaign, Donation (donor, campaign, amount, mode, payment via gateway, 80G receipt number, PAN), 80G receipt print, Form 10BD export, endowment tagging to a fund account.
Report: Donation register, AQAR 5.4.2 band.
Acceptance criteria
1. An online donation creates a Payment Entry and an 80G receipt with a sequential number per financial year.
2. The 10BD export contains all eligible donations with PAN and amounts.
Tests: I - payment → receipt, export completeness.

## B. Library integration (M13)

### P5-T04 Koha/SOUL integration
BRD: M13-01, M13-03, M13-04 | Depends on: P1-T24 | Size: M
Deliverables: Library Integration Settings, Koha REST adapter (patron sync of students/staff, fines import → Sales Invoice "Library Fine", checkouts summary), SOUL file adapter, Usage Stats Import (footfall, e-resource logins), E-Resource subscriptions (N-LIST, DELNET, IEEE: cost, period, usage), library no-dues check.
Reports: Library usage per day (4.2.4), Book/journal expenditure (4.2.3), E-resources (4.2.2).
Acceptance criteria
1. A new student appears as a Koha patron within one sync cycle. A Koha fine appears in the student ledger once.
Tests: I - adapters with mocked endpoints, idempotent fine import.

## C. Segment packs

### P5-T05 Nursing pack (INC)
BRD: section 9, M12-06 | Depends on: P4-T12 | Size: M
Deliverables: Nursing programme templates (B.Sc. Nursing, GNM, M.Sc. Nursing), INC requirement data sets (clinical hours, procedures), competency-based outcome model (outcomes per competency instead of NBA POs), INC inspection data pack (faculty, beds, clinical sites, hostel), INC-format reports (placeholders until official formats are supplied).
Acceptance criteria
1. A Nursing-segment institution sees nursing templates and clinical packs enabled by default. NBA-specific screens are hidden.
Tests: I - pack defaults per segment.

### P5-T06 Deemed university pack
BRD: section 4.3 | Depends on: P2-T01, P2-T22 | Size: L
Deliverables: Institution Status "Deemed": statutory bodies (Board of Management, Academic Council, Planning & Monitoring Board, Finance Committee) as Body Type seeds, `degree_awarding_body` = College enforced, degree certificate and convocation management in-house, multi-school (faculty/school) department hierarchy, Ph.D. programme management enabled (T09).
Acceptance criteria
1. Switching a profile to Deemed enables the pack without migration. Earlier batches keep their regulations and certificates.
Tests: I - status switch, certificate issuer behaviour.

## D. Research long tail (M08)

### P5-T07 PhD scholars
BRD: M08-13 | Depends on: P3-T12 | Size: M
Deliverables: Research Scholar (student link, supervisor, co-supervisor, registration date, mode), Doctoral Committee meetings (Body + Meeting), coursework (curriculum), progress reports, synopsis, thesis submission, plagiarism check record, viva, Shodhganga submission link. Data points AQAR 3.4.2.
Acceptance criteria
1. A scholar can't submit the thesis before the minimum duration and coursework completion.
Tests: I - gate checks.

### P5-T08 Ethics approvals and instrument booking
BRD: M08-14, M08-15 | Depends on: P2-T01, P4-T08 | Size: M
Deliverables: Ethics Committee (Body Types IEC/IBSC/IAEC), Ethics Application and Approval (validity, conditions), project link requirement for human/animal studies. Instrument Booking (Asset, slot, internal/external user, charges → Sales Invoice for externals).
Acceptance criteria
1. A sanction flagged "human subjects" can't start expenditure without a valid ethics approval.
2. External bookings invoice per the rate card.
Tests: I - gate, invoicing.

## E. Integrations (M17-05)

### P5-T09 DigiLocker / NAD / ABC
BRD: M17-05 | Depends on: P2-T22, P1-T13 | Size: M
Deliverables: adapters: issue grade sheets/degree data to NAD/DigiLocker (file push first), ABC credit upload (ABC ID on Student), DigiLocker document pull for admissions (consent-based).
Acceptance criteria
1. The export file for a result session passes the adapter's schema validation. Upload status is tracked per student.
Tests: I - schema validation, status tracking (mocked API).

### P5-T10 ORCID / Scopus / Crossref / IRINS sync
BRD: M07-06, M17-05 | Depends on: P3-T21 | Size: M
Deliverables: adapters for ORCID works pull, Scopus author metrics (citations, h-index) if an API key is available, IRINS profile link/import. Scheduled sync with de-duplication by DOI.
Acceptance criteria
1. Sync adds new works without duplicating existing DOIs, and updates citation counts.
Tests: I - mocked API sync and dedupe.

### P5-T11 Biometrics / RFID
BRD: M17-05, M05-02, M07-03 | Depends on: P1-T19 | Size: M
Deliverables: device push API endpoint (token per device), mapping to Student Attendance (course schedule by time + room), Employee Checkin (HRMS), hostel Gate Movement. Device registry and health report.
Acceptance criteria
1. A punch inside a scheduled period in the mapped room marks the student present once. Duplicates are ignored.
Tests: I - mapping, dedupe, auth.

### P5-T12 More payment gateways, e-challan
BRD: M09-06 | Depends on: P1-T25 | Size: M
Deliverables: PayU, Cashfree, BillDesk adapters on the P1-T25 interface, SBI Collect / state e-challan reconciliation import.
Acceptance criteria
1. Each gateway completes the sandbox flow and webhook idempotency tests from P1-T25.
Tests: I - per-adapter contract tests.

### P5-T13 E-signature
BRD: M17-04, M02-03 | Depends on: P1-T08, P2-T02 | Size: M
Deliverables: e-sign adapter (Aadhaar eSign or DSC provider), sign flow for minutes, certificates, UCs; signed PDF stored with a hash in Verifiable Document.
Acceptance criteria
1. A signed document's verification page shows signer, time and certificate status.
Tests: I - mocked provider flow.

### P5-T14 OMR and on-screen valuation
BRD: M06-09 | Depends on: P2-T18 | Size: L
Deliverables: OMR result file import into Valuation Entry. On-screen valuation: scanned script upload per dummy number, examiner annotation UI with question-wise marks.
Acceptance criteria
1. Imported OMR marks reconcile with the script count per bundle. Mismatches are reported.
Tests: I - import reconciliation.

## F. Platform completion and hardening

### P5-T15 Migration toolkit
BRD: M17-07 | Depends on: P1-T28 | Size: L
Deliverables: Migration Batch with source templates for common legacy ERPs/spreadsheets (students, results history with grades per regulation, fees outstanding, employees, assets), dry-run mode, rollback per batch, reconciliation report (counts and totals vs source).
Acceptance criteria
1. A dry run reports all errors without writing. A real run is reversible per batch.
2. Imported historic results reproduce the CGPA in the source within 0.01.
Tests: I - dry run, rollback, CGPA reconciliation.

### P5-T16 Perspective plan and annual benchmarks
BRD: M01 (AQAR 6.2.1) | Depends on: P3-T03 | Size: S
Deliverables: Perspective Plan (period, goals), Annual Benchmark (year, KPI linked to a metric node, target, actual pulled from metric values). Report: plan progress.
Acceptance criteria
1. Actuals update automatically from the locked metric values of the year.
Tests: I - actual pull.

### P5-T17 Mobile apps
BRD: M16-04 | Depends on: P1-T26, P2-T25 | Size: L
Deliverables: React Native/Expo app (student/parent/faculty) on the same whitelisted APIs, push notifications via FCM, offline attendance capture for faculty with sync.
Acceptance criteria
1. Feature parity with the portal for the top 6 student flows. Offline attendance syncs without duplicates.
Tests: I - API contract tests. M - device UAT.

### P5-T18 Production hardening
BRD: section 10 NFRs | Depends on: all | Size: L
Deliverables: load tests (results for 10,000 students, hall tickets, fee generation, broadcasts), backup/restore drill including `encryption_key`, availability plan for exam/result windows, DPDP: consent records audit, retention job, data subject export, access log review, security review (permission matrix tests auto-generated per role × doctype), Tamil translation completeness check.
Acceptance criteria
1. Load targets met: result run for 10,000 students < 30 min, broadcast of 20,000 messages queued < 5 min.
2. Restore drill on a fresh server brings back data including decryptable Aadhaar values.
3. The permission matrix test suite passes for every role.
Tests: load scripts, restore drill log, permission matrix suite.

---

## Phase 5 exit checklist
- [ ] Tasks delivered per pilot priority. Each integration has contract tests with mocks.
- [ ] Hardening report attached (load, restore, permission matrix, DPDP checklist).
- [ ] Blueprint status updated. Usage notes complete.
