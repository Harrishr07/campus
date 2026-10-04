"""M03-04 Curriculum service API. Other modules call these, never the controllers (D7)."""

from campus.curriculum.offerings import generate_offerings  # noqa: F401  (public API)


def prerequisites_met(student, course):
	"""True when `student` has met the prerequisites of `course`.

	Stub until Phase 2 supplies results: every student is treated as eligible.
	"""
	return True
