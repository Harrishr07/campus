"""M06-01 Exam registration rules (pure, no frappe): per-course eligibility and the late fee slab.

Eligibility of one registered course, first match wins:
- malpractice debarment bars every course of the session;
- shortage of attendance (SA) bars the courses attended this term (current and dropped re-registered),
  while an arrear stays registrable (R2022 cl. 15.1);
- detention bars the term's courses the same way;
- an offered bridge course of a rejoining student (P2-T21) is attended this term: barred like a current one, but it
  is not a TERM_KINDS course (a withdrawal is only for those);
- otherwise the course is eligible.
"""

CURRENT, ARREAR, DROPPED, BRIDGE = "Current", "Arrear", "Dropped", "Bridge"
KINDS = (CURRENT, ARREAR, DROPPED, BRIDGE)
TERM_KINDS = (CURRENT, DROPPED)  # courses of the session's term (the only ones a student may withdraw from)
ATTENDED_KINDS = (*TERM_KINDS, BRIDGE)  # courses attended in the term: attendance applies

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
	if kind in ATTENDED_KINDS and shortage:
		return SHORTAGE
	if kind in ATTENDED_KINDS and detained:
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
