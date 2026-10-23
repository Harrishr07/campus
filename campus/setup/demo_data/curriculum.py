"""PR-03 Curriculum of the 2025 batch: one Effective eight-semester R2022 curriculum per programme, in the credit range the
regulation's Curriculum Rule demands (165-170). Semesters 1 and 2 are common to all programmes, semester 3 of CSE has
its real course names, the rest are generic programme courses (the point is the credit structure, not a syllabus)."""

import frappe

from campus.campus_platform.doctype.regulation.regulation import regulation_name

THEORY, PRACTICAL = "Theory", "Practical"
# title, category, L, T, P, exam type. Credits at the R2022 rates (L 1, T 1, P 0.5): 3-1-0 = 4, 3-0-2 = 4, 3-0-0 = 3, 0-0-4 = 2.
COMMON = {
	1: [
		("Matrices and Calculus", "BSC", 3, 1, 0, THEORY), ("Engineering Physics", "BSC", 3, 0, 2, THEORY),
		("Problem Solving and Python Programming", "ESC", 3, 0, 2, THEORY), ("Technical English", "HSMC", 3, 0, 0, THEORY),
		("Engineering Graphics", "ESC", 3, 0, 2, THEORY), ("Physics and Chemistry Laboratory", "BSC", 0, 0, 4, PRACTICAL),
	],
	2: [
		("Statistics and Numerical Methods", "BSC", 3, 1, 0, THEORY), ("Engineering Chemistry", "BSC", 3, 0, 2, THEORY),
		("Basic Electrical and Electronics Engineering", "ESC", 3, 0, 2, THEORY), ("Professional English", "HSMC", 3, 0, 0, THEORY),
		("Engineering Mechanics", "ESC", 3, 1, 0, THEORY), ("Engineering Practices Laboratory", "ESC", 0, 0, 4, PRACTICAL),
	],
}  # fmt: skip
CSE_SEMESTER_3 = [
	("Discrete Mathematics", "BSC", 3, 1, 0, THEORY), ("Data Structures", "PCC", 3, 0, 2, THEORY),
	("Digital Principles and Computer Organization", "ESC", 3, 1, 0, THEORY), ("Object Oriented Programming", "PCC", 3, 1, 0, THEORY),
	("Database Management Systems", "PCC", 3, 0, 0, THEORY), ("Data Structures Laboratory", "PCC", 0, 0, 4, PRACTICAL),
]  # fmt: skip
GENERIC_SEMESTER = [  # semesters 4-7 (and 3 outside CSE): 4 + 4 + 4 + 4 + 3 + 2 = 21 credits
	("Core {sem}.1", "PCC", 3, 1, 0, THEORY), ("Core {sem}.2", "PCC", 3, 1, 0, THEORY), ("Core {sem}.3", "PCC", 3, 1, 0, THEORY),
	("Core {sem}.4", "PCC", 3, 1, 0, THEORY), ("Core {sem}.5", "PCC", 3, 0, 0, THEORY), ("Laboratory {sem}", "PCC", 0, 0, 4, PRACTICAL),
]  # fmt: skip
SEMESTER_8 = [  # 10 + 4 + 4 = 18 credits: with 21 x 7 = 147 the total is 165, the regulation's minimum
	("Project Work", "EEC", 0, 0, 20, "Project"), ("Professional Elective VI", "PEC", 3, 1, 0, THEORY),
	("Open Elective", "OEC", 3, 1, 0, THEORY),
]  # fmt: skip


def semester_courses(abbr, semester):
	"""[(course name, category, L, T, P, exam type)] of one semester of the programme `abbr`."""
	if semester in COMMON:
		return COMMON[semester]
	if semester == 3 and abbr == "CSE":
		return CSE_SEMESTER_3
	template = SEMESTER_8 if semester == 8 else GENERIC_SEMESTER
	return [(f"{abbr} {title.format(sem=semester)}", *rest) for title, *rest in template]


def load(ctx):
	"""Make the courses and the curriculum of every programme Effective, in the regulation of the profile."""
	regulation = regulation_name(ctx.profile["regulation"]["code"], ctx.college)
	for programme in ctx.profile["programmes"]:
		ensure_curriculum(ctx, programme, regulation)


def ensure_curriculum(ctx, programme, regulation):
	existing = frappe.db.get_value("Curriculum", {"program": programme["name"], "regulation": regulation, "version": 1})
	if existing:
		return existing
	rows = []
	for semester in range(1, 9):
		for title, category, lecture, tutorial, practical, exam_type in semester_courses(programme["abbr"], semester):
			name = title
			if not frappe.db.exists("Course", name):
				frappe.get_doc({"doctype": "Course", "course_name": name, "oc_company": ctx.college}).insert(ignore_permissions=True)
				ctx.out.created["Course"] += 1
			row = {
				"semester": semester, "course": name, "category": category, "lecture_periods": lecture,
				"tutorial_periods": tutorial, "practical_periods": practical, "exam_type": exam_type,
			}  # fmt: skip
			if exam_type == "Project":
				row.update(credits=10, credits_override=1)
			rows.append(row)
	doc = frappe.get_doc(
		{
			"doctype": "Curriculum", "program": programme["name"], "regulation": regulation, "version": 1, "company": ctx.college,
			"courses": rows,
		}
	)  # fmt: skip
	doc.insert(ignore_permissions=True)
	for status in ("Approved", "Effective"):
		doc.status = status
		doc.save(ignore_permissions=True)
	ctx.out.created["Curriculum"] += 1
	return doc.name
