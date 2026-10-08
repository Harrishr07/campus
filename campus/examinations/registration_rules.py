"""M06-01 Exam registration rules (pure, no frappe): per-course eligibility and the late fee slab.

Eligibility of one registered course, first match wins:
- malpractice debarment bars every course of the session;
- shortage of attendance (SA) bars the courses attended this term (current and dropped re-registered),
  while an arrear stays registrable (R2022 cl. 15.1);
- detention bars the term's courses the same way;
- otherwise the course is eligible.
"""

CURRENT, ARREAR, DROPPED = "Current", "Arrear", "Dropped"
KINDS = (CURRENT, ARREAR, DROPPED)
TERM_KINDS = (CURRENT, DROPPED)  # courses attended in the session's term

ELIGIBLE = "Eligible"
SHORTAGE = "Not eligible (SA)"
DETAINED = "Not eligible (Detained)"
DEBARRED = "Not eligible (Debarred)"


def course_eligibility(kind, shortage, detained=False, debarred=False):
	"""The eligibility label of a course of `kind` for a student with the given flags."""
	if kind not in KINDS:
		raise ValueError(f"Unknown exam registration course kind: {kind}")
	if debarred:
		return DEBARRED
	if kind in TERM_KINDS and shortage:
		return SHORTAGE
	if kind in TERM_KINDS and detained:
		return DETAINED
	return ELIGIBLE


def late_fee(days_late, slabs):
	"""The late fee for registering `days_late` days after the closing date; None when registration is closed.

	`slabs` is [(from_day, to_day, fee)], both days inclusive. On time (0 or fewer days late) costs nothing;
	a day no slab covers (past the last slab, or in a gap) means registration is closed.
	"""
	if days_late <= 0:
		return 0
	for from_day, to_day, fee in slabs:
		if from_day <= days_late <= to_day:
			return fee
	return None
