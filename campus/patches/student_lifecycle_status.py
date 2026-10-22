"""M05-09 (L-01) Give every existing student its lifecycle status from its records, with one Migrated Lifecycle
Transition each: a submitted Admission Cancellation -> Cancelled, a Convocation List place -> Award Eligible,
Completed -> Study Completed, a transfer certificate -> Withdrawn, an open break (or Break of Study) -> On Break,
Discontinued stays; Active, Detained (kept as Student.oc_detained), Long Absent and blank -> Active. Students that
already have a Lifecycle Transition are skipped (idempotent)."""


def execute():
	from campus.student_services.lifecycle import migrate_students
	from campus.student_services.setup import seed_lifecycle_rules, setup_student_fields

	setup_student_fields()  # the new options and oc_detained before the statuses are written
	seed_lifecycle_rules()
	migrate_students()
