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
