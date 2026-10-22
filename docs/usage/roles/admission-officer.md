# Admission Officer

**Login (demo):** `admissions@sxcce.example.edu`

**What you do:** take enquiries, turn them into applicants, check documents and seats, admit, and confirm joining when the student reports.

**You see (desk):** Admissions, Approvals.

## Daily tasks
1. **Review new enquiries:** Admissions > Transactions > Lead. Filter by status; open one and follow up. The public form `/admission-enquiry` creates Leads for your college.
2. **Convert an enquiry:** the applicant is created by `convert_lead_to_applicant` (see docs/usage/enquiry-crm.md). Otherwise load a batch: Admissions > Transactions > Applicant Upload, then check rows first with Admissions > Reports > Import Check.
3. **Check an applicant:** Admissions > Transactions > Student Applicant. Pending papers: Admissions > Reports > Pending Documents. Duplicates: Candidate Duplicate Review.
4. **Admit:** open an Approved Student Applicant, click **Admit**, confirm.
5. **Confirm joining:** the admitted applicant becomes a Student. Open the Student (Student Services > Masters > Student) and click **Confirm Joining**, set the Joining Date. Register number and fee invoice follow.
6. **Watch seats:** Admissions > Reports > Live Seat Matrix, Admission No-Shows, Admissions by Quota and Category.
7. **Late joining or cancellation:** Admissions > Transactions > Late Joining Request, Admission Cancellation. Refund rules: Refund Register report.

You cannot see fees, marks or exams.
