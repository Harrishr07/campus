"""M06-04 Examiner remuneration: the work an examiner did in an Exam Session, read from the source records, priced by
the Remuneration Rate in force on the work date, less the work another live claim already holds.

Sources (one claim line per source, quantity from the record):
- Valuation: each Completed Valuation Allocation of the examiner (by Employee / External Member or user), counted
  in submitted Valuation Entries (scripts valued), activity "Valuation Round <n>", work date the last entry's.
- QP Setting / QP Scrutiny: each QP Setter Nomination naming the employee as setter or scrutiniser, once the
  course's approved paper has been released (so a claim never reveals a setter before the exam); work date the
  nomination's deadline (the release is only the gate).
- Invigilation: each duty of the employee in the session's Invigilation Roster dated before the claim date and before
  today (a duty of today may not have been held yet).
Each line carries a source key (what was done, not a row name, so a regenerated roster or a recreated nomination
cannot be paid twice; a valuation key also names its allocation, so a bundle reallocated to another examiner is theirs). Claim Item.source_key is unique in the database; the controller also re-reads claimed keys
with a locking read after locking the examiner's master row.
"""

import frappe
from frappe import _
from frappe.utils import getdate, now_datetime, today

from campus.examinations import remuneration_rules as rules

CLAIM = "Examiner Remuneration Claim"
CLAIM_ITEM = "Examiner Remuneration Claim Item"
QP_SETTING, QP_SCRUTINY, INVIGILATION = "QP Setting", "QP Scrutiny", "Invigilation"


def work_lines(claim):
	"""Priced lines of the examiner's work in the claim's session, unclaimed by other live claims, and the names of
	the claims that hold the rest. Locks the examiner's master row first."""
	lock_examiner(claim)
	lines = unique_by_key([*valuation_work(claim), *qp_work(claim), *invigilation_work(claim)])
	held = claimed_elsewhere([line["source_key"] for line in lines], claim.name)
	free = [line for line in lines if line["source_key"] not in held]
	price(claim.company, free)
	return free, sorted(set(held.values()))


def lock_examiner(claim):
	if claim.examiner_type == "Internal":
		frappe.db.get_value("Employee", claim.employee, "name", for_update=True)
	else:
		frappe.db.get_value("External Member", claim.external_member, "name", for_update=True)


def valuation_work(claim):
	who = (
		{"employee": claim.employee}
		if claim.examiner_type == "Internal"
		else {"external_member": claim.external_member}
	)
	if claim.examiner_user:
		who["examiner"] = claim.examiner_user
	allocations = frappe.get_all(
		"Valuation Allocation", {"exam_session": claim.exam_session, "status": "Completed"},
		["name", "bundle", "valuation_round"], or_filters=who, order_by="name",
	)  # fmt: skip
	if not allocations:
		return []
	valued = {
		row.allocation: row
		for row in frappe.get_all(
			"Valuation Entry",
			{"allocation": ["in", [a.name for a in allocations]], "docstatus": 1},
			["allocation", {"COUNT": "name", "as": "scripts"}, {"MAX": "creation", "as": "last_valued"}],
			group_by="allocation",
		)  # fmt: skip
	}
	return [
		line(
			f"Valuation Round {a.valuation_round}",
			"Valuation Allocation",
			a.name,
			_("Bundle {0}").format(a.bundle),
			valued[a.name].last_valued,
			valued[a.name].scripts,
			("Valuation", a.bundle, a.valuation_round, a.name),
		)
		for a in allocations
		if a.name in valued
	]


def qp_work(claim):
	released = released_papers(claim.exam_session)
	if claim.examiner_type != "Internal" or not released:
		return []
	nominations = frappe.get_all(
		"QP Setter Nomination", {"exam_session": claim.exam_session, "course": ["in", list(released)]},
		["name", "course", "scrutiniser", "deadline"], order_by="name",
	)  # fmt: skip
	setting = set(
		frappe.get_all(
			"QP Nomination Setter",
			{
				"parenttype": "QP Setter Nomination",
				"parent": ["in", [n.name for n in nominations] or [""]],
				"employee": claim.employee,
			},
			pluck="parent",
		)
	)
	lines = []
	for n in nominations:
		for activity, applies in (
			(QP_SETTING, n.name in setting),
			(QP_SCRUTINY, n.scrutiniser == claim.employee),
		):
			if applies:
				key = ("QP", claim.exam_session, n.course, activity, claim.employee)
				lines.append(line(activity, "QP Setter Nomination", n.name, n.course, n.deadline, 1, key))
	return lines


def released_papers(exam_session):
	"""{course: release date} of the session's approved papers already released (the gate; work is priced on the
	nomination's deadline, when the paper was set)."""
	papers = frappe.get_all(
		"Question Paper",
		{
			"exam_session": exam_session,
			"docstatus": 1,
			"moderation_status": "Approved",
			"release_at": ["<=", now_datetime()],
		},
		["course", "release_at"],
	)
	return {p.course: getdate(p.release_at) for p in papers}


def invigilation_work(claim):
	roster = frappe.db.get_value("Invigilation Roster", {"exam_session": claim.exam_session}, "name")
	if claim.examiner_type != "Internal" or not roster:
		return []
	duties = frappe.get_all(
		"Invigilation Duty",
		{"parenttype": "Invigilation Roster", "parent": roster, "employee": claim.employee, "exam_date": ["<", held_before(claim)]},
		["exam_date", "slot", "room"], order_by="exam_date, slot",
	)  # fmt: skip
	return [
		line(
			INVIGILATION,
			"Invigilation Roster",
			roster,
			f"{d.exam_date} {d.slot or ''} {d.room or ''}".strip(),
			d.exam_date,
			1,
			("Invigilation", claim.exam_session, d.exam_date, d.slot, claim.employee),
		)
		for d in duties
	]


def held_before(claim):
	"""Duties before the claim date, and never one not yet held (a slot of today may still be running)."""
	return min(getdate(claim.posting_date), getdate(today()))


def line(activity, source_doctype, source_name, details, work_date, quantity, key_parts):
	return {
		"activity": activity, "source_doctype": source_doctype, "source_name": source_name, "details": details,
		"work_date": getdate(work_date), "quantity": quantity, "source_key": "|".join(str(p or "") for p in key_parts),
	}  # fmt: skip


def unique_by_key(lines):
	"""One line per source key (two nominations of one course pay its setter once)."""
	seen = {}
	for row in lines:
		seen.setdefault(row["source_key"], row)
	return list(seen.values())


def claimed_elsewhere(keys, claim_name):
	"""{source key: claim} for the keys another live claim holds (locking read: keys are cleared on cancel)."""
	if not keys:
		return {}
	item = frappe.qb.DocType(CLAIM_ITEM)
	rows = (
		frappe.qb.from_(item)
		.select(item.source_key, item.parent)
		.where(item.source_key.isin(keys) & (item.parenttype == CLAIM) & (item.parent != (claim_name or "")))
		.for_update()
	).run()
	return dict(rows)


def price(company, lines):
	"""Set rate, amount, the rate record and its Item on each line; throws naming an activity without a rate."""
	versions = {}
	for row in lines:
		if row["activity"] not in versions:
			versions[row["activity"]] = frappe.get_all(
				"Remuneration Rate",
				{"company": company, "activity": row["activity"]},
				["name", "from_date", "rate", "item"],
			)
		rate = rules.rate_on(versions[row["activity"]], row["work_date"])
		if not rate:
			frappe.throw(
				_("No Remuneration Rate for {0} in {1} on {2}.").format(
					_(row["activity"]), company, frappe.format(row["work_date"], "Date")
				)
			)
		row.update(
			rate=rate["rate"],
			amount=rules.line_amount(row["quantity"], rate["rate"]),
			remuneration_rate=rate["name"],
			item=rate["item"],
		)
