"""M03-04 Curriculum service API. Other modules call these, never the controllers (D7)."""

from campus.curriculum.effective import effective_curriculum  # noqa: F401  (public API)
from campus.curriculum.offerings import generate_offerings  # noqa: F401  (public API)
from campus.curriculum.outcomes import (  # noqa: F401  (public API, M03-02)
	course_outcomes,
	matrix_for,
	matrix_for_offering,
	seed_program_outcomes,
)


def prerequisites_met(student, course):
	"""True when `student` has met the prerequisites of `course`.

	Stub until Phase 2 supplies results: every student is treated as eligible.
	"""
	return True
