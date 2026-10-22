# UAT: Faculty (Instructor)
Login `faculty@sxcce.example.edu`. Guide: roles/faculty.md.

| # | Step | Expected |
|---|---|---|
| 1 | Open `/campus-portal/faculty` | My timetable, only your periods |
| 2 | Attendance > open a period, tick one absentee, **Save attendance** | Saved; the absentee shows Absent, others Present |
| 3 | Reopen the same period and change a student within 48 hours | Allowed |
| 4 | CIA marks > a semester 3 course, enter marks, **Save CIA marks** | Saved; totals update |
| 5 | Leave > apply for one day | Application appears for approval |
| N1 | Open a period marked more than 48 hours ago, try to change a status | Refused; message says to raise an Attendance Correction Request |
| N2 | Raise the Attendance Correction Request (Faculty > Transactions) | Created; cannot approve it yourself |
| N3 | Open another teacher's course in CIA marks | Not listed; direct URL refused |
| N4 | Open a student who is not your mentee under My students | "This student is not your mentee." |
| N5 | Edit CIA marks after the deadline | Read-only; needs an approved CIA Unlock Request |
