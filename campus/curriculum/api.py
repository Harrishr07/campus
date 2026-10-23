"""M03-04 Curriculum service API. Other modules call these, never the controllers (D7)."""

from campus.curriculum.effective import effective_curriculum  # noqa: F401  (public API)
from campus.curriculum.offerings import generate_offerings  # noqa: F401  (public API)
from campus.curriculum.outcomes import (  # noqa: F401  (public API, M03-02)
	course_outcomes,
	matrix_for,
	matrix_for_offering,
	seed_program_outcomes,
)


def unmet_prerequisites(student, prerequisites, cache=None):
	"""M03-07 The courses of `prerequisites` (a curriculum row's text) that `student` has not passed in a published
	result (examinations.api.passed_courses; a `cache` dict kept across the rows of one registration reads them once).
	Transfers, equivalences and waivers have no records yet (M03-09), so they satisfy nothing here; a row with an unmet
	prerequisite is held for review, never passed."""
	from campus.curriculum.registration_rules import prerequisite_codes
	from campus.examinations.api import passed_courses  # lazy: examinations.api pulls in the finance stack

	codes = prerequisite_codes(prerequisites)
	if not codes:
		return []
	cache = {} if cache is None else cache
	if student not in cache:
		cache[student] = passed_courses(student)
	return [course for course in codes if course not in cache[student]]
