"""M06-07 P2-T22 fix round 1: the graduate examination Certificate Types (consolidated grade sheet, provisional and
degree certificates, degree data sheet) were seeded without approval; require it. DML only."""

from campus.examinations.exam_certificates import require_graduate_approval


def execute():
	require_graduate_approval()
