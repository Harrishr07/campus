# Student Services: exam withdrawal, break of study, rejoin (P2-T21)

All three are in **Student Services > Transactions**. Each one goes through the approval engine. The seeded
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
- Choose the student, the Exam Session and the courses to withdraw from. Each course must be registered,
  eligible and scheduled in that session.
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
- Approval sets the student's Academic Status to **Break of Study**. Cancelling the break sets it back to
  Active.

## Rejoin Application
- Pick the approved Break of Study, the rejoin date and the **Academic Year** of rejoining.
- **To Regulation** is the regulation in force for the programme in that year.
- List any **Bridge Courses**.
- Approval does three things:
  - It moves the student to the To Regulation. The move is logged in the student's Regulation History, with
    the bridge courses in that entry.
  - It sets the student back to Active.
  - It adds the bridge courses, as kind **Bridge**, to the student's next exam registrations until the student
    has sat them.
- A break can have only one rejoin. A rejoin cannot be cancelled. To correct the regulation afterwards, the
  Dean Academics uses Change Regulation.
