"""PR-05 Role-permission matrix: dumps every campus role's permissions on every campus DocType and report to
docs/usage/permission-matrix.csv, and fails loudly when a rule below is broken.

    bench --site <site> execute campus.setup.permission_matrix.run

Rules (each a defect line naming the DocType and role):
- only System Manager may delete a record kept for history (HISTORY_KEPT);
- Student, Guardian and Guest read only the DocTypes in STUDENT_READABLE, and never share or export any;
- a confidential DocType (the restricted-record hook list, CO Attainment Snapshot, the exam-confidential set) is
  readable only by the roles listed for it in CONFIDENTIAL_READERS.
The rules read the permissions the site resolves (Custom DocPerm included), so run them on a migrated site.
"""

import csv
import os

import frappe
from frappe import _

FLAGS = ("read", "write", "create", "delete", "submit", "cancel", "export", "print", "share")
OWNER = "System Manager"
STUDENT_FACING = ("Student", "Guardian", "Guest")

# Lifecycle, official documents, results, certificates and the financial / audit ledgers: kept as history.
# Round Result (a placement round's shortlist) is deliberately not listed: the Placement Officer deletes a wrongly
# created one (commit 7c53906).
HISTORY_KEPT = (
	"Lifecycle Transition", "Official Document", "Completion Check", "Verifiable Document",
	"Student Result", "Result Ratification", "Mark Sheet Entry",
	"Hall Ticket", "Certificate Request", "Utilisation Certificate",
	"Grant Receipt", "Grant Interest", "Grant Income Recognition", "Scholarship Disbursement", "Fee Refund",
	"Fine Applied", "No Dues Clearance",
	"Aadhaar Access Log", "QP Access Log", "Seat Override Log", "Message Log",
)  # fmt: skip

# What a student, guardian or guest may open on the desk (the portal reads through its own API).
STUDENT_READABLE = (
	"Certificate Request", "Circular", "Condonation Request", "Hall Ticket", "Student Grievance", "Student Result",
)  # fmt: skip

_MENTORING = ("Mentor", "Class Advisor", "Dean Student Affairs", "HOD", "Principal")
_EXAM_CONFIDENTIAL = ("Exam Confidential", "COE", "Examiner")
CONFIDENTIAL_READERS = {
	"Counselling Note": ("Mentor", "Student Counsellor", "HOD", "Principal"),
	"Parent Interaction": _MENTORING,
	"CO Attainment Snapshot": ("COE", "Dean Academics"),
	"Answer Script Bundle": _EXAM_CONFIDENTIAL,
	"Dummy Number Map": _EXAM_CONFIDENTIAL,
	"QP Access Log": _EXAM_CONFIDENTIAL,
	"QP Setter Nomination": _EXAM_CONFIDENTIAL,
	"Question Bank Item": _EXAM_CONFIDENTIAL,
	"Question Paper": _EXAM_CONFIDENTIAL,
	"Question Paper Settings": _EXAM_CONFIDENTIAL,
	"Valuation Allocation": _EXAM_CONFIDENTIAL,
	"Valuation Entry": _EXAM_CONFIDENTIAL,
}  # fmt: skip


def run(path=None):
	"""Write the CSV and raise when a rule is broken. Returns the number of rows written."""
	rows = collect_rows()
	write_csv(rows, path or default_path())
	defects = find_defects(rows, frappe.get_hooks("restricted_record_doctypes") or [])
	if defects:
		frappe.throw("<br>".join(defects), title=_("Permission defects"))
	print(f"{len(rows)} permission rows written, no defects")
	return len(rows)


def default_path():
	return os.path.join(frappe.get_app_path("campus", "..", "docs", "usage"), "permission-matrix.csv")


def campus_modules():
	with open(frappe.get_app_path("campus", "modules.txt")) as modules:
		return [line.strip() for line in modules if line.strip()]


def collect_rows():
	"""One row per (kind, name, role, permlevel); kind is DocType or Report. Sorted for a stable diff."""
	modules = campus_modules()
	rows = []
	for doctype in frappe.get_all("DocType", {"module": ["in", modules]}, pluck="name"):
		rows += [doctype_row(doctype, perm) for perm in frappe.get_meta(doctype).permissions]
	for report in frappe.get_all("Report", {"module": ["in", modules]}, pluck="name"):
		roles = frappe.get_all("Has Role", {"parent": report, "parenttype": "Report"}, pluck="role")
		rows += [{"kind": "Report", "name": report, "role": role, "permlevel": 0, "read": 1} for role in roles]
	return sorted(rows, key=lambda r: (r["kind"], r["name"], r["role"], r["permlevel"]))


def doctype_row(doctype, perm):
	row = {"kind": "DocType", "name": doctype, "role": perm.role, "permlevel": perm.permlevel or 0}
	return row | {flag: int(bool(perm.get(flag))) for flag in FLAGS}


def write_csv(rows, path):
	with open(path, "w", newline="") as out:
		writer = csv.DictWriter(out, ["kind", "name", "role", "permlevel", *FLAGS], restval=0, lineterminator="\n")
		writer.writeheader()
		writer.writerows(rows)


def find_defects(rows, restricted_doctypes):
	"""Pure over the rows (see collect_rows), so each rule is testable with synthetic rows."""
	doctype_rows = [row for row in rows if row["kind"] == "DocType"]
	return (
		history_defects(doctype_rows)
		+ student_defects(doctype_rows)
		+ confidential_defects(doctype_rows, restricted_doctypes)
	)


def history_defects(rows):
	return [
		f"{row['name']}: {row['role']} can delete a record kept for history"
		for row in rows
		if row["name"] in HISTORY_KEPT and row.get("delete") and row["role"] != OWNER
	]


def student_defects(rows):
	defects = []
	for row in rows:
		if row["role"] not in STUDENT_FACING:
			continue
		if row.get("read") and row["name"] not in STUDENT_READABLE:
			defects.append(f"{row['name']}: {row['role']} can read a staff-only DocType")
		for flag in ("share", "export"):
			if row.get(flag):
				defects.append(f"{row['name']}: {row['role']} can {flag}")
	return defects


def confidential_defects(rows, restricted_doctypes):
	defects = [f"{name}: restricted record without a reader list" for name in restricted_doctypes if name not in CONFIDENTIAL_READERS]
	for row in rows:
		readers = CONFIDENTIAL_READERS.get(row["name"])
		if readers is not None and row.get("read") and row["role"] not in (*readers, OWNER):
			defects.append(f"{row['name']}: {row['role']} can read a confidential DocType")
		if row["role"] == "Exam Confidential" and row["name"] not in CONFIDENTIAL_READERS:
			defects.append(f"{row['name']}: exam-confidential DocType without a reader list")
	return defects
