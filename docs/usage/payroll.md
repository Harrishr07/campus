# Payroll for aided and self-financing staff (M07-07)

Payroll is HRMS payroll: Salary Component, Salary Structure, Salary Structure Assignment, Employee Promotion,
Payroll Entry and Salary Slip. Campus adds no payroll DocTypes. It adds a Funding Mode field on Salary Structure,
seeds components and two draft structures, and provides one helper that assigns a structure by the employee's
Funding Mode (Employee > Faculty tab > Funding Mode: Aided or Self-financing).

## What migrate seeds (once; your edits are never overwritten)
- **Salary Components**: Basic (B), Dearness Allowance (DA), House Rent Allowance (HRA), Academic Grade Pay (AGP).
  A component that already exists (HRMS seeds Basic and HRA on Indian sites) is left as it is.
- **Statutory components**: HRMS's Provident Fund and Professional Tax get their Component Type (Provident Fund,
  Professional Tax) if it is blank, so the HRMS reports Provident Fund Deductions and Professional Tax Deductions
  find them.
- **Two draft Salary Structures per college** (each non-group company with an Institution Profile), named
  "Aided Staff - ABBR" and "Self-financing Staff - ABBR", with Funding Mode set. They are drafts: review
  the rates, then submit. A structure is not seeded again while one with the same name or the same company and
  Funding Mode exists.

Default rows (all rates are in the structure record; change them there):

| Row | Aided | Self-financing |
| --- | --- | --- |
| Basic | `base` (pay in the pay band / level) | `base` |
| Academic Grade Pay | `variable` (0 for 7th CPC pay levels; the slip then shows AGP 0) | - |
| Dearness Allowance | `(base + variable) * 0.50` | `base * 0.10` |
| House Rent Allowance | `(base + variable) * 0.10` | `base * 0.10` |
| Provident Fund | `(base + variable) * (1 + 0.50) * 0.12` (12% of Basic + AGP + DA) | `min(base * (1 + 0.10), 15000) * 0.12` (EPF, 12% of Basic + DA up to the 15,000 wage ceiling) |
| Professional Tax | 208 a month | 208 a month |

`base` and `variable` are the Base and Variable of the Salary Structure Assignment. Formulas use them rather than
component abbreviations because HRMS's Basic and HRA already depend on payment days, and HRMS refuses a
payment-days formula that also reads another payment-days component. Each row is prorated once for leave without pay.
If you change a rate in one row (for example DA), change the rows built on it too (Provident Fund repeats the DA rate).

## Steps for a college
1. **Accounts**: on the Company, Default Payroll Payable Account must be an account of type **Payable** (open
   "Payroll Payable - ABBR" and set Account Type). Set the default account of each Salary Component for the
   company (Salary Component > Accounts) before you submit salary slips; Payroll Entry posts the accrual Journal Entry
   from them.
2. **Fiscal Year and Holiday List**: an active Fiscal Year covering the payroll dates, and a submitted
   **Holiday List Assignment** for the company (or each employee).
3. **Review and submit** the two structures. Keep one active structure per company and funding mode. To revise,
   make a new structure with the same Funding Mode and set the old one's Is Active to No.
4. **Funding Mode** on each employee (Employee > Faculty).
5. **Assign** with `campus.faculty.api.assign_salary_structure(employee, from_date, base, variable=0)` (POST; needs
   permission to create Salary Structure Assignments). It picks the submitted, active structure of the employee's
   own company for their Funding Mode, then creates and submits the assignment. Calling it again for the same
   employee and From Date returns the existing assignment unchanged. It refuses an employee without a Funding
   Mode, a mode without a submitted structure, and a mode with two active structures.
6. **Run payroll**: Payroll Entry (company, month, payroll payable account), Get Employees, Submit (creates the
   draft slips), check, then Submit Salary Slips.

## Increments and promotions
An annual increment or a promotion (cadre or designation change) is an HRMS **Employee Promotion**: Promotion Date,
the changed properties, and Revised CTC. On submit HRMS updates the Employee and its CTC. The new pay then takes effect
through a new assignment from the promotion date:
`assign_salary_structure(employee, promotion_date, base=<new pay>, variable=<AGP>)`. Slips from that date use the new
assignment; earlier months keep the old one. The increment rate (for example 3% of Basic, rounded) is the college's
rule under its pay commission; Campus does not compute it, so no increment helper is added.

## PF, ESI and PT: what exists and what does not
india_compliance has no payroll features; HRMS provides the components and two reports.
- **Provident Fund**: wired as a deduction row in both structures; HRMS Provident Fund Deductions report works once
  the Component Type is set (done by migrate). Not provided: the employer's share (EPF 3.67% / EPS 8.33%) and the
  EPFO ECR file. Add an Employer Contribution component and row if you need the employer share on the slip. Aided
  colleges whose teachers subscribe to GPF can rename or replace the row.
- **Professional Tax**: wired as a fixed 208 a month (Tamil Nadu's top half-yearly slab, 1,250, spread monthly).
  Not provided: state slab tables or half-yearly deduction. Use a Condition on the row (for example
  `base > 12500`), or several PT rows with conditions, for your state's slabs. HRMS's Professional Tax component
  depends on payment days, so PT is prorated in a month with leave without pay; clear "Depends on Payment Days" on
  the component if your state deducts it in full.
- **ESI**: not provided by HRMS or india_compliance (no component, no report). For staff earning up to 21,000 a month,
  add an "Employee State Insurance" deduction (0.75%, Condition on gross) and an employer contribution (3.25%) to
  the structure.
- **Income tax (TDS)**: not part of these templates; use HRMS Income Tax Slab, Payroll Period and an income tax
  component as usual.

## Demo and tests
`campus/tests/test_faculty_payroll.py` builds September 2026 payroll for Demo College of Engineering: faculty_1
(Aided, base 40,000, AGP 9,000) gets gross 78,400, deductions 9,028, net 69,372; faculty_2 (Self-financing, base
30,000) gets gross 36,000, deductions 2,008, net 33,992. After an Employee Promotion with a new assignment from
2026-08-01 at base 41,200, faculty_1's September slip is gross 80,320, net 71,076.
