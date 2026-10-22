"""M12-02, M06-05 Student Result: a student's course grades, SGPA, CGPA, result, arrears and (final year)
classification for one Exam Session.

Created by the Result Run (campus.examinations.results) or, for an Affiliated session, by a University Result Import
(campus.examinations.university_import; source University). Versioned: version 1 is SR-<session>-<student>,
a later version (a re-run after publication) SR-<session>-<student>-V<n>, linked to the one it replaces with
its change log; only the latest has is_latest set. Read access follows publication (campus.examinations.access).
"""

from frappe.model.document import Document


def result_name(exam_session, student, version=1):
	base = f"SR-{exam_session}-{student}"
	return base if version == 1 else f"{base}-V{version}"


class StudentResult(Document):
	def autoname(self):
		self.name = result_name(self.exam_session, self.student, self.version or 1)
