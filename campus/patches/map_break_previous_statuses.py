"""M05-09 (L-01 fix round 2) Sites that ran student_lifecycle_status before its fix round 1 body: map the pre-L-01
academic statuses still kept on Break of Study (previous_status) onto lifecycle statuses and keep the detention of a
student detained before a break still open. Idempotent (lifecycle.migrate_break_statuses)."""


def execute():
	from campus.student_services.lifecycle import migrate_break_statuses

	migrate_break_statuses()
