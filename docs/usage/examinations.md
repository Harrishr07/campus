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
4. **Request Approval.** The paper is refused if it is off its blueprint. A moderator approves it. A moderator is never the requester, the owner, a nominated setter, or anyone who changed the questions, pattern or files.
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
