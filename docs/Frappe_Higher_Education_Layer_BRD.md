# Business Requirements Document

**Higher-Education Extension Layer on Frappe Education (India)**

Working title: OneBook Campus (placeholder) | Version 0.1 DRAFT | 4 October 2026

Owner: Catherine Jinita, OneBook | Status: For review and validation

## 1. Document Control & Conventions

| Item | Detail |
|---|---|
| Purpose | Define requirements for a higher-education layer on top of Frappe Education / ERPNext for Indian colleges. |
| Audience | Product, engineering, implementation consultants, sales/marketing, pilot institutions. |
| Priority scale | P0 = launch blocker; P1 = needed within first 2 releases; P2 = important, can follow; P3 = later / integrate third party. |
| Coverage rating | None = no evidence of feature in Frappe Education; Partial = school-level or basic only; Base = available via Frappe Education/ERPNext. |
| Validation caveat | Coverage ratings come from public docs, GitHub, forum and competitor pages. They MUST be verified by a code-level audit of the frappe/education and ERPNext apps (Section 12) before commitments are made. |
| Estimates | Effort figures are indicative assumptions, not measured. Re-baseline after the technical audit. |

## 2. Problem Statement

Indian arts & science, nursing and engineering colleges operate under overlapping regulators (university, UGC, AICTE, INC, NAAC, NBA, NIRF, funding agencies via PFMS). Frappe Education provides a sound core (admissions, students, programs/courses, fees, attendance, basic assessment, portal) plus ERPNext accounting, HR and stock. It does not cover the operating reality of a higher-education institution: accreditation data capture, Controller of Examinations operations, academic-council governance, funded-research and PFMS reporting, faculty appraisal, hostel, transport, labs, placements, alumni and student-welfare statutory bodies.

**Problem statement (user view): "As the head of an autonomous engineering college, I cannot run my institution on Frappe Education alone. It covers the basic student, fee and attendance core, and leaves most institution-specific operations and every accreditation/compliance workflow to custom development or separate tools."**

Evidence from community channels: forum and GitHub activity centres on school-level use, customisation of fees/portals/assessment, bugs in fee schedules, attendance tools and imports, and multi-school workarounds (e.g., each school as a Company). College-specific workflows (autonomous exams, NAAC/NBA) are rarely discussed.

## 3. Objectives & Success Measures

| Objective | Measure (target to be agreed) |
|---|---|
| Single system of record for an autonomous engineering college | >= 90% of departments/offices operating in-system at pilot go-live |
| Accreditation as by-product of operations | NAAC/NBA/NIRF datasets generated from live data with < 10% manual re-entry |
| Exam cycle on-platform | Hall tickets to result publication and revaluation without spreadsheets |
| Funded research compliance | UC/SOE and PFMS EAT data prepared in-system for 100% of sanctioned projects |
| Reduce institution-prep time | SSR/AQAR/SAR preparation cycle shortened vs. institution baseline (measure in pilot) |
| Adoption | Faculty and student portal weekly active use above agreed threshold |

## 4. Scope

### 4.1 In scope: three segments

| Segment | Typical regulators / drivers | Lifecycle path | Distinct needs |
|---|---|---|---|
| Arts & Science | Affiliating university, UGC, NAAC (primary), NIRF | Affiliated -> Autonomous -> Deemed university | Syllabus framing, CBCS, COE (post-autonomy), AQAR/SSR, NEP alignment |
| Nursing | INC, state nursing council, affiliating health university, NAAC, NIRF | Affiliated -> (Autonomous/Deemed where eligible) | Clinical rotations, hospital-attached practicals, logbooks, residential hostel, INC inspection data |
| Engineering | AICTE, NBA (primary driver), NAAC, NIRF, affiliating university/autonomy | Affiliated -> Autonomous -> Deemed | CO-PO attainment, lab slots, projects/internships, placements, R&D/consultancy/IPR |

### 4.2 Out of scope (this release)

- K-12 school features beyond what Frappe Education already provides.
- Medical, law, B.Ed, management, and other streams (future segments).
- Full LMS content authoring (integrate Frappe LMS or Moodle).
- Own ILMS build if Koha/SOUL integration is chosen (see M13).

### 4.3 Institution maturity model

Configuration must change with status. An affiliated college follows the university syllabus and exams; an autonomous college owns syllabus, exams and results; a deemed university adds statutory bodies, own degrees, and wider governance. The product shall expose an "Institution Status" setting that enables or disables module packs and workflows, so one customer can graduate from affiliated to autonomous to deemed without migration.

## 5. Stakeholders & Personas

| Persona | Primary needs |
|---|---|
| Principal / Director / Vice-Chancellor | Dashboards, approvals, accreditation readiness, risk alerts |
| IQAC Coordinator | Year-round evidence capture, criterion-wise metrics, AQAR/SSR/SAR/NIRF exports |
| Controller of Examinations (COE) and exam cell | Exam cycle, confidentiality, valuation, results, revaluation, transcripts |
| Head of Department (HOD) | Workload, timetable, course allocation, department metrics, BoS submissions |
| Faculty | Attendance, CIA marks, CO-PO, appraisal, research output, leave, portal |
| R&D Dean / Research Coordinator / PI | Proposals, sanctions, budgets, UC/SOE, PFMS, IPR, publications |
| Registrar / Admissions Officer | Admissions (counselling and management quota), documents, TC, certificates |
| Accounts Officer / Finance | Fees, grants, payroll, audit, PFMS expenditure filing |
| Warden / Transport Officer / Lab In-charge / Librarian | Allocation, billing, tracking, inventory, circulation |
| Training & Placement Officer | Recruiter drives, eligibility, offers, internships, analytics |
| Student / Parent | Portal, fees, results, grievances, certificates, notifications (WhatsApp) |
| Alumni | Registration, events, mentorship, giving |
| External: auditors, NAAC/NBA assessors, funding agencies | Evidence, read-only access, formatted reports |

## 6. Baseline: What Frappe Education Provides

- Student, guardian, instructor records; student applicant to enrolment workflow.
- Programs, courses, batches/terms, scheduling; student groups.
- Fee structures, schedules, fee plans, online payments (releases note custom amounts and fee-plan changes; recent PRs on multi-account/cost-centre fee categories).
- Attendance and basic assessment planning and results; student portal.
- ERPNext: accounting, HR/payroll, procurement, stock, projects (usable foundation for grants, hostel inventory, lab consumables).
- Open source, extensible via custom apps; Frappe Cloud marketplace listing.

Known limitations from community/GitHub signals: school-centric orientation; open issues on applicant web form, fee schedules and attendance tooling; multi-campus handled by workaround; Razorpay-centric Indian payments; no accreditation, COE, hostel, transport, research or placement modules found.

## 7. Competitive Landscape (Reference)

| Product | Relevant strengths (public claims) | Use in our benchmarking |
|---|---|---|
| MasterSoft / IITMS | Hostel admission-to-exit, mess, NAAC/AICTE/NBA oriented higher-ed ERP | Hostel, compliance depth |
| OnCampusERP | NAAC SSR / NBA SAR / NIRF auto-generation, GPS transport, alumni | Compliance engine, transport |
| Unity Edu | PFMS integration, scheme-wise ledgers, UC, NAAC data as by-product | Grants, PFMS |
| Cyborg ERP | Project section (PI onboarding, UC/SOE, fellowships), N-level ILMS, T&P | Research, library, placement |
| Samarth (docs) | Research project & grant management with sanction orders and expenditure | Research accounts |
| Edumerge | Exam management (OMR, re-evaluation), ILMS, alumni, autonomous-college operations | COE, library, alumni |
| Studentink, Zamflux, IMPRES CoE, CampusAlly, EMBASE | Dedicated COE: hall tickets, digital valuation, results, revaluation | COE |
| Fedena, Entab CampusCare, ZeroSuite, Leading Campus, VAPS, Academia ERP | School/college admin, fees, WhatsApp comms, timetable/substitution, alumni | Core and communication |
| IRINS (INFLIBNET) | National research information network for faculty profiles, publications, projects | Integration target |

## 8. Functional Requirements by Module

Format: ID | requirement | priority. All modules shall respect role-based access, audit trails and document attachments (evidence).

### M01 Governance, IQAC & Accreditation

Frappe Education coverage: None | Driver: NAAC, NBA, NIRF, AICTE, UGC

| ID | Requirement | Priority |
|---|---|---|
| M01-01 | Criterion-wise evidence repository (NAAC 7 criteria / metrics; NBA criteria; NIRF parameters) with year, department, owner, and file links | P0 |
| M01-02 | Metric engine: configurable formulas for quantitative metrics computed from live module data; versioned when regulator formats change | P0 |
| M01-03 | AQAR, SSR, NBA SAR and NIRF data export in regulator templates (Excel/PDF), with pre-validation checks for missing evidence | P0 |
| M01-04 | IQAC calendar, meeting agenda/minutes, action-taken tracker | P1 |
| M01-05 | Stakeholder feedback surveys (students, alumni, employers, teachers) with analysis | P1 |
| M01-06 | Statutory committee registry: Anti-Ragging, Grievance, ICC/Women cell, SC/ST cell, Disciplinary, with meeting and report logs | P1 |
| M01-07 | Regulator submission tracker (AICTE approvals, UGC/affiliation renewals, deadlines, alerts) | P1 |

### M02 Academic Governance (Syllabus Framing Council)

Frappe Education coverage: None | Driver: Autonomy rules, UGC autonomy guidelines

| ID | Requirement | Priority |
|---|---|---|
| M02-01 | Bodies master: Board of Studies per department, Standing/Academic committees, Academic Council, Governing Council, with members and terms | P0 |
| M02-02 | Proposal workflow: BoS draft -> committee -> Academic Council -> Governing Council, with versioned documents and comment trail | P0 |
| M02-03 | Meeting management: notice, agenda, quorum, minutes, resolutions, action tracking, e-signatures | P0 |
| M02-04 | Regulation and syllabus publishing: approved version becomes effective for a batch/regulation year; older versions remain for earlier batches | P0 |
| M02-05 | External expert and industry member management for BoS (honorarium, TA/DA via finance) | P2 |

### M03 Curriculum, CBCS & Outcome-Based Education

Frappe Education coverage: Partial | Driver: NBA, NEP, autonomy regulations

| ID | Requirement | Priority |
|---|---|---|
| M03-01 | Regulation-year based curriculum: programs, semesters, credits, course categories (core, elective, audit, co-curricular, value-added) | P0 |
| M03-02 | PEO, PO, PSO, CO master with mapping matrices (CO-PO, CO-PSO) and approval | P0 |
| M03-03 | Assessment-to-CO mapping (CIA, assignments, ESE questions) and attainment computation (direct and indirect) with configurable targets and thresholds | P0 |
| M03-04 | Course registration each semester with prerequisites, credit-load limits, elective seat caps, and add/drop windows | P0 |
| M03-05 | Credit transfer, honours/minor, multi-disciplinary and lateral-entry rules | P2 |
| M03-06 | Audit points / co-curricular credit tracking required for graduation | P1 |

### M04 Admissions

Frappe Education coverage: Partial | Driver: State counselling, management quota, AICTE norms

| ID | Requirement | Priority |
|---|---|---|
| M04-01 | Applicant pipeline for counselling-allotted seats, management quota, lateral entry, PG; imports of allotment lists | P0 |
| M04-02 | Eligibility and document verification checklist (community, transfer, migration, income, etc.) with status and reminders | P0 |
| M04-03 | Seat matrix by program/category/quota with live vacancy | P1 |
| M04-04 | Fee structure by quota/category; refund and withdrawal rules aligned to regulator norms | P1 |
| M04-05 | Lead capture and enquiry CRM with WhatsApp follow-up (leverages OneBook CRM/automation strengths) | P1 |

### M05 Student Lifecycle & Services

Frappe Education coverage: Partial | Driver: NAAC Criteria 2 & 5

| ID | Requirement | Priority |
|---|---|---|
| M05-01 | Onboarding: ID/library/bus/hostel linkage, mentor/class-advisor allocation, code-of-conduct acknowledgement, anti-ragging affidavit | P0 |
| M05-02 | Attendance with 75% (configurable) eligibility rules, condonation workflow, medical leave, on-duty | P0 |
| M05-03 | GPA/CGPA, arrear/backlog, probation and progression rules | P0 |
| M05-04 | Certificates: bonafide, conduct, TC, migration, course completion, transcripts; QR-verifiable | P0 |
| M05-05 | Scholarship and fee-concession management (government portals, institutional, renewals, disbursal tracking) | P1 |
| M05-06 | Grievance redressal with escalation matrix and SLA tracking | P1 |
| M05-07 | Mentoring logs, counselling, health records, insurance | P2 |
| M05-08 | Student activities: clubs, NSS/NCC, sports, events, participation certificates | P2 |

### M06 Controller of Examinations (COE)

Frappe Education coverage: Partial | Driver: Autonomy; university regulations

| ID | Requirement | Priority |
|---|---|---|
| M06-01 | Exam calendar, notification, eligibility check, registration (regular, arrear, supplementary), exam fee collection | P0 |
| M06-02 | Hall ticket, seating plan, invigilator duty roster, attendance sheets, malpractice register | P0 |
| M06-03 | Question paper workflow: setter/scrutiniser nomination, bank, moderation, confidential release and printing log | P0 |
| M06-04 | Dummy/code numbering, answer-script tracking, valuation allocation (internal/external examiners), remuneration | P0 |
| M06-05 | Mark entry with moderation, grace rules, result processing, grade sheet, consolidated mark sheet | P0 |
| M06-06 | Revaluation / photocopy / scrutiny workflow; result publication with passing board approval | P0 |
| M06-07 | Transcript, provisional and degree certificate generation; convocation list | P1 |
| M06-08 | Continuous Internal Assessment (CIA) schedule, marks lock, and audit | P0 |
| M06-09 | Optional: on-screen valuation, OMR integration | P3 |

### M07 Faculty & Staff Lifecycle

Frappe Education coverage: Partial | Driver: NAAC Criterion 2/3, AICTE norms

| ID | Requirement | Priority |
|---|---|---|
| M07-01 | Recruitment, qualification verification against AICTE/UGC norms, appointment, probation, confirmation | P1 |
| M07-02 | Workload: theory/lab/tutorial hours, course allocation, department-wise load balancing | P0 |
| M07-03 | Timetable generation with room/lab/faculty constraints; leave and substitution management | P0 |
| M07-04 | Appraisal: API / self-appraisal, student feedback, HOD review, CAS promotion tracking | P1 |
| M07-05 | Professional development: FDPs, workshops, conferences, certifications with evidence | P1 |
| M07-06 | Faculty profile aggregating publications, patents, projects, PhD guidance; sync with IRINS/Scopus/ORCID where available | P1 |
| M07-07 | Payroll, PF/ESI, TDS via ERPNext HR with pay-scale and increment rules for aided and self-financing staff | P0 |

### M08 Research, Development & Funded Projects (incl. PFMS)

Frappe Education coverage: None | Driver: DST, SERB, AICTE, UGC, ICMR, industry; GFR; PFMS

| ID | Requirement | Priority |
|---|---|---|
| M08-01 | Research centre / department / cell master with coordinators and committees | P1 |
| M08-02 | Proposal pipeline: call tracking, internal review, submission, outcome | P1 |
| M08-03 | Sanction register: agency, scheme, PI/co-PI, sanction order, instalments, duration, extensions | P0 |
| M08-04 | Budget heads per project (equipment, consumables, manpower, travel, contingency, overheads) with re-appropriation approvals | P0 |
| M08-05 | Project-wise ledger linking to ERPNext accounting (cost centre/project) and purchases against sanction | P0 |
| M08-06 | Utilisation Certificate (UC) and Statement of Expenditure (SOE) generation in agency formats, with audit trail | P0 |
| M08-07 | PFMS support: structured export/import for EAT (expenditure filing, advances, transfers) and UC; vendor/bank master consistency; API integration where agency access permits | P0 |
| M08-08 | Progress reports, milestone tracking, deliverables, mid-term reviews; project closure and asset handover | P1 |
| M08-09 | Project staff (JRF/SRF/project assistants): fellowship, recruitment, payroll as per sanction | P1 |
| M08-10 | Consultancy projects: estimate, agreement, GST invoicing, revenue sharing, deliverable tracking | P1 |
| M08-11 | IPR: invention disclosure, patent lifecycle, copyright/design, committee approval, licensing revenue share | P1 |
| M08-12 | Publications/conference/books register with indexing (Scopus/WoS/UGC-CARE), links to faculty profile and NAAC/NIRF metrics | P1 |
| M08-13 | PhD scholar management: registration, DC meetings, coursework, thesis, viva, Shodhganga submission | P2 |
| M08-14 | Research ethics/IEC/IBSC approvals and animal/human-subject compliance (esp. nursing/health) | P2 |
| M08-15 | Research equipment / central instrumentation facility booking and charges | P2 |

### M09 Finance & Accounts (extension of ERPNext)

Frappe Education coverage: Base | Driver: Statutory audit, GFR, AICTE

| ID | Requirement | Priority |
|---|---|---|
| M09-01 | Fee heads: tuition, exam, hostel, transport, library, lab, development; concessions, refunds, fine rules; challan and receipt formats | P0 |
| M09-02 | Multi-account and cost-centre mapping for fees, grants and trust/society entities | P0 |
| M09-03 | Department/scheme budgeting, budget vs. actual | P1 |
| M09-04 | Student fee ledger and dues across modules (hostel, transport, exam) | P0 |
| M09-05 | Audit pack: day book, ledgers, grant statements, fixed-asset register; GST/TDS compliance for consultancy | P1 |
| M09-06 | Payment gateways beyond Razorpay (Indian UPI/netbanking aggregators, bank collect, e-challan for state portals) | P1 |

### M10 Hostel & Mess

Frappe Education coverage: None | Driver: Institution policy; safety norms

| ID | Requirement | Priority |
|---|---|---|
| M10-01 | Hostel, block, floor, room, bed master; capacity and category rules | P0 |
| M10-02 | Allotment by merit/category/year/course; transfers; vacancies; waitlist | P0 |
| M10-03 | Mess: menu planning, preferences, attendance, monthly billing, rebates for leave | P0 |
| M10-04 | Entry/exit, outpass/leave approval with guardian notification, visitor log | P1 |
| M10-05 | Warden dashboards, complaints and maintenance tickets, inventory per room | P1 |
| M10-06 | Fee integration and refunds on vacating; stock integration for mess store | P1 |

### M11 Transport

Frappe Education coverage: None | Driver: Institution policy; road safety

| ID | Requirement | Priority |
|---|---|---|
| M11-01 | Routes, stops, vehicles, drivers; student/staff allocation | P1 |
| M11-02 | Distance- or zone-based fee generation; passes | P1 |
| M11-03 | GPS integration, live tracking and parent/student ETA alerts | P2 |
| M11-04 | Route optimisation: suggest routes/stops from student address clusters, capacity and time constraints | P2 |
| M11-05 | Fuel, maintenance, insurance/FC expiry alerts; driver payroll via HR | P2 |

### M12 Laboratory & Facility Management

Frappe Education coverage: None | Driver: NBA, AICTE, INC norms

| ID | Requirement | Priority |
|---|---|---|
| M12-01 | Lab master with equipment inventory, AMC, calibration schedule, condition status | P1 |
| M12-02 | Slot allocation by batch/course/faculty with timetable constraints and conflict detection | P1 |
| M12-03 | Consumables stock and indent -> purchase flow (ERPNext stock/buying) | P1 |
| M12-04 | Experiment list per course, lab records, CO mapping, viva/record marks capture | P1 |
| M12-05 | Safety logs and checklists (fire, first aid, MSDS), incident register | P2 |
| M12-06 | Nursing: clinical rotation scheduling across hospital sites, procedure logbooks, preceptor sign-off, INC-format records | P0 (Nursing) |
| M12-07 | Classroom, seminar-hall and facility booking with approvals | P2 |

### M13 Library

Frappe Education coverage: None | Driver: NAAC Criterion 4, AICTE

| ID | Requirement | Priority |
|---|---|---|
| M13-01 | Recommended: integrate Koha/SOUL via APIs (member sync, dues to fee ledger, usage statistics) instead of rebuilding | P3 |
| M13-02 | If built: accession, MARC21 cataloguing, circulation, fines, Web OPAC, barcode/RFID | P3 |
| M13-03 | E-resource and journal subscription tracking (INFLIBNET, N-LIST, DELNET) with usage reports | P2 |
| M13-04 | Institutional repository / Shodhganga linkage | P2 |

### M14 Training & Placement and Internships

Frappe Education coverage: None | Driver: NAAC Criterion 5, NBA, NIRF GO

| ID | Requirement | Priority |
|---|---|---|
| M14-01 | Company/recruiter master, drive pipeline (invite, PPT, tests, interviews, offers) | P1 |
| M14-02 | Eligibility rules (CGPA, backlogs, branch), registration and shortlisting | P1 |
| M14-03 | Offers, packages, joining, analytics by department/gender; higher-studies tracking (GATE/GRE/CAT) | P1 |
| M14-04 | Internship MoUs, allocation, reports, evaluation, certificates; project/capstone management | P1 |
| M14-05 | Skill/certification tracking (NPTEL, vendor certs) and training attendance | P2 |
| M14-06 | Industry MoU and industry-academia register for NBA/NAAC | P2 |

### M15 Alumni & Advancement

Frappe Education coverage: None | Driver: NAAC Criterion 5/7, NIRF

| ID | Requirement | Priority |
|---|---|---|
| M15-01 | Alumni self-registration, verification, directory, chapters | P2 |
| M15-02 | Events, newsletters, job board, mentorship | P2 |
| M15-03 | Donations / endowments with receipts (80G) and campaign reporting | P2 |
| M15-04 | Alumni feedback and contribution evidence for accreditation | P2 |

### M16 Communication & Engagement

Frappe Education coverage: Partial | Driver: Parent/student expectations

| ID | Requirement | Priority |
|---|---|---|
| M16-01 | WhatsApp Business API, SMS, email, push with templates (fees, attendance, results, exam, hostel) | P0 |
| M16-02 | Role- and group-based broadcast; consent and opt-out logging | P0 |
| M16-03 | Notice board, circulars, and approval before release (e.g., marks) | P1 |
| M16-04 | Mobile apps/PWA for students, parents, faculty (React Native/Expo option) | P1 |

### M17 Platform, Multi-Campus & Integrations

Frappe Education coverage: Partial | Driver: Scalability, security

| ID | Requirement | Priority |
|---|---|---|
| M17-01 | Multi-institution tenancy: several colleges (arts, nursing, engineering) under one trust, with shared services (hostel, transport, library) and separate academic records | P0 |
| M17-02 | Role/permission model aligned to institutional hierarchy (principal, dean, HOD, coordinators, committees) | P0 |
| M17-03 | Generic multi-level approval workflow engine with delegation and SLA escalation | P0 |
| M17-04 | Document management: versioning, e-signature, QR verification | P1 |
| M17-05 | Integrations: PFMS exports/API, IRINS, Scopus/ORCID, NAD/ABC (Academic Bank of Credits) where applicable, DigiLocker, state scholarship portals, biometrics/RFID, GPS, payment gateways | P1 |
| M17-06 | Reports and BI dashboards; data export for regulators | P0 |
| M17-07 | Data migration toolkit from legacy ERPs and spreadsheets | P1 |

## 9. Segment-Specific Variations

| Area | Arts & Science | Nursing | Engineering |
|---|---|---|---|
| Primary accreditation | NAAC, NIRF | INC compliance, NAAC, NIRF | NBA, NAAC, NIRF, AICTE |
| Outcome model | Programme/course outcomes under NEP | Competency-based, clinical outcomes | CO-PO-PSO attainment (NBA) |
| Practicals | Science labs | Clinical postings, skill labs, logbooks | Engineering labs, projects, internships |
| Residential | Optional | Usually mandatory hostel | Hostel + transport common |
| Research | UGC/DST, publications | ICMR/state health bodies, ethics approvals | DST/SERB/AICTE, consultancy, patents |
| Placement | Moderate | Hospital placement / higher studies | High priority, drives ranking |

## 10. Non-Functional Requirements

| Category | Requirement |
|---|---|
| Security & privacy | Role-based access, field-level permissions for marks and confidential exam data, full audit log, encryption in transit/at rest, compliance with India DPDP Act 2023 for student data, consent management |
| Confidentiality | Exam paper and valuation data accessible only to authorised roles with time-bound release |
| Availability | Target >= 99.5% during exam, admission and result windows; backup with tested restore |
| Performance | Bulk jobs (hall tickets, results for thousands of students) complete within agreed time via background queues |
| Scalability | Single instance to support multiple colleges and tens of thousands of students |
| Usability | Mobile-first portals, English plus regional language support (e.g., Tamil), accessibility basics |
| Configurability | Regulation-year rules, grading schemes, fee heads and workflows configurable without code |
| Extensibility | Delivered as Frappe app(s) layered on Frappe Education, avoiding core forks; upgrade-safe against Frappe versions |
| Data portability | Open exports; documented APIs/webhooks |
| Auditability | Every accreditation figure traceable to source records and evidence |

## 11. Integration Inventory

| System | Purpose | Mode | Priority |
|---|---|---|---|
| PFMS (EAT, UC, SOE) | Grant expenditure, UC, advances | Structured export/import first; API if available | P0 |
| IRINS / INFLIBNET | Faculty research profiles | API/import | P2 |
| Scopus / WoS / ORCID | Publication metadata | API/import | P2 |
| WhatsApp Business API / SMS | Notifications | API | P0 |
| Payment gateways | Fees | API | P0 |
| State scholarship and counselling portals | Allotment and scholarship data | File import | P1 |
| Koha / SOUL | Library | API | P3 |
| Biometric / RFID / GPS | Attendance, access, tracking | Device APIs | P2 |
| DigiLocker / ABC | Certificates and credits | API | P2 |
| Frappe LMS / Moodle | Learning content | Connector | P3 |

## 12. Delivery Approach & Phasing (Indicative)

| Phase | Focus | Modules |
|---|---|---|
| 0 - Validate (4-6 weeks) | Code-level audit of frappe/education and ERPNext; 3-5 institution interviews (one per segment, one autonomous engineering college as design partner); confirm regulator templates | All |
| 1 - Foundation | Platform, workflow engine, regulation-year model, communications | M17, M16, M03 (core), M04, M05, M09 |
| 2 - Autonomy core | COE, governance councils, faculty workload/timetable | M06, M02, M07 |
| 3 - Compliance & research | IQAC engine, OBE attainment, R&D + PFMS | M01, M03 (OBE), M08 |
| 4 - Campus operations | Hostel, transport, labs, placements | M10, M11, M12, M14 |
| 5 - Extend | Alumni, library integration, nursing pack, deemed-university pack | M15, M13, nursing variants |

Note: earlier internal estimates (months of effort, rupee cost per module) were rough and unvalidated; replace with estimates from Phase 0.

## 13. Assumptions, Risks & Open Questions

### Assumptions

- Customers are Indian colleges operating under UGC/AICTE/INC and state regulations.
- Regulator formats (NAAC, NBA, NIRF) change; the product must treat them as configurable data, not code.
- PFMS direct API access may be limited to registered agencies; file-based exchange is the safe baseline.

### Risks

| Risk | Mitigation |
|---|---|
| Frappe Education core instability / upstream changes | Build as separate apps; pin versions; contribute fixes upstream |
| Regulator template changes (NAAC binary accreditation, NBA revisions) | Metric engine with versioned formulas; maintain regulator-watch process |
| Scope breadth vs. team size | Strict phasing; integrate rather than build (library, OSV) |
| University-specific exam rules vary widely | Rule engine and regulation-year configuration; design partners from multiple universities |
| Data privacy for minors and student records | DPDP-aligned consent, access logs, retention policy |
| Competition from entrenched ERPs | Differentiate on open-source flexibility, accounting depth (ERPNext), research/PFMS and implementation speed |

### Open questions

- Which pilot institution and university regulations will anchor the first release?
- Do customers want a replacement ERP or a layer beside existing tools (e.g., existing library or hostel software)?
- Which PFMS interactions (EAT, UC, SOE, sanction) are accessible to our target institutions via file vs API?
- Pricing and packaging: per student, per module, or per institution?
- Hosting model: Frappe Cloud, institution-hosted, or managed by OneBook?
- Which Tamil Nadu-specific processes (TNEA, e-Pass, Anna University/other regulations) must be first-class?

## 14. Traceability: Compliance to Modules

| Regulatory item | Modules |
|---|---|
| NAAC (7 criteria, AQAR, SSR) | M01, M03, M05, M07, M08, M13, M14, M15 |
| NBA (CO-PO, SAR) | M01, M03, M06, M07, M12, M14 |
| NIRF (TLR, RPC, GO, OI, Perception) | M01, M05, M07, M08, M14 |
| AICTE / UGC / INC norms | M01, M04, M07, M12 |
| PFMS / GFR (EAT, UC, SOE) | M08, M09 |
| Anti-ragging, grievance, ICC | M01, M05 |

## 15. Source References

- Frappe Education repository and docs: github.com/frappe/education; docs.frappe.io/erpnext/education-module-in-erpnext
- Frappe Forum Education category: discuss.frappe.io/c/erpnext/schools-college-education/40
- PFMS EAT module overview: dst.gov.in EAT module PDF; cga.gov.in PFMS pages
- UC manual (PFMS): dst.gov.in UC Manual for Agencies
- Competitors: oncampuserp.com, unityedu.ai, cyborgerp.com, edumerge.com, iitms.co.in, databus.co/campusally, docs.samarth.ac.in, zerosuite.in
- Autonomous-college process references: srcas.ac.in COE manual; nasccbe.ac.in regulations; gcoej.ac.in autonomy rules; jct.ac.in COE
- IRINS: wii.gov.in IRINS page (INFLIBNET)

## 16. Requirement Additions v0.2 (22 October 2026)

Source: review of an external team's "BRD for Campus" (not adopted as scope). Only points that strengthen this BRD are taken. IDs continue the module numbering above; P-levels use the same scale.

### 16.1 Functional additions

| ID | Requirement | Priority |
|---|---|---|
| M03-07 | Prerequisites evaluated from published results, recognised transfers and approved waivers; missing evidence sends the registration to review, never auto-passes | P0 |
| M03-08 | Course registration: cumulative term credit limits across all registrations; deadlines enforced on amendments; every apply/cancel bound to the exact Program Enrollment it was made for | P0 |
| M03-09 | Subject equivalence and waiver register (source/target course, regulation, credit treatment, evidence); one credit can satisfy one requirement only, including external MOOC/NPTEL credit | P1 |
| M04-06 | Staff bulk upload of candidates with validation preview, row-level outcomes and idempotent retry; same rules as manual entry and API | P0 |
| M04-07 | Duplicate candidate detection on name + DOB + qualifying-exam identifiers, with reviewer link/keep decision; shared phone or email alone is not a duplicate | P0 |
| M04-08 | Seat matrix strict mode: a missing program/quota/category row blocks admission unless an authorised override is logged; overrides never raise approved intake | P0 |
| M04-09 | Admission approval separate from joining confirmation; Program Enrollment, tuition invoice, ID issue and attendance start follow joining; pre-joining money is an advance, not an invoice | P0 |
| M04-10 | Reporting dates, temporary clearance, late joining (with effective date) and no-show referral to cancellation and refund | P1 |
| M04-11 | Lateral entry per program: accepted qualifications, separate intake, permitted entry semester, curriculum mapping, waivers and bridge courses, remaining credits and duration | P0 |
| M05-09 | Student lifecycle state model with configurable transitions and effective dates: applicant, admitted, joined, active, on break, discontinued, withdrawn, cancelled, readmitted, study completed, award eligible, graduated, alumni | P0 |
| M05-10 | Discontinuation, readmission and semester reallocation/repeat: placement by academic review, curriculum matching, outstanding subjects, fee adjustment, history preserved, no duplicate enrollment or charge on retry | P0 |
| M05-11 | Student record correction workflow: old and new values, evidence, approver, effective date | P1 |
| M05-12 | Attendance from each enrollment's attendance start date over sessions actually conducted; session states scheduled/conducted/cancelled/rescheduled/makeup; configurable on-duty and leave treatment; corrections after the deadline need approval | P0 |
| M05-13 | Mentoring: counselling notes visible only to the mentor and designated staff; parent interaction records with follow-up owners | P1 |
| M05-14 | Certificates: correction, supersession and reissue linked to the original; certificates that imply a status change (TC) route the status change through the lifecycle approval | P1 |
| M05-15 | Completion: credit completion check against the curriculum, separate study-completed and award-eligible states, degree-awarding authority validated per institution and program | P0 |
| M06-10 | Affiliated mode: university exam registration export and result import in agreed file formats, row validation, rejected rows, transmission and acknowledgement references | P0 |
| M06-11 | Improvement examinations; former students may register for arrear examinations within attempt and duration rules | P1 |
| M06-12 | Result run pre-validation: every course has a course type and applicable rules; incomplete configuration blocks the run instead of leaving courses ungraded | P0 |
| M09-07 | Concessions per fee subhead and semester with sub-types, calculation order and caps; one of each sub-type per admission, subhead and semester; bulk uses the same rules (values to be confirmed with the pilot college) | P1 |
| M14-07 | Student projects: teams, guide allocation, reviews, submission, viva, marks transfer to assessment; industrial visits with evidence | P1 |
| M05-08a | Activities (clubs, NSS/NCC, sports, events) feed achievements; external credit recognition only through M03-09 | P2 |
| M01-08 | Official document register: approval, affiliation and accreditation documents with authority, reference, academic year, validity and expiry alerts | P1 |
| M01-09 | AISHE dataset export from verified records | P1 |
| M17-08 | ABC/NAD academic-record export file with identifier mapping, validation and correction tracking (API remains P2) | P1 |
| M01-06a | Confidential cases (anti-ragging, internal complaints, disciplinary): case assignment by committee, restricted evidence, higher-level review, decisions applied through controlled processes | P1 |

### 16.2 Non-functional additions

| Category | Requirement |
|---|---|
| Idempotency | Every bulk job, import and retryable action has a stable key; a retry returns the earlier result and never creates a second student, enrollment, invoice or charge |
| Consistent validation | Business rules run server-side and identically for desk forms, bulk jobs and permitted APIs, and are re-checked at commit |
| Mandatory approval | A configurable list of sensitive document types cannot be submitted when no approval policy matches; the attempt is blocked and flagged for configuration |
| Separation of duties | System administration does not confer business approval; entry, verification, approval and publication are separately assignable |
| History preservation | Amendments and reversals carry reason and source reference; historical enrollments, marks, attendance and posted transactions are never deleted |
| Attachment and export security | Attachments, reports and exports obey the same company and record permissions as their source documents |
| Operational readiness | Backup with a tested restore, migration reconciliation report, role-permission matrix review and acceptance testing before each pilot go-live |
