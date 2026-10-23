# UAT: Admission Officer
Login `admissions@sxcce.example.edu`. Guide: roles/admission-officer.md.

| # | Step | Expected |
|---|---|---|
| 1 | Open Admissions > Enquiries > Lead | Demo enquiries list; no error |
| 2 | Open `/admission-enquiry` logged out, submit a test enquiry (programme set) | Thank-you page; new Lead appears, assigned to an Admission Officer |
| 2a | Open that Lead, click **Convert to Applicant** | Student Applicant opens with name, mobile, email and programme copied; the Lead shows status Converted and an **Open Applicant** button instead |
| 3 | Admissions > Reports > Import Check, upload a valid Applicant Upload file | Rows show outcomes, none written yet |
| 4 | Open a Student Applicant with status Approved, click **Admit** | Confirmation; status becomes Admitted |
| 5 | Open an Admitted applicant's Student, click **Confirm Joining** | Register number and fee invoice created |
| 6 | Admissions > Reports > Live Seat Matrix | Joined count rose by one for that programme |
| N1 | Open `/app/sales-invoice` or Fees and Finance | No Fees and Finance entry in the dock; access refused |
| N2 | Open Examinations workspace | Not in the dock; URL gives "not permitted" |
| N3 | Confirm Joining twice on the same student | Second attempt refused or no duplicate invoice |
