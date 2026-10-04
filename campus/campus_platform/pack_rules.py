"""M17-01 Pure rules that decide whether a module pack is available to an institution."""

AFFILIATED = "Affiliated"


def effective_status(institution_status, effective_from, on_date):
	"""Status in force on `on_date`. Before `status_effective_from` the college is still Affiliated."""
	if effective_from and str(effective_from) > str(on_date):
		return AFFILIATED
	return institution_status


def status_allows_pack(allowed_statuses, status):
	"""A pack with no allowed statuses is available for every status."""
	return not allowed_statuses or status in allowed_statuses
