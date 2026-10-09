# Research (M08)

## Calls and proposals (P3-T13, M08-02)

1. **Research Call** (Research > Transactions): the agency, one of its Funding Schemes, the deadline and
   "Remind PIs (Days Before Deadline)" (default 7).
2. **Research Proposal**: pick the college, the call (agency, scheme and deadline come from it), the PI, the
   co-investigators (employees of the college) and the budget by head. Only the scheme's heads are allowed, each
   once. The scheme must be usable by the college: every head needs an account mapping for that college
   (Grant Budget Head) and the college needs Research Settings.
3. **Internal review**: click Request Approval. The default policy "Research Proposal Internal Review" sends it to
   the college's Principal. You can edit the policy or add levels in Approval Policy. The PI and co-PIs never
   review their own proposal. Review can't be skipped: without a policy the proposal does not submit.
4. When the review approves it, the proposal is submitted (status Approved). Click **Submit to Agency** to record
   the date and the agency reference. You can't do this before internal approval.
5. Click **Record Outcome** (Sanctioned / Not Sanctioned) when the agency decides. The Sanction itself is P3-T14.

Deadline reminders: every day, the PI of each proposal not yet submitted to the agency gets the
`research_proposal.deadline` message, from the call's reminder window up to the deadline day. Reminders stop once
the internal review rejects the proposal. Edit the wording in Message Template. Submit to Agency and Record Outcome
leave a comment on the proposal; the agency fields can't be edited on the submitted form.

Report: **Research Proposal Pipeline** lists a college's proposals by stage: Draft, Under Internal Review,
Returned for Changes, Rejected Internally, Approved, Submitted to Agency, Sanctioned, Not Sanctioned, Cancelled.

Module pack: turning the RESEARCH pack off for a college hides the Research desk area from that college's users.

## Sanctions and grant receipts (P3-T14, M08-03, M08-05)

Set-up first: in **Research Settings**, set the **Research Cost Centre** (a group cost centre of the college). In
the **Funding Scheme**, choose the **Budget Action** (Stop or Warn). Each revenue head of the scheme must map to
exactly one expense account of the college, and two heads can't share an account. Seed money uses the seeded
Funding Agency **Institution** with a scheme of its own. It works like any other grant.

1. **Sanction** (Research > Transactions): enter the order no and date, the agency and scheme, the PI and co-PIs,
   the start and end dates, the amount per head per fiscal year, the instalments (they must add up to the
   sanctioned total) and the conditions. You can link the Research Proposal if the agency sanctioned it. A proposal
   can have only one sanction.
2. **Submit** creates an ERPNext Project, a Cost Center under the research cost centre and the liability account
   "Grant Received in Advance - <sanction>" under the grant liability parent. It also creates one Budget per
   revenue head account. Each Budget covers the sanction's fiscal years, is split by year as sanctioned, and stops
   or warns per the scheme on both the total and the amount sanctioned to date. Capital heads get no ERPNext
   Budget, because ERPNext budgets only income and expense accounts.
3. **Receive Instalment** opens a **Grant Receipt**. Pick the instalment, the amount, the bank or cash account and
   the UTR / cheque reference. Submitting it posts a Journal Entry that debits the bank and credits the sanction's
   liability, with its project and cost centre. A receipt is never income. An instalment can't be received beyond
   its amount.
4. **Extend** records a revised end date with the agency's extension order. The project's end date follows.
5. **Cancel** works only before anything has been posted against the project, cost centre or liability account.
   It removes the Project, Cost Center, Budgets and liability account.

## Spending, budget control and re-appropriation (P3-T15, M08-04, M08-05)

Every Purchase Order, Purchase Invoice, Journal Entry and Expense Claim line on a sanction's project or cost centre
carries a **Grant Budget Head** (`oc_budget_head`):

- The head must be one of the sanction's heads. The line's account must be one of that head's accounts for the
  college: an Equipment line posting to a consumables account is refused. When the item's group is mapped under a
  head of the scheme, that head is filled in, and another head is refused.
- The line must use both the sanction's project and its cost centre. A line on the cost centre gets the project
  filled in. The date must be inside the sanction period. A head can't go on a line that isn't a sanction's.
- Journal Entry rows need a head only when they post spending (an expense or fixed asset account). Grant Receipt
  bank and liability rows need none. Capital purchases go through a Purchase Invoice, not an Expense Claim.

Limits follow the scheme's **Budget Action** (Stop or Warn):

- **Revenue heads**: the sanction's ERPNext Budgets apply. A revenue line dated in a period that no Budget covers
  is refused.
- **Capital heads**: these have no ERPNext Budget, so Campus checks them when a Purchase Order, Purchase Invoice or
  Journal Entry is submitted, under a lock on the sanction. A head's spending up to the end of each fiscal year
  can't pass what was sanctioned for it up to that year, or its total. Spending is the submitted invoice lines,
  the journal rows and the unbilled part of open orders. An order and its invoice count once. Amounts are net of
  taxes: non-recoverable GST that ERPNext capitalises into the asset is not counted against the head.
- The capital check also runs when a submitted order's items are updated (Update Items), and when you cancel a
  credit to a capital head (a debit note, or a journal crediting it), because that cancel gives the spending back.
  On an updated order, only each line's unbilled part counts; the billed part is counted from its invoice.
- Update Items can't add rows to an order of a sanctioned project, because the dialog can't set their head,
  project or account. Raise a new Purchase Order instead.

**Extend** on a sanction also carries the Budgets into the revised end date's fiscal year. Nothing new is
sanctioned for that year, so only the unspent balance can be spent there.

**Re-appropriation Request** (Research > Transactions): pick the sanction, the fiscal year, the from and to heads
(the to head can be any head of the scheme) and the amount. Enter the agency's letter number and date, and attach
the letter. Submitting it:

- moves the amount between the sanction's head rows (the total sanctioned stays the same)
- revises the affected ERPNext Budgets (cancelled and replaced; the new one's Revision Of names the old)
- adds a comment on the sanction

A head can't give away money already spent or committed against it. A revenue head left with nothing loses its
Budget, and its lines are then refused. Cancelling the request moves the amount back.

## Grant income, capital grants and interest (P3-T16, M08-05, blueprint D9)

Set-up: **Research Settings** names the **Grant Income Account**, the **Deferred Capital Grant Account** and the
**Interest Treatment** (Grant Liability by default). A Funding Agency can override the treatment.

**Grant Interest** (Research > Transactions): enter the interest the bank credited on a sanction's grant funds, and
the bank or cash account it was credited in. Submitting it posts a Journal Entry that debits the bank. With the
Grant Liability treatment, it credits the sanction's "Grant Received in Advance" liability. With Interest Income,
it credits the college's Interest Income Account instead.

**Grant Income Recognition** (Research > Transactions) is the period-end entry. Enter the college and the period.
List the sanctions, or leave the table empty to take every submitted sanction of the college that has started by
the period end. Submitting it posts one Journal Entry on the period end, with each sanction's project and cost
centre on its rows. For each sanction, it:

- moves the **revenue spending** (the sanction's revenue head accounts on its cost centre) from the liability to
  grant income
- moves **asset purchases** (its capital head accounts) from the liability to the Deferred Capital Grant
- releases the **Deferred Capital Grant** to grant income in line with the **depreciation** booked on the sanction's
  cost centre. Give assets bought from a sanction the sanction's cost centre. The release never passes what was
  capitalised, and each asset is taken as wholly funded by the sanction.

Amounts are cumulative to the period end, less what earlier recognitions already did. So a credit note reverses
income, and spending back-dated into a recognised period is picked up by the next period. After recognition, a
sanction's liability balance = receipts + interest (Grant Liability treatment) − revenue recognised − capitalised.

Each sanction is recognised once per period end. A sanction already recognised up to that date, or with nothing
new, is dropped from the run. If none is left, the run is refused, so running a period twice posts nothing.
Cancelling reverses the Journal Entry and frees the period. Only a sanction's latest recognition can be cancelled.

## Utilisation Certificate and Statement of Expenditure (P3-T17, M08-06, blueprint D9)

**Utilisation Certificate** (Research > Transactions): pick the sanction and the period (inside the sanction
period). Saving the draft reads the figures from the general ledger:

- **Opening unspent balance**: what came into the sanction's liability before the period, less what was spent
  before it.
- **Grants received**: Grant Receipts in the period. **Interest earned**: Grant Interest credited to the liability
  (Grant Liability treatment). Interest treated as income is the college's, so it is not on the UC. Under GFR, interest
  on central government grants belongs to the government and must be shown on the UC, so keep the Grant Liability
  treatment for those agencies.
- **Refunds and other adjustments**: anything else posted to the liability, such as an unspent balance refunded to
  the agency (shown as negative). Grant Income Recognition entries are left out, because they only move money
  already spent.
- **Expenditure by head**: for each budget head, debit less credit on the head's accounts on the sanction's cost
  centre. Capital heads count at cost; depreciation is not expenditure.
- **Closing unspent balance** = total available − expenditure in the period. This equals everything received less
  everything spent up to the period end.

The **Expenditure by Head** table is also the **Statement of Expenditure**: sanctioned, spent before the period,
spent in it, spent to date and balance, per head. Two heads of a sanction can't share an account, because the
ledger couldn't be split between them.

**Unreconciled entries**: spending on the sanction's project or cost centre that its heads don't account for, up to
the period end. Examples: an expense ledger outside every head, or the project under another cost centre. These
come from vouchers Campus doesn't tag, such as a Stock Entry. The form shows how many there are and their amount.
The certificate can't be approved until they are posted to a head or moved off the project.

**Approval** runs through the approval engine under the seeded policy "Utilisation Certificate Approval": the PI
first (the PI's user, from the Employee record), then Accounts (an Accounts Manager of the college), then the
Principal. Let Accounts prepare the certificate, because the person who prepares it can't approve it. One person
certifies at one level only: someone who approved an earlier level (say the PI, who also holds Accounts Manager)
can't approve a later one, and the certificate is refused if the same user appears at two levels. A UC can't be
submitted without approval. The PI can read their own certificates and no one else's.

On the final approval, Campus locks the sanction and re-reads the ledger. The approval is refused if:

- there are unreconciled entries (the read on the sanction's cost centre is a locking one; the read for the project
  under other cost centres is not, because GL Entry has no index on project)
- the figures have changed since the certificate was sent for approval (return it and save it again)
- another approved UC of the sanction covers part of the period

When approval succeeds, Campus:

- records who certified at each level
- stores a snapshot of the figures
- issues the printed certificate as a Verifiable Document, with a QR code and a /verify code

**Prints**: "Utilisation Certificate" is a placeholder layout in the style of GFR 12-A, used until the agency's
format is supplied. "Statement of Expenditure" gives the head-wise statement. The **UC Format** of the Funding
Scheme, else of the Funding Agency, names the print format the certificate is issued in. It can be any print format
of Utilisation Certificate, so an agency's own layout is a new print format, not a code change.

**Source changed**: any ledger entry on the sanction's liability, cost centre or project dated on or before an
approved UC's period end (a back-dated voucher, or a cancellation) recomputes the UC. If the figures move, the UC is
marked **Source Changed** and the approved figures stay as they were. **Recheck Source** recomputes it and clears
the mark when the figures match again. To revise a certificate, cancel it (its Verifiable Document is revoked) and
amend it. The amendment is the next **version** and needs approval again.

**Reports**:

- **Utilisation Certificate Status**: one row per fiscal year of each sanction, cut to the sanction's dates. It shows
  the due date (period end + **UC Due Days** in Research Settings, a placeholder until the agency's terms are known)
  and a status: Submitted, Source Changed, Not Yet Due, Due or Overdue.
- **Grant Ledger by Head**: the entries behind each head for a period, with the opening, a running balance and the
  period total that the UC shows.

## PFMS EAT export (P3-T18, M08-07)

**PFMS Export Batch** (Research > Transactions): pick the sanction, the export type and the period. Saving the draft
lists the sanction's payments of that type in the period:

- **Expenditure**: Payment Entries to a supplier against the sanction's Purchase Invoices (the allocated amount, so a
  part payment exports what was paid), and Purchase Invoices paid on the invoice itself.
- **Advance**: Payment Entries to a supplier against the sanction's Purchase Orders, or left unallocated with the
  sanction's project or cost centre.
- **Transfer**: any of these to a supplier marked **Registered PFMS Agency** (a fund transfer to another agency).

An invoice or order is the sanction's when its lines are on the sanction's cost centre. One only partly on it is
excluded, because the sanction's share of the payment can't be told.

**Vendor check**: a payment is excluded, with the reason, when its supplier has no **PFMS Vendor Code** (on the
Supplier) or no bank account with an account number and IFSC (the payment's party bank account, else the supplier's
default). The **Excluded Payments** table lists them. Fix the supplier and the next batch picks the payment up.

**Re-export**: submitting the batch locks the sanction, selects the payments again and gives each row a reference and
an export key, unique in the database. A payment in a submitted batch is not exported again unless PFMS reports it
failed, so re-exporting a period gives only the new and the failed payments. **Already Exported** shows how many were
left out for that reason. A batch with a row PFMS accepted can't be cancelled; cancelling any other frees its rows.

**The file**: the batch attaches the EAT bulk-upload CSV, laid out by its **PFMS Export Layout** (Research > Settings).
A layout is a list of columns, each a header and a source (a payment or batch field, or a fixed value), plus the date
format and the header row. The seeded "PFMS EAT ... (placeholder)" layouts are placeholders until the official EAT
file spec is supplied: change the columns to the official ones, with no code change. Every layout needs a **Row
Reference** column. Text cells that would start a spreadsheet formula (=, +, -, @) get a leading apostrophe.

**Import Status**: upload the status file PFMS returns. The layout names its columns (row reference, status, PFMS
reference, message) and which status values mean success or failure. Accepted rows are final. Failed rows go into
the next batch of the period. A row already accepted or failed, an unknown reference or an unknown status is skipped
and listed. The batch is **Processed** when no row is waiting for a status.

**Adapters**: the batch's **Adapter** is "File" (the file above); nothing calls PFMS. Another app can add one, such
as an API adapter once the agency grants access, with the hook `pfms_adapters = {"Name": "path.to.AdapterClass"}`.
The class implements `export_expenditure`, `export_advance`, `export_transfer` and `import_status`
(campus.research.pfms_adapter.PFMSAdapter).

## Deferred

- Re-opening a Closed Purchase Order with capital head lines does not re-run the capital check. Closing frees the
  unbilled part, so re-opening gives it back without a check. Until this is covered, re-open such an order only if
  the head still has room, or raise a new order. (P3-T15)
- Disposing of a grant-funded asset credits its Fixed Asset ledger on the sanction's cost centre. Grant Income
  Recognition then reads it like a purchase return, and so does the UC's capital head expenditure. Until disposals are
  handled, book the disposal's grant share by a manual journal. (P3-T16)
- Recognition Journal Entry rows don't carry reference_type / reference_name to the Grant Income Recognition.
  ERPNext's Reference Type is a fixed list, and extending it would change Journal Entry for every app. The run's
  `journal_entry` link and the entry's remark name it instead. (P3-T16)
- Grant Income Recognition still reads the GL with locking reads under the sanction lock. The coordinator suggested
  dropping them; they are kept until a contention problem shows up. (P3-T16)
- A GL entry committed at the same moment as a UC's final approval may land after the approval's ledger read and
  before the UC is visible as approved, and then not flag it. Use Recheck Source on a UC approved during busy
  posting, which recovers it. (P3-T17)
- The agencies' official UC / SOE formats (GFR 12-A, 12-C, DST, SERB, UGC) are not built yet. Add each one as a print
  format of Utilisation Certificate and name it in the scheme's or agency's UC Format. (P3-T17)
- Source Changed follows GL entries only. A change outside the ledger (a head's account mapping, an account's type)
  can move an approved UC's figures without flagging it. After such a change, use Recheck Source on the sanction's
  approved UCs. A UC that can't be recomputed after a posting is marked Source Changed and the error is logged.
  (P3-T17)
- The project-side unreconciled read at final approval is not a locking read, so untagged spending posted on the
  project under another cost centre at the same moment as the approval can slip past the gate. The posting then
  flags the UC Source Changed, or Recheck Source catches it. (P3-T17 fix 1)
- PFMS export: payments made by Journal Entry and Expense Claim reimbursements are not exported, and a payment
  cancelled after it was exported is not withdrawn from PFMS. Cancel it in PFMS by hand. The official EAT layout,
  UC upload and the PFMS API adapter wait for the spec and agency access. (P3-T18)
