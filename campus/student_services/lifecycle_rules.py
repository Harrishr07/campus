"""M05-09 Student lifecycle rules (pure, no database): the lifecycle statuses, the seeded transition graph, the
checks every transition passes and the status a student recorded before L-01 is migrated to.

An applicant is not a student: "Applicant" stays on Student Applicant. Detention (progression) is not a lifecycle
status: a detained student is Active and repeats the semester (Student.oc_detained).
"""

ADMITTED, JOINED, ACTIVE, ON_BREAK = "Admitted", "Joined", "Active", "On Break"
DISCONTINUED, WITHDRAWN, CANCELLED, READMITTED = "Discontinued", "Withdrawn", "Cancelled", "Readmitted"
STUDY_COMPLETED, AWARD_ELIGIBLE, GRADUATED, ALUMNI = (
	"Study Completed",
	"Award Eligible",
	"Graduated",
	"Alumni",
)
STATUSES = [
	ADMITTED, JOINED, ACTIVE, ON_BREAK, DISCONTINUED, WITHDRAWN, CANCELLED, READMITTED,
	STUDY_COMPLETED, AWARD_ELIGIBLE, GRADUATED, ALUMNI,
]  # fmt: skip
NEW = ""  # the "from" of a record's first status
ON_ROLL = (
	JOINED,
	ACTIVE,
	ON_BREAK,
)  # studying: a TC means they withdraw (each has a seeded rule to Withdrawn)

# The seeded transition table (Lifecycle Transition Rule records); colleges disable or add rows.
DEFAULT_TRANSITIONS = [
	(NEW, ADMITTED), (NEW, ACTIVE),
	(ADMITTED, JOINED), (ADMITTED, CANCELLED),
	(JOINED, ACTIVE), (JOINED, CANCELLED), (JOINED, WITHDRAWN),
	(ACTIVE, ON_BREAK), (ACTIVE, DISCONTINUED), (ACTIVE, WITHDRAWN), (ACTIVE, CANCELLED), (ACTIVE, STUDY_COMPLETED),
	(ON_BREAK, ACTIVE), (ON_BREAK, DISCONTINUED), (ON_BREAK, WITHDRAWN),
	(DISCONTINUED, READMITTED), (WITHDRAWN, READMITTED),
	(READMITTED, ACTIVE),
	(STUDY_COMPLETED, AWARD_ELIGIBLE),
	(AWARD_ELIGIBLE, GRADUATED),
	(GRADUATED, ALUMNI),
]  # fmt: skip

UNKNOWN_STATUS, SAME_STATUS, NOT_PERMITTED, BEFORE_LATEST = (
	"unknown",
	"same",
	"not permitted",
	"before latest",
)

# Phase 1/2 academic statuses that are not lifecycle statuses
LEGACY_BREAK, LEGACY_COMPLETED, LEGACY_DISCONTINUED = "Break of Study", "Completed", "Discontinued"
LEGACY_DETAINED = "Detained"


def refusal(permitted, from_status, to_status, effective_date, latest_effective):
	"""Why moving from `from_status` to `to_status` on `effective_date` is refused, or None when it is allowed.

	`permitted` holds the enabled (from, to) pairs; `latest_effective` is the effective date of the student's last
	status change (None for a new record). A change never takes effect before the last one did."""
	from_status = from_status or NEW
	if to_status not in STATUSES:
		return UNKNOWN_STATUS
	if from_status == to_status:
		return SAME_STATUS
	if (from_status, to_status) not in permitted:
		return NOT_PERMITTED
	if latest_effective and effective_date < latest_effective:
		return BEFORE_LATEST
	return None


def migrated_status(old_status, cancelled=False, left=False, open_break=False, convocation=False):
	"""The lifecycle status of a student recorded before L-01, from its academic status and records: a submitted
	Admission Cancellation (`cancelled`), a transfer certificate (`left`), an approved break with no rejoin
	(`open_break`), a place on a Convocation List (`convocation`)."""
	if cancelled:
		return CANCELLED
	if old_status in (GRADUATED, ALUMNI):
		return old_status  # past the convocation list already
	if convocation:
		return AWARD_ELIGIBLE  # a TC to a graduate does not make them withdrawn
	if old_status == LEGACY_COMPLETED:
		return STUDY_COMPLETED
	if left:
		return WITHDRAWN
	if open_break or old_status == LEGACY_BREAK:
		return ON_BREAK
	if old_status == LEGACY_DISCONTINUED:
		return DISCONTINUED
	if old_status in STATUSES:
		return old_status
	return ACTIVE  # Active, Detained (kept as oc_detained), Long Absent, blank
