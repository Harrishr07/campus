# IQAC operations (P3-T08)

- **Committee Compliance** report (IQAC module): per committee, Held meetings in the chosen period against the Body Type's `min_meetings_per_year`; "Below minimum" rows are flagged, unmet composition rules are listed. Set the minimum on the Body Type. Choose a one-year period.
- **IQAC Calendar** report: meetings of Bodies of Body Type IQAC plus Regulator Submissions falling due. Planned activities as a separate record are deferred.
- **IQAC Action Taken Report**: Meeting Action Items of the period's meetings (any committee, or one Body Type), with Done / Overdue state and action taken.
- **Regulator Submission Type**: regulator, due rule (fixed date each year, or days after period end) and reminder days (default `30,7,1`). Official templates are not seeded; the college creates its types.
- **Regulator Submission**: type, period end, owner. The due date is computed. While Pending the owner is messaged on each reminder day; after the due date the owner and the Principal (position PRINCIPAL of the company) are messaged weekly until it is Submitted, Acknowledged or Waived. Daily scheduler: `campus.iqac.regulator.send_reminders`.
- **Institutional MoU**: partner, purpose, period, `Used For` (Placement, Research ...), activities. Status follows the period.
