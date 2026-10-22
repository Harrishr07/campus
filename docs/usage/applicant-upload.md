# Applicant upload and duplicate candidates (M04-06, M04-07)

For admission staff (Admission Officer). Desk: **Admissions > Applicant Upload**, **Candidate Duplicate Review**.

## Upload candidates
1. **Applicant Upload > New**: choose the college (Company) and Academic Year, then **Download Template**.
2. Fill one row per candidate. Required: First Name, Date of Birth (YYYY-MM-DD), Program, Qualifying Exam,
   Qualifying Register No. Optional: Middle/Last Name, Gender, Email, Mobile, Student Category, Admission Quota,
   Admission Type.
3. Attach the file (CSV or XLSX) and **Validate**. Nothing is created yet. **View Rows** lists every row:
   - **Valid**: will be created.
   - **Invalid**: the message says why (missing value, bad date, unknown program, program of another college,
     e-mail already used, row repeated in the file). Fix the file and validate again.
   - **Possible Duplicate**: the candidate may already exist (see below).
   - **Already Imported**: the same candidate (exam, register no, date of birth, program, year) is already an applicant.
4. **Import**. Valid rows become applicants; possible duplicates go to review (**Held for Review**). The upload
   shows **Awaiting Review** until every review is decided, then **Completed** (or **Completed with errors**).
   The uploaded file and the rows' raw values are deleted then; the file's SHA-256 stays on the upload.

Uploading the same file again is safe: rows already imported show **Already Imported** and nothing is created twice.
If a row ends as **Error** with "the import was interrupted", upload the file again; only that row is imported.

## Duplicate candidates
A candidate is a possible duplicate of an applicant or student of the same college when the name (any word order,
ignoring case and punctuation) and date of birth match, or the qualifying-exam register number matches for the
same exam. The same phone number or e-mail alone is never a duplicate (siblings share them).

Open **Candidate Duplicate Review** and decide:
- **Link to Existing Record**: the candidate is the existing applicant or student; nothing new is created.
- **Not a Duplicate** (reason required): a different person; the applicant is created.

Who decided, when and why is kept on the review (with its version history).

Entering a duplicate by hand (desk form or API) is refused with the matching records named. For a genuine
different person with the same name and date of birth, upload a one-row file and mark the review **Not a Duplicate**.

## Not yet
- A desk "Open duplicate review" action on the applicant form; needed before self-service or API intake.
- The refusal message names the matching records; it is meant for staff and must not be shown to public callers.
