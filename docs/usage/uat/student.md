# UAT: Student (portal)
Login `student@sxcce.example.edu` at `/campus-portal`. Guide: roles/student.md.

| # | Step | Expected |
|---|---|---|
| 1 | Dashboard | Fees outstanding, attendance, latest SGPA and CGPA |
| 2 | Fees | Invoices with totals; **Pay online** or the pay-at-office note |
| 3 | Attendance | Per-course percentage; leave days counted |
| 4 | Results | Published Odd and Even results |
| 5 | Exams | Registration and hall ticket, if open |
| 6 | Certificates: choose a type, **Request** | Request listed; **Download** after issue |
| 7 | Leave: apply with a note | Application listed |
| N1 | Open `/app` | Redirected or refused (no desk) |
| N2 | Change `?student=` in the URL to another register number | Refused or own data only |
| N3 | Open `/app/student/<other student>` | Refused |
| N4 | Open `/campus-portal/faculty` | Refused (no Employee record) |
