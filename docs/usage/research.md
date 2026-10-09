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
