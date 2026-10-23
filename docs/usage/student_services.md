# Student Services: exam withdrawal, break of study, rejoin (P2-T21)

All three are in **Student Services > Status Changes**. Each one goes through the approval engine. The seeded
policy has two levels: the HOD of the programme's department recommends, then the Principal approves. The
person who requests approval, and the owner of the document, never approve it. Final approval submits the
document.

## Regulation values (Exam Rule Set, "Withdrawal and Break of Study" section)
- **Withdrawal Window**: the number of days after the exam (default 10).
- **Break of Study Maximum**: in years (default 1).
- **Exceptional Extra Break**: in years (default 1).

An Effective regulation's rule set is locked. To change these values, amend the regulation as a new version.

The withdrawal code comes from the regulation's Grading Scheme codes: WD in R2022, WC in R2026, W in R2021.

## Exam Withdrawal Application
- Choose the student, the Exam Session and the courses to withdraw from. Each course must be a course of the
  term (Current or Dropped, not an arrear or bridge course), registered, eligible and scheduled in that session.
- A student may withdraw only once in a programme. A second application is refused.
- The application must be made within the window, counted from the exam date of each course. A late
  application can be saved but cannot be sent for approval.
  - Only the Principal can tick **Special Case**, which lifts the window. The Principal must give a reason.
  - The Special Case does not lift the once-per-programme rule.
- Once approved, the Result Run grades each withdrawn course with the regulation's code. The result is WD,
  which counts as no attempt and no appearance, so a withdrawal does not cost a student a distinction.
- If the session already has a Student Result, approving or cancelling the application recomputes it. A
  published session cannot be changed.

## Break of Study
- Enter the From and To dates and the reason.
- All of a student's approved breaks together may last up to the maximum. A break marked **Exceptional**,
  with a reason, may also use the extra years.
- Breaks never overlap.
- Approval keeps the student's current Academic Status and sets it to **Break of Study**. Exam registration and
  the Result Run skip a student on a break. Cancelling the break restores the earlier status.
- Without an Approval Policy none of the three documents can be submitted.

## Rejoin Application
- Pick the approved Break of Study, the **Academic Year** of rejoining and a rejoin date inside it.
- The student joins the cohort now where they left off: the batch admitted in the rejoin year less the years
  completed when the break started (**To Batch**). For example, a 2022 admission who breaks after two years (in
  2024-25) and rejoins in 2026-27 joins the 2024 batch. **To Regulation** is that batch's regulation.
- The batch and regulation are checked again when the rejoin is submitted.
- List any **Bridge Courses**.
- Approval does three things:
  - It moves the student to the To Regulation. The move is logged in the student's Regulation History, with
    the bridge courses in that entry.
  - It moves the student's batch to To Batch and restores the status from before the break.
  - Bridge courses offered in a term are registered as kind **Bridge** (attendance applies) and graded by the
    Result Run. A bridge course not offered yet stays pending: it is neither registered nor charged.
- A break can have only one rejoin. A rejoin cannot be cancelled. To correct the regulation afterwards, the
  Dean Academics uses Change Regulation.
