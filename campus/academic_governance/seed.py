"""M02-01 Seed the Body Types of UGC 2023 cl. 12 and the non-statutory committees. Idempotent: an existing Body
Type is never touched, so a college's edited rules survive every migrate."""

import frappe

# (name, statutory, term years, minimum meetings a year, quorum %, [(category, min, max, mandatory for quorum)])
SIX_MONTHLY = 2
STATUTORY = [
	("Governing Body", 5, SIX_MONTHLY, 50, [("University Nominee", 1, 0, 1)]),
	("Academic Council", 3, SIX_MONTHLY, 50, [("University Nominee", 3, 3, 0)]),
	("Board of Studies", 3, SIX_MONTHLY, 50, [("External Expert", 1, 0, 0), ("Alumni", 1, 0, 0)]),
	("Finance Committee", 3, SIX_MONTHLY, 50, []),
]
NON_STATUTORY = [
	"Planning and Evaluation Committee",
	"Grievance Redressal Committee",
	"Examination Committee",
	"Admission Committee",
	"Library Committee",
	"Internal Complaints Committee",
	"Anti-Ragging Committee",
	"Class Committee",
	"Course Committee",
	"Passing Board",
	"IQAC",
]


def seed_body_types():
	for name, term_years, meetings, quorum, rules in STATUTORY:
		make_body_type(name, 1, term_years=term_years, min_meetings_per_year=meetings, quorum_percent=quorum, rules=rules)
	for name in NON_STATUTORY:
		make_body_type(name, 0)


def make_body_type(name, statutory, rules=(), **values):
	if frappe.db.exists("Body Type", name):
		return
	frappe.get_doc(
		{
			"doctype": "Body Type",
			"body_type_name": name,
			"statutory": statutory,
			"composition": [
				{"category": c, "minimum_count": low, "maximum_count": high, "mandatory_for_quorum": must} for c, low, high, must in rules
			],
			**values,
		}
	).insert(ignore_permissions=True)
