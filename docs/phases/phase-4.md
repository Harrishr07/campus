# Phase 4 - Campus operations (Hostel, Transport, Labs & Clinical, Placement)

Goal: the trust runs hostels, mess and transport for its colleges with billing in the student ledger.
Departments run labs (equipment, consumables, experiment records feeding CIA). Nursing runs clinical
rotations with logbooks. The TPO runs drives to offers with eligibility from live results.

BRD: M10-01..06, M11-01..05 (M11-03/04 basic), M12-01..07, M14-01..06.
Prerequisites: Phase 1 company scoping and Shared Service Agreement (P1-T03, T04), approval engine (T07),
messaging (T10), fees and ledger (T23, T24), portal (T26); Phase 2 timetable (P2-T07), CIA templates (P2-T13),
results/CGPA (P2-T19); Phase 3 MoU master (P3-T08), evidence (P3-T04).
Ownership: hostel = trust company (blueprint D4). Transport = per Shared Service Agreement (default trust).

Exit demo: 200 hostel applications from two colleges → rule-based allotment → mess month with rebates →
mess bill invoiced by the trust → outpass with guardian WhatsApp and a late return → bus registration
and pass → lab consumable indent to purchase → experiment records feed CIA → nursing batch rotated across 2
hospital sites with logbook sign-off → placement drive with CGPA/arrear eligibility → offers → NIRF median salary report.

---

## A. Hostel & mess (M10)

### P4-T01 Hostel masters
BRD: M10-01 | Depends on: P1-T04 | Size: M
Deliverables: Hostel (company = trust, gender, served colleges from the Shared Service Agreement), Hostel Block, Hostel Floor, Hostel Room (type, capacity, AC, status), Hostel Bed, Hostel Fee Rate (academic year × room type → Fee Category amounts), Hostel Settings.
Room inventory via Asset Location per room.
Acceptance criteria
1. Room capacity equals the number of active beds. A bed can't exist without a room.
2. A male hostel can't be configured to accept female allotments and vice versa.
Tests: I - master validations.

### P4-T02 Applications and allotment
BRD: M10-02 | Depends on: T01, P1-T09 | Size: L
Deliverables: Hostel Application (student, year, preferences), Allotment Rule (ordered criteria: year of study, distance from home, merit (CGPA/cut-off), category reservation, freshers-only blocks), Allotment Run (bulk; deterministic tie-break), Hostel Allotment (student, bed, from/to, status), Room Transfer Request (approval), waitlist report, allotment order print. Fee invoice from the trust on allotment.
Permissions: hostel users read limited Student fields across member colleges (permission query + field restrictions).
Acceptance criteria
1. The run fills beds strictly by rule order. The same inputs give the same allotment.
2. Students from both colleges are allotted. Invoices are raised by the trust and appear in each student's cross-company ledger.
3. A warden can't read student marks, Aadhaar or guardian income.
Tests: U - rule ordering and tie-break. I - run, invoice company, permission restrictions.

### P4-T03 Mess
BRD: M10-03, M10-06 | Depends on: T02, P1-T23 | Size: L
Deliverables: Mess (type, warehouse), Mess Menu Template (weekly cycle) and published menu, Mess Plan (fixed monthly / dividing system / per meal; rebate rule: min consecutive days), Mess Leave (from outpass or request), Mess Billing Run (monthly: dividing system = (stock issued from the mess warehouse + mess staff cost + overheads) ÷ total man-days, minus rebates) → Sales Invoice by the trust. Mess store via Material Request → Purchase → Stock Entry (issue).
Reports: Mess cost per day, Mess bill summary.
Acceptance criteria
1. The fixture month gives the hand-computed per-day rate and bills. A student on 5 consecutive days' leave (rule ≥4) gets the rebate.
2. Billing twice for the same month posts nothing new.
Tests: U - dividing system calc, rebate rule. I - billing idempotency, stock-based cost pick-up.

### P4-T04 Outpass, gate, visitors, roll call
BRD: M10-04 | Depends on: T02, P1-T10 | Size: M
Deliverables: Outpass (student request in portal, type day/home, approval by warden via approval engine, guardian WhatsApp on approval and on exit/return), Gate Movement (out/in scan via QR on the outpass), late return flag and alert, Visitor Log, Night Roll Call.
Acceptance criteria
1. The guardian gets a message on approval, exit and return. A late return alerts the warden and guardian.
2. Exit without an approved outpass is recorded as a violation.
Tests: I - message triggers, late detection.

### P4-T05 Complaints, inventory, vacating
BRD: M10-05, M10-06 | Depends on: T02 | Size: M
Deliverables: Hostel complaints via ERPNext Issue (issue type, SLA), Room Inventory Check, Hostel Vacating (inventory check, damages → invoice, caution deposit refund via P1-T25).
Warden dashboard: occupancy, open complaints, late returns, dues.
Acceptance criteria
1. Vacating frees the bed, raises damage charges, and refunds the deposit minus damages.
2. Complaint SLA breach escalates per the Issue SLA.
Tests: I - vacating accounting, SLA.

## B. Transport (M11)

### P4-T06 Routes, stops, vehicles, registration, fees
BRD: M11-01, M11-02, M11-05 | Depends on: P1-T04, P1-T23 | Size: M
Deliverables: Bus Stop (geo), Route (ordered stops, times, distance), Vehicle custom fields (FC, permit, insurance, PUC expiry, seating), Transport Fee Slab (zone/distance), Transport Registration (student/staff, stop, year) → invoice by the provider company, Bus Pass (QR), Route Change Request. Expiry alerts (30/7 days). Vehicle Log for fuel.
Reports: Route occupancy vs seats, Students by stop, Transport dues, Vehicle document expiry, Fuel efficiency.
Acceptance criteria
1. Registration is blocked when the route is at seating capacity (waitlist instead).
2. The fee picks the slab by the stop's distance. The invoice comes from the Shared Service Agreement provider.
3. Expiry alerts go to the transport officer at 30 and 7 days.
Tests: U - slab selection. I - capacity, invoice company, alerts.

### P4-T07 GPS and route suggestions (basic)
BRD: M11-03, M11-04 | Depends on: T06 | Size: M
Deliverables: GPS adapter interface + one vendor adapter (webhook positions → Vehicle Position), parent/student "where is my bus" in the portal, ETA alert near the stop. Route suggestion tool: cluster student addresses (geocoded) and propose stops/routes under capacity (OR-Tools VRP), output as a draft Route.
Acceptance criteria
1. A position webhook updates the live map within 30 s. An ETA alert is sent once per trip per stop.
2. The suggestion tool returns routes with no bus over capacity on the demo geodata.
Tests: I - webhook ingestion (mock), alert dedupe. U - VRP wrapper on a small fixture.

## C. Labs, facilities and clinical (M12)

### P4-T08 Labs and equipment
BRD: M12-01, M12-05 | Depends on: P1-T03 | Size: M
Deliverables: Laboratory (room, department, in-charge, technician, courses), equipment as Asset with Location = lab, AMC and calibration via Asset Maintenance, Safety Checklist Template, Lab Safety Inspection, Lab Incident.
Reports: Lab equipment register (NBA), AMC/calibration due, Incident register.
Acceptance criteria
1. Calibration-due items appear 15 days ahead and notify the in-charge.
Tests: I - due computation, notifications.

### P4-T09 Consumables indent to purchase
BRD: M12-03 | Depends on: T08 | Size: S
Deliverables: Lab warehouse per lab, Material Request from the lab with approval (HOD) → Purchase Order → Receipt into the lab warehouse → Stock Entry issue per experiment session.
Report: Consumables consumption by lab.
Acceptance criteria
1. An indent above the HOD limit routes to the Principal (approval engine).
Tests: I - routing, stock movement.

### P4-T10 Experiments and lab records
BRD: M12-04, M12-02 | Depends on: P2-T13, P3-T09 | Size: M
Deliverables: Experiment (course + curriculum, CO, equipment), Lab Batch (split of an offering), Lab Record (student, experiment, observation/record marks, viva, CO) → feeds the CIA lab component (R2022: 75% observation/record + 25% test).
Lab slot conflicts checked against the timetable (P2-T07).
Acceptance criteria
1. Lab Record marks consolidate into the CIA lab component matching the fixture.
2. CO tags on experiments appear in CO attainment (P3-T10).
Tests: I - consolidation, CO flow.

### P4-T11 Facility booking
BRD: M12-07 | Depends on: P2-T07 | Size: S
Deliverables: Facility Booking (room, date/time, purpose, approval), conflict check against the timetable and other bookings. Facility utilisation report. ICT classroom count data point (AQAR 4.1.3).
Acceptance criteria
1. Overlapping bookings or timetable clashes are rejected.
Tests: I - conflict detection.

### P4-T12 Nursing clinical rotations and logbooks
BRD: M12-06 (P0 for nursing) | Depends on: P1-T13, P1-T04 (CLINICAL pack) | Size: L
Deliverables: Clinical Site (hospital, wards/units, capacity per shift, MoU), Clinical Requirement (per program/year: hours per area, procedure counts; INC values as data), Nursing Procedure master, Clinical Rotation Schedule (batch × site × ward × period; capacity and overlap checks), Clinical Attendance, Clinical Logbook Entry (procedure, count, date, preceptor sign-off in the portal), INC-format logbook print (placeholder layout).
Reports: Clinical hours vs requirement per student, Procedures completed vs required.
Acceptance criteria
1. A rotation exceeding ward capacity or double-booking a student is rejected.
2. Logbook entries count only after preceptor sign-off. A preceptor can sign only for students posted to their ward.
3. The student shortfall report matches the fixture.
Tests: U - rotation constraints. I - sign-off permissions, hours calc.

## D. Training & placement (M14)

### P4-T13 Recruiters, drives, eligibility, rounds
BRD: M14-01, M14-02 | Depends on: P2-T19 | Size: L
Deliverables: Recruiter (industry, contacts, MoU link), Placement Eligibility Template, Placement Drive (roles, CTC, eligibility: min CGPA, max standing arrears, history of arrears, branches, batch, gender if specified; rounds child; schedule), Drive Registration (student opt-in in the portal; eligibility auto-evaluated from live results), Round Result (shortlist per round, bulk upload), drive notice print.
Acceptance criteria
1. Eligibility uses live CGPA and arrears. A student clearing an arrear becomes eligible without manual change.
2. Only eligible students can register. Shortlists can only include registered students.
Tests: U - eligibility evaluation. I - live recalculation, registration gate.

### P4-T14 Offers, higher studies, internships, certifications
BRD: M14-03, M14-04, M14-05, M14-06 | Depends on: T13, P1-T13 | Size: M
Deliverables: Placement Offer (CTC, offer letter evidence, accepted/declined, joined), Placement Settings (one-offer rule, dream-offer threshold), Higher Studies Record, Competitive Exam Record (GATE/GRE/CAT/etc.), Internship (organisation, period, mentor, report, evaluation marks → curriculum course or extra activity credit), Capstone Project (team, guide, reviews), Certification Record (NPTEL/vendor). Internship certificate and NOC prints.
Reports: Placement by department/gender/package incl. median salary (NIRF GO), AQAR 5.2.1, 5.2.2, 5.2.3, internships (1.3.4), eligible-not-placed, recruiter-wise offers, NBA placement table. Data points for each.
Acceptance criteria
1. The one-offer rule blocks a second drive registration after an accepted offer, unless the new CTC ≥ the dream threshold.
2. The median salary per program for the last 3 graduating batches matches the fixture.
Tests: U - one-offer rule, median calc. I - reports and data points.

---

## Phase 4 exit checklist
- [ ] Exit demo run. Trust invoices visible in each student's cross-company ledger.
- [ ] Permission review: trust-side roles see only the allowed student fields.
- [ ] Usage notes for hostel, transport, labs, clinical, placement. Blueprint status updated.
