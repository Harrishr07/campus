# UAT: HOD
Login `hod@sxcce.example.edu` (CSE), then `hod-ece@sxcce.example.edu`. Guide: roles/hod.md.

| # | Step | Expected |
|---|---|---|
| 1 | Approvals > Reports > My Pending Approvals | Requests for your department |
| 2 | Approve an Attendance Correction Request raised by CSE faculty | Request approved; the attendance record is replaced |
| 3 | Faculty > Reports > Workload Balance | CSE faculty only |
| 4 | Examinations > Reports > CIA Status by Offering | CSE offerings only |
| N1 | As `hod-ece@`, open Student list and Attendance Correction Request | No CSE students or requests |
| N2 | As `hod-ece@`, try to approve a CSE request by URL | Refused |
| N3 | As `hod@`, open Fees and Finance | Not visible |
| N4 | As `hod@`, Student list | No **Add** button (students are created by the office) |
