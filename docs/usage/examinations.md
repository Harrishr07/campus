# Examinations: CIA entry and lock (P2-T13)

Desk: **Examinations** workspace.

## Set up (COE)
1. **CIA Component Template**: one per regulation and course type. Seeds exist for R2022 Theory (two
   assessments of 100, each 40 assignment + 60 test, converted to 40), R2022 Lab (75 observation/record
   + 25 test, converted to 60) and R2026 Theory (the same assessments converted to 35, plus up to 5
   attendance marks from the regulation's Attendance Rule bands). Each component is entered out of
   `max_marks` and is worth `weight` converted marks. The weights plus the attendance maximum must equal
   the Exam Rule Set's CIA maximum. A template locks once its regulation is Effective.
2. **CIA Schedule**: one per course offering. The template is picked from the offering's curriculum
   regulation and course type. Set the assessment dates and the **entry deadline**. Only the COE can set or
   change the deadline, and only before it has passed; after that only an approved unlock reopens entry.
3. The offering's faculty fill in the **question pattern**. Each question has a component, a maximum, a CO tag
   and a Bloom level, and the questions of a component must add up to its entered-out-of marks.

## Enter marks (faculty)
- Open the offering's **Mark Sheet Entry**. Saving it creates one CIA question row for each student and
  question. Enter the marks, and tick **Absent** for a student who missed an assessment; that
  component then scores 0.
- Every save works out each student's **CIA** = round(sum of marks / out of × weight) + attendance marks. You
  can do this while the Exam Session is still Draft. ESE marks need the session to be in Marks Entry.

## Lock and unlock
- At the entry deadline the CIA freezes for everyone. An hourly job then consolidates each sheet once
  more, so the attendance marks are the ones on record at the lock. ESE entry is not affected.
- To change CIA after the lock, the faculty raise a **CIA Unlock Request** (reason, unlock until) and
  click Request Approval. The seeded policy "CIA Unlock Approval" routes it to the company's COE.
  Once it is approved, CIA can be edited until the unlock-until time.
- Once a student has a Student Result in the session, an approved CIA Unlock Request does not let the faculty change that
  student's CIA. Only the COE can, and the results are then run again.

## Who sees what
Faculty edit only their own offerings, an HOD reads the offerings of their department's programmes, and the
COE reads and edits everything. Every change is versioned.

## Reports
- **CIA Status by Offering**: the deadline, Open / Locked / Unlocked, students, absentees and average CIA.
- **CIA Marks Audit Trail**: every CIA question-mark and CIA change (who, when, old to new), plus each unlock
  request and the decision on it.

# Examinations: exam registration and exam fee (P2-T14)

## Set up (COE)
1. **Exam Session**: set Registration Opens, Registration Closes (the last day without a late fee), Exams Start / End and the Exam Schedule (one row per course: date, FN/AN).
2. **Exam Fee Rate** (Examinations > Masters): fee per course for the company (or one program), and late fee slabs in days after the closing date, e.g. 1-7 days ₹100, 8-15 days ₹250. Past the last slab, registration is closed.
3. Lock the term's **Attendance Eligibility Run** (Student Services). Registration reads only locked runs.

## Create registrations
On the Exam Session, **Create Exam Registrations** (optionally for one program) queues a bulk run. Each student gets one Exam Registration with:
- the term's courses they attend (Current; Dropped when their Course Registration says so), without Internal Only courses;
- arrears: courses last published as U, AB or WD (no offering).

Running it again adds only missing courses; confirmed registrations are not touched.

Eligibility per course: SA (from the locked run; an approved condonation counts) bars the term's courses, while arrears stay registrable (R2022 cl. 15.1). **Detained** (with a reason) bars the term's courses. **Debarred (Malpractice)** bars every course.

## Confirm (student)
On /campus-portal the student sees the courses and their eligibility, and presses **Confirm registration**. The fee is the rate × eligible courses, plus the late fee slab of the days after the closing date. A background job raises the Sales Invoice under the Exam fee head. Guardians can see the registration, but only the student can confirm it.

Exam dues do not stop registration. They block hall tickets (`campus.examinations.api.exam_dues_block`).

# Examinations: hall tickets (P2-T15)

## Generate (COE)
1. On the Exam Session, schedule every course that will be sat (Exam Schedule) and set **Hall Tickets Released On**.
2. Press **Generate Hall Tickets**. A bulk run gives each Exam Registration one Hall Ticket:
   - **Issued**: the student's photo (Student image), the eligible courses with their date and slot, and a QR. The QR is a Verifiable Document, and /verify shows the exam session, academic term, registration status and ticket status.
   - **Withheld**, with reasons: debarred; attendance shortage (SA) or detention when no eligible course is left (an SA student still sits eligible arrears); registration not confirmed; unpaid Exam-head dues (`exam_dues_block`). A withheld ticket has no valid QR.
3. An eligible course with no exam date fails that student's item in the bulk run, so schedule it and run again.

Running it again is safe. An unchanged ticket keeps its QR. A changed one (dates, courses, photo, status) has its QR revoked and a new one issued. A ticket that becomes withheld has its QR revoked.

The withheld list is in Examinations > Transactions > **Withheld Hall Tickets**.

## Download (student)
On /campus-portal, the exam registration card shows the hall ticket. A withheld student sees the reason. An issued ticket can be downloaded (PDF) once the release time has passed. Students and guardians can open only their own (or their ward's) issued, released tickets.

# Examinations: halls, seating, invigilation, exam attendance, malpractice (P2-T16)

## Exam Halls
An Exam Hall is a **Room** with Room Type "Exam Hall". Set **Seat Rows**, **Seat Columns** and any **Blocked Seats** (pillar, broken bench). Seating Capacity becomes rows × columns minus the blocked seats. Seats are labelled R1C1 (row 1 is the front).

## Seating Plan (COE)
1. Generate the hall tickets first: only students with an **Issued** hall ticket listing a course on that date and slot get a seat.
2. New **Seating Plan**: Exam Session, date, slot (FN/AN) and the Exam Halls to use. Save, then press **Generate Seating**.
3. Courses are interleaved so that no two row or column neighbours write the same course when the mix allows it. "Neighbours with the Same Course" shows 0 unless the mix leaves no other way. Blocked seats stay empty. If the students outnumber the seats, generation is refused: add a hall.
4. The result is the same every time for the same input. Changing the halls clears the seats until you generate again.
5. Prints: **Seating Chart** (the grid per hall) and **Hall Attendance Sheet** (one page per hall with signature and answer-script columns).

## Exam attendance
On the Seating Plan, tick **Absent** on a seat, or call `campus.examinations.api.mark_exam_absent`. The Result Run then grades that course **AB**, even if marks were entered. Once attendance is marked, the plan cannot be re-seated.

## Invigilation Roster (COE)
One per Exam Session. Optionally list the faculty pool; left empty, every active teacher of the college is used. Press **Generate Roster**: each hall used in the session's seating plans gets its invigilators (Invigilators per Hall). Duties are balanced within one per teacher for each session type (FN, AN): the hardest-to-staff halls are filled first, then duties are moved from busier to lighter teachers. **Largest Duty Gap** shows the result; a gap above one (leave or own-course exclusions leave no fairer roster) is warned, so widen the pool. Nobody invigilates a hall where a course they teach this term is written, and nobody on approved leave that day is used. A hall nobody can take stops the roster with its name. Print: **Invigilation Order**.

## Malpractice Report
An invigilator (Academics User) files the report: student, course (must be one the student is registered for), category, description and evidence. Upload evidence as **private** files yourself (another user's upload cannot be claimed); they are attached to the report, and an amendment keeps them. Reports are confidential: the COE, the Principal, Dean Academics and System Managers read all of them, and an invigilator reads only their own (and its evidence). Leave the committee decision empty and **Request Approval**. The seeded policy sends it to the COE position holder of the college, who records the **Committee Decision** and remarks on the form (only the COE and System Managers can write them) and then approves; a report the COE files should go to a Principal-level Approval Policy instead. When a **Debarment** is approved, the student's Exam Registration of that session is debarred and every course becomes "Not eligible (Debarred)". The student is left out of seating at once. Generate the hall tickets again to withdraw the ticket. Only a System Manager can cancel an approved report, which lifts that debarment.

## Dummy numbers and valuation (P2-T18)
1. **Dummy numbers (Exam Confidential).** After exam attendance is marked, call `campus.examinations.dummy_numbers.generate_dummy_numbers` (POST) with the session and course. Every student seated for that course and not absent gets a random 8-digit number. Running it again adds only the students who have no number yet. It also voids the number of a student marked absent since the last run, and restores the number if that mark is lifted. Only Exam Confidential can open the **Dummy Number Map**, which links a number to a student. It is never shared and keeps no version history.
2. **Answer Script Bundle (COE or Exam Confidential).**
   - Enter the packet number, course and expected count, the scripts by dummy number (tick Received), and the question pattern (question and maximum).
   - Each script must be a live dummy number of the course and can sit in one bundle only.
   - The expected count cannot be changed after the first save.
   - A bundle can be set to **Complete** only when all the expected scripts are received, and only a Complete bundle can be allocated. Once a bundle is allocated, its scripts and status are fixed.
   - Movements (from, to, handed to) are stamped with the user and time and cannot be changed later.
3. **Valuation Allocation (COE).**
   - Allocate the bundle for round 1 and round 2, each to a different examiner: Internal (Employee) or External (External Member), with the examiner's login and a deadline.
   - A teacher of the course in that term is refused. To allow it, tick the Exam Rule Set's **Allow Course Teacher as Examiner** for every regulation in the bundle.
4. **Valuation Entry (examiner).** Examiners see dummy numbers only. They enter question-wise marks at **/campus-portal/valuation**, or on the desk form, and submit.
5. **Third valuation.** When rounds 1 and 2 differ by more than the Exam Rule Set's **Third Valuation Above %** of the ESE maximum (default 15), the script is added to the bundle's round-3 allocation. That allocation is created Unassigned; the COE sets its examiner.
6. **Final ESE mark.**
   - The rule set's **Final ESE Mark** decides. With two valuations it is their average. With three it is either "Average of Closest Two" or "Average of Third and Nearer". Ties go to the higher pair, and the result is rounded half up to a whole mark.
   - The mark is kept on the Dummy Number Map. An examiner's submit never changes a mark sheet.
   - Once every allocation of the course is **Completed** and every live script of the course is finalised (a partial write-back would let the few changed rows be tied to the few valued scripts), Exam Confidential runs `campus.examinations.valuation_write_back.write_back_pending` (POST) with the session and course. This bulk job writes each final mark to the student's Mark Sheet Entry row as ESE and flags it **ESE from Valuation**, so it cannot be edited on the sheet.
   - Some scripts are skipped, with the reason shown in **Write-back Issue** on the map: a student absent on the sheet or in the hall (the absent mark is kept), a result that has already been run, or a sheet that refuses the mark. Run the job again after fixing the cause.
   - Once the student's result has been run, or the session is published, the script's marks are locked.

## Examiner remuneration (P2-T23)
1. **Remuneration Rate (COE or Accounts).** One record per activity, college and Effective From date (these three cannot be changed after the first save): Valuation Round 1 / 2 / 3 (per script valued), QP Setting and QP Scrutiny (per paper), Invigilation (per duty). A new rate is a new record with a later date; work is priced by the version in force on its date. For external examiners set the **Service Item** (with its SAC code): it is the Purchase Invoice line.
2. **Examiner Remuneration Claim (COE).** Choose the Exam Session and the examiner: Internal (Employee) or External (External Member, which needs a Supplier with a TDS category). Save: the work is filled in from the records and cannot be typed:
   - each Completed Valuation Allocation of the examiner (scripts = submitted Valuation Entries);
   - each QP Setter Nomination naming the employee as setter or scrutiniser, once the course's approved paper has been released (priced on the nomination's deadline);
   - each invigilation duty in the session's roster dated before the claim date and before today.
   Each piece of work can be in one live claim only (draft or submitted); cancelling a claim frees it. Work already claimed is left out, and a claim with nothing left is refused.
3. **Approval.** Request Approval: Accounts Manager of the college approves by default. The examiner, the requester and the owner never approve. If the work or a rate changed after approval, the submit is refused: cancel and amend.
4. **Payment.** On approval an internal examiner gets a submitted **Additional Salary** on the component **Campus Exam Remuneration** on the next payroll (the claim date, or the day after their last submitted slip). An external examiner gets a draft **Purchase Invoice** for the Supplier, with TDS by the Supplier's Tax Withholding Category; Accounts submits it only as approved (same Supplier, college and amount per Item; to change it, cancel and amend the claim), and the claim takes its TDS and Net Payable. The invoice of a submitted claim cannot be cancelled on its own: cancel the claim, which cancels the Additional Salary (refused once a submitted slip paid it) or the invoice (a draft is deleted).
5. **Remuneration Register** (report): the claims of a college with amount, TDS, net payable and the payment document.

# Examinations: confidential question papers (P2-T17)

Only users with the **Exam Confidential** role see Question Bank Items, QP Setter Nominations, Question Papers and the QP Access Log. System Manager does not get access through its own role.

## Set up
- **Question Paper Settings** (System Manager):
  - the download lead, at most 120 minutes before the slot;
  - the slot length;
  - the FN and AN start times.
- **The key.** The question paper key encrypts every paper PDF. Keep it in the `CAMPUS_QP_KEY` environment variable, or in a file outside `sites/` named by `campus_qp_key_file` in site_config. Either way, backups do not carry it. A key left in site_config (`campus_qp_key`) works, but migrate warns about it. If the key is missing while sealed papers exist, migrate never generates a new one.
- **The moderation policy.** "Question Paper Moderation" is seeded with Exam Confidential of the college as the approver.

## Prepare (Exam Confidential)
1. **QP Setter Nomination**: setters, scrutiniser and the date the paper is due.
2. **Question Bank Items**: course, CO, Bloom level, marks, difficulty.
3. **Question Paper**:
   - the pattern: at least one CO row and one Bloom row, each with min-max % of the marks;
   - the questions for sets A and B, and the PDF of each set. A PDF is encrypted when the paper is saved.
   - Release At is always the slot start from the session's schedule.
4. **Request Approval** before the download window opens. The paper is refused if it is off its blueprint or its window has begun. A moderator approves it. A moderator is never the requester, the owner, a nominated setter, anyone who changed the questions, pattern or files, or anyone who wrote one of its bank questions.
5. **Approval seals the paper.**
   - It fixes the download window: from the lead before the slot start until the slot ends.
   - It fixes each sealed file's name and SHA-256.
   - Only one approved paper is allowed per session and course.

## On exam day
- Inside the window, Exam Confidential downloads each set from the form (**Download > Set A/B**). The PDF is watermarked with the user and the time, and is never cached.
- Record the copies printed for each Exam Hall with **Record Print**. The **Question Paper Print Log** report shows the copies per hall.
- Before the window, nobody can open a sealed paper, list it or download it. That includes System Manager.
- While any sealed paper of a course is closed, **all** of that course's bank items are hidden and locked.

## Withdraw
- The COE or a System Manager of the paper's college can withdraw a paper at any time, and must give a reason.
- A withdrawn sealed paper stays closed for good. It is never downloadable, and it can never be amended, copied or deleted.
- Withdraw from the **Exam Session** form (**Question Paper > Withdraw Question Paper**): pick the course and give the reason. You never open the paper.
- Withdrawing a sealed paper retires its bank questions: they are disabled for good and no other paper can use them.
- If an exam is postponed, withdraw its sealed paper and seal a new one. The download window fixed at approval does not follow schedule changes.

## Audit
Every open, list, download, print and withdrawal is logged in the **QP Access Log**, allowed or denied, with the user, time and IP. The log rows cannot be changed or deleted.

## Known residual (ruling O-1)
A System Manager can still reach confidential data through configuration paths:
- backups;
- Jinja in Print Format;
- Customize Form;
- Server Scripts;
- granting itself the role.

Treat System Manager as equivalent to Administrator. Give that role only to people who may see exam papers.

Notifications, Webhooks and Version history on these DocTypes are refused. Bank question text is not encrypted at rest (deferred).

# Examinations: result processing, Passing Board and publication (P2-T19)

## Moderation (COE, approved by the Principal)
1. **Mark Moderation**: the Exam Session, the course, the ESE adjustment in marks (negative lowers it) and the justification. **Request Approval**; the seeded policy sends it to the Principal of the college (the requester never approves). Only the final approval submits it.
2. One live moderation per session and course. None is proposed, submitted or cancelled once the session is Published.
3. The next Result Run adds the adjustment to the ESE of every student who sat the course (kept within 0 and the ESE maximum) and shows it in the course row's **Moderation** column.

## Result Run (COE)
1. On the Exam Session, **Run Results** for each programme. The bulk job (Result Runs) grades every enrolled student, less those on a break of study:
   - current courses of the term, and the **Arrear** courses of the student's Exam Registration of the session. An arrear writer gets a row on the course's Mark Sheet Entry in the session; the Result Run keeps the CIA of the first attempt when the Exam Rule Set has **Carry Forward CIA** (R2022), otherwise the CIA on the new sheet (or the last one);
   - SA, WD/WC and AB codes as before; the attempt number (earlier fails, and absences when the rule counts them) decides the R2022 ESE-alone pass from the 3rd attempt;
   - **grace marks** when the student's Exam Rule Set has **Grace Marks Allowed**: the fewest whole ESE marks that pass a failed course, up to the maximum per course, the number of courses and the total per student. The seeded rule sets have grace off (the research note gives no values). Every grace is listed in **Grace Mark Audit** (report) with the Exam Rule Set that allowed it and its limits;
   - grades by the Grading Scheme method of the course type: R2022 theory is **Relative Box-Cox** when more than 30 students of the session passed the course (same bands for every programme), otherwise, and for labs and projects, the absolute table. The row shows the **Grading Method**;
   - SGPA over this session's current courses, CGPA over every pass, both leaving out the scheme's excluded categories (MC); **Result** Pass / Reappear and the **Arrears** count; a final-year session gives a student without arrears a **Classification** (lateral entry and break of study included).
   - once a student has a Student Result in the session, only the COE changes the student's marks (and must run the results again); a teacher's change, or deleting the sheet, is refused;
   - an Arrear with no row on a mark sheet of the session is **Pending**: still owed, outside the SGPA, counted in Arrears; the other courses are graded as usual. Grace considers the R2022 ESE-alone pass from the 3rd attempt (the smaller need counts).
2. Before publication a re-run replaces the results. After publication a re-run that changes a result (or a student's first result) creates one **pending version** (SR-...-V2, **Pending Ratification**) with **Changes from the Previous Version**, graded on the relative bands frozen at publication (so no other student's grade moves). The published version stays the one students, guardians and staff see. A withdrawal approved after publication takes the same path. A re-run back to the published marks drops the pending version.
3. **Result Ratification** (COE): pick the session; the pending versions are listed with their changes. **Request Approval**; the Principal approves (the requester never does). Approval publishes the listed versions (unless they changed since), the replaced versions stay readable to the COE, and each student and guardian gets the `exam.result_revised` notice.
4. Speed: see the T19 report (480 students measured on the test bench).

## Photocopy, revaluation and review (P2-T20)
1. Set up (COE): on the regulation's **Exam Rule Set**, **Application Window (days)** (from the release of the results; seeded 15, pending confirmation) and **Revaluation after Photocopy and Justification** (on for R2022, cl. 16.4). The course types allowed are the **Revaluation Allowed** ticks of its type rows (theory and theory with lab; never labs or projects). On the **Exam Fee Rate**, the **Photocopy**, **Revaluation** and **Review Fee** per course.
2. **Revaluation Application** (desk; the portal page is P2-T25): the student, the Exam Session, the type and the courses. It is accepted from Release At until the window's last day, checked again on submit. Each course must be on the student's published result, sat (Pass or Fail), and of an allowed course type; one live application per type and course. Submit raises the fee as a Sales Invoice (Exam head). Cancelling cancels an unpaid invoice; once paid, a photocopy is issued or an outcome exists, it cannot be cancelled.
3. **Photocopy**: once the invoice is paid, the COE clicks **Issue Photocopy**.
4. **Revaluation** under R2022: each course needs its photocopy issued first. A teacher of the course this term records the justification with **Justify** (`campus.examinations.revaluation.justify`; only that teacher can, and the justification cannot be edited on the form). Teachers have no desk access to applications yet: their page in the faculty portal is deferred. Submit is refused until every course is justified. Other regulations go straight to revaluation.
5. **Review**: only for a course that already has a revaluation outcome for the student in the session.
6. **Revaluation Outcome** (COE, once the fee is paid): the application, the course, the revaluer (Employee or External Member with a user) and the **ESE on Revaluation** (out of the course's ESE maximum, before moderation and grace). The revaluer cannot be an examiner who valued the script, the revaluer of an earlier outcome of it, or (unless the Exam Rule Set allows course teachers) a teacher of the course. Submit records the ESE and grade before and after and recomputes the result: a change makes the pending Student Result version (above), which a **Result Ratification** publishes. The published version is never edited. The student gets the `exam.revaluation_completed` notice (no marks). An outcome cannot be cancelled; a later review outcome supersedes the revaluation's ESE.
7. When the ratified version replaces one with an issued Grade Sheet, the old sheet is revoked and a new one issued for the ratified version (new grades, SGPA, CGPA; QR). The version history is on the Student Result (**Previous Version**, changes).
8. Reports: **Revaluation Change Stats** (per session and course: outcomes, ESE raised / lowered / unchanged, grade changed, average change) and **Evaluation Grievances vs Appeared** (AQAR 2.5.2; per published session of the year: students who sat a course, students with a revaluation or review, %). The data point `evaluation_grievances` counts the same students over the year.

## Passing Board and publication (COE)
1. Run the results of every programme to **Completed**, then hold a **Body Meeting** of the college's **Passing Board** (quorum met, status **Held**, on or after the day the last Result Run finished) and record a resolution approving the results with its **Exam Session** set.
2. On the Exam Session, **Publish Results** (a COE user other than the one who recorded the meeting): the meeting, the resolution number and **Release At** (e.g. 10:00 the next day). The resolution must be Approved, name this session, and be unused by another session; no Result Run of the session may be running, and the latest run of every programme must have finished clean (Completed, no errors). The meeting (date and start time) must sit after that run finished. Neither the meeting's owner nor the resolution's **Recorded By** (stamped by the server when it is numbered; the resolution's text, decision and Exam Session are fixed from then on) may publish. If a Mark Sheet Entry or Mark Moderation of the session changed after the earliest start of the programmes' latest runs, a programme's Student Result after its own run finished (a result without a programme after the last run finished), or anything after the meeting, publication is refused: run the results again and take a new resolution. Publication freezes the relative bands the run graded on (recorded by the run, never recomputed later); they cannot be changed afterwards. The session becomes Published with Publish At = Release At; setting the status to Published by hand is refused.
3. Until Release At, Student Results are read only by the COE, System Manager and Dean Academics: Academics Users, teachers, students and guardians see nothing, on the desk, the API and `/campus-portal/results`. After it, staff read the session's results; students and guardians the latest version of their own.
4. Within 15 minutes of Release At the scheduler queues the release notice (template `exam.result_published`: SMS, WhatsApp, email by consent) to every student and guardian, once per session.

## Grade sheets, certificates and transcripts (COE, P2-T22)
Every print below reads **published** results only (the latest ratified version, session Published, Release At passed) and carries a QR verifiable at `/verify/<code>`. An issued certificate prints from the record frozen when it was issued, so a later revaluation, rule change or setting switch never changes what its QR attests; issue a new one to show new values.
1. **Semester grade sheet**: on a Student Result, **Issue Grade Sheet** (refused before release), then print **Grade Sheet**.
2. The other prints are **Certificate Types** issued through a **Certificate Request** (desk or `/campus-portal/certificates`; numbered, verifiable, fee if the type has one):
   - **Transcript**: every published semester with its SGPA, then the CGPA. This is the Transcript Request; a student asks for it in the portal.
   - **Consolidated Grade Sheet**: core courses, then the Additional / Honours / Minor courses (from the student's Course Registrations) marked counted or not counted in the CGPA, the CGPA, % = CGPA × 10 and the class.
   - **Provisional Certificate**: the issuer is the college or the affiliating university, per the Institution Profile's Provisional Certificate Issuer.
   - **Degree Certificate** only where the Institution Profile's Degree Awarding Body is College; otherwise the **Degree Data Sheet** for the university. Switching the setting withdraws the other print at once.
   The graduate prints (all but the transcript) are refused until the programme is completed: a published final-year result, no core arrear and, when the regulation's Curriculum Rule sets Minimum Total Credits, that many core credits passed. They need approval through the college's **Approval Policy** for Certificate Request: the condition `doc.needs_approval` routes every type that needs approval through one policy; for COE-only approval of the examination documents, add a policy with a condition on `doc.certificate_type` (e.g. `doc.certificate_type in ("Consolidated Grade Sheet", "Provisional Certificate", "Degree Certificate", "Degree Data Sheet")`) and a level for the COE position (scope field company), at a higher priority than the general one. Approval issues the document. The transcript needs none. Until it is issued, a request is a draft: only staff who can edit Certificate Requests can preview it, marked **DRAFT - NOT VALID** with no QR; the student or guardian cannot print or download it. A student gets one Provisional and one Degree Certificate (cancel the issued one to issue again). The Degree Data Sheet is prepared on the desk for the university and is not offered in the portal.
3. **Classification** follows the regulation's Classification Rule with the entry type (lateral), years of study and break of study. Additional courses enter the CGPA only when the Grading Scheme counts them and the student passed the Classification Rule's Honours or Minor credits.

## Progression Run (COE, term end)
1. Set a **Progression Rule** per regulation: maximum arrears to proceed (more detains: year back) and the CGPA below which a promoted student is on probation (0: none). It locks with its Effective regulation.
2. Create a **Progression Run** (company, term, programme; one per term and programme) and submit it: a bulk run promotes, detains or promotes on probation each Active student enrolled that year (students on a break of study are skipped). Promoted students move to the next semester; detained ones get the academic status Detained. **Re-run** is idempotent and takes the students this run detained again, so a revaluation that clears their arrears promotes them.

## Convocation List (COE)
1. Create a **Convocation List** (company, optionally programme) and **Get Graduates**: students with the programme completed from published results, not already on another list.
2. **Download** exports CSV in the list's **Export Format** columns. The default columns are a placeholder: the university's format is not known yet, so set the headings and order to match it. Cells that look like spreadsheet formulas are neutralised.
