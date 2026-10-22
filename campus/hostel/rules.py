"""M10-01 Hostel rules that need no database: who a hostel can take."""


def gender_allowed(hostel_gender, student_gender):
	"""A male hostel takes male students and a female hostel female students; nobody else."""
	return bool(hostel_gender) and hostel_gender == student_gender
