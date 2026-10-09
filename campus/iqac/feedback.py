"""M01-05 / M03-03 / M07-04 Feedback engine: who may answer a Feedback Campaign, recording a response, and the indirect
CO scores of a course offering.

Anonymity. A response of an anonymous campaign is written by a plain insert (no document hooks, so no Version, follow,
comment or notification) with owner "Guest", no respondent and its times set to midnight of the response day. One
response per respondent is kept by Feedback Response Token: its name is an HMAC (site encryption key) of campaign and
respondent, its owner "Guest" and its times the campaign's start, so a token tells neither when it was made nor which
response it belongs to. Nothing here logs the respondent. Reports show only groups of at least the minimum group size
(Campus Settings > Feedback Minimum Group Size).

Respondents are "Doctype:name" keys, as messaging uses: Student / Guardian / Employee / User records of the session user
for internal audiences, and "External Member:<name>" for invited alumni and employers, who answer by a signed link.
"""

import hashlib
import hmac
import json
from datetime import datetime, time

import frappe
from frappe import _
from frappe.query_builder.functions import Avg, Count
from frappe.utils import cint, flt, getdate, today
from frappe.utils.password import get_encryption_key

from campus.campus_messaging.api import audience_members, recipient_keys_for_user

RESPONSE, TOKEN, ANSWER = "Feedback Response", "Feedback Response Token", "Feedback Answer"
EXTERNAL = ("Alumni", "Employers")
LIKERT = range(1, 6)
TEXT_LIMIT = 2000
ANONYMOUS_OWNER = "Guest"


# Keys, tokens and signatures


def keyed_hash(*parts):
	message = "\n".join(str(part) for part in parts).encode()
	return hmac.new(get_encryption_key().encode(), message, hashlib.sha256).hexdigest()


def token_name(campaign, respondent):
	"""The Feedback Response Token name of `respondent` for `campaign`; it reveals neither."""
	return keyed_hash("feedback-token", campaign, respondent)


def invite_signature(campaign, respondent):
	return keyed_hash("feedback-invite", campaign, respondent)[:32]


def valid_signature(campaign, respondent, signature):
	return bool(signature) and hmac.compare_digest(invite_signature(campaign, respondent), str(signature))


def has_responded(campaign, respondent):
	return bool(frappe.db.exists(TOKEN, token_name(campaign, respondent)))


# Audience


def respondents(campaign):
	"""Every respondent key the campaign addresses (also who is invited and reminded)."""
	if campaign.audience in EXTERNAL:
		return [f"External Member:{row.member}" for row in campaign.invitees]
	if campaign.audience_rule:
		return audience_members(campaign.audience_rule)
	if campaign.audience == "Teachers":
		return offering_teachers(campaign.course_offering)
	rule = {"doctype": "Audience Rule", "company": campaign.company, "rule_type": "Student Group", "student_group": campaign.course_offering}
	if campaign.audience == "Parents":
		rule.update({"rule_type": "Guardians of", "guardians_of": "Student Group"})
	return audience_members(frappe.get_doc(rule))


def offering_teachers(offering):
	instructors = frappe.get_all("Student Group Instructor", {"parent": offering, "parenttype": "Student Group"}, pluck="instructor")
	employees = frappe.get_all("Instructor", {"name": ["in", instructors or [""]]}, pluck="employee")
	active = frappe.get_all("Employee", {"name": ["in", [e for e in employees if e] or [""]], "status": "Active"}, pluck="name")
	return [f"Employee:{name}" for name in sorted(active)]


def respondent_key(campaign, member=None, signature=None):
	"""The key the caller answers as: an invited member by a valid signed link, else a record of the session user."""
	if member or signature:
		key = f"External Member:{member}"
		if campaign.audience not in EXTERNAL or key not in respondents(campaign) or not valid_signature(campaign.name, key, signature):
			frappe.throw(_("This feedback link is not valid."), frappe.PermissionError)
		return key
	if frappe.session.user == "Guest":
		frappe.throw(_("Please log in to give feedback."), frappe.PermissionError)
	matches = sorted(recipient_keys_for_user(frappe.session.user) & set(respondents(campaign)))
	if not matches:
		frappe.throw(_("This feedback is not addressed to you."), frappe.PermissionError)
	return matches[0]


def is_open(campaign, day=None):
	return getdate(campaign.start_date) <= getdate(day or today()) <= getdate(campaign.end_date)


def open_campaigns_for(user=None):
	"""[{name, campaign_title, end_date}] of the open campaigns the user may still answer."""
	keys = recipient_keys_for_user(user or frappe.session.user)
	result = []
	for row in frappe.get_all(
		"Feedback Campaign", {"start_date": ["<=", today()], "end_date": [">=", today()]}, ["name"], order_by="end_date"
	):
		campaign = frappe.get_doc("Feedback Campaign", row.name)
		if campaign.audience in EXTERNAL:
			continue
		mine = sorted(keys & set(respondents(campaign)))
		if mine and not has_responded(campaign.name, mine[0]):
			result.append(frappe._dict(name=campaign.name, campaign_title=campaign.campaign_title, end_date=campaign.end_date))
	return result


# Recording a response


@frappe.whitelist(allow_guest=True, methods=["POST"])
def submit_response(campaign, answers, member=None, signature=None):
	"""Record the caller's answers ({question row name: value}, JSON) to an open campaign, once per respondent."""
	campaign = frappe.get_doc("Feedback Campaign", campaign)  # respondents cannot read campaigns; checked below
	if not is_open(campaign):
		frappe.throw(_("This feedback is not open."))
	key = respondent_key(campaign, member, signature)
	rows = answer_rows(frappe.get_doc("Feedback Form", campaign.form), answers)
	claim_token(campaign, key)
	return store_response(campaign, key, rows)


def answer_rows(form, answers):
	"""Answer rows for the form's questions, checked: Likert 1-5, a listed option, text within the limit, required answered."""
	from campus.iqac.doctype.feedback_form.feedback_form import choice_options

	values = json.loads(answers) if isinstance(answers, str) else (answers or {})
	rows = []
	for question in form.questions:
		value = values.get(question.name)
		value = value.strip() if isinstance(value, str) else value
		if value in (None, ""):
			if question.is_required:
				frappe.throw(_("Please answer: {0}").format(question.question))
			continue
		row = {"question_row": question.name, "question": question.question, "question_type": question.question_type, "course_outcome": question.course_outcome}
		if question.question_type == "Likert":
			if str(value) not in {str(n) for n in LIKERT}:
				frappe.throw(_("{0}: choose a rating from 1 to 5.").format(question.question))
			row["rating"] = cint(value)
		elif question.question_type == "Choice":
			if value not in choice_options(question):
				frappe.throw(_("{0}: choose one of the listed options.").format(question.question))
			row["answer"] = value
		else:
			row["answer"] = str(value)[:TEXT_LIMIT]
		rows.append(row)
	return rows


def claim_token(campaign, key):
	"""Insert the respondent's token; the primary key (set by us, never regenerated: autoname Prompt) makes a second or
	concurrent response fail."""
	token = frappe.new_doc(TOKEN)
	token.update({"name": token_name(campaign.name, key), "campaign": campaign.name})
	stamp(token, midnight(campaign.start_date), ANONYMOUS_OWNER)
	try:
		token.db_insert()
	except frappe.DuplicateEntryError:
		frappe.clear_last_message()  # db_insert's "already exists" names the token
		frappe.throw(_("You have already answered this feedback."))


def store_response(campaign, key, rows):
	anonymous = cint(campaign.is_anonymous)
	response = frappe.new_doc(RESPONSE)
	response.update(
		{
			"name": frappe.generate_hash(length=16), "campaign": campaign.name, "form": campaign.form, "company": campaign.company,
			"course_offering": campaign.course_offering, "instructor": campaign.instructor, "response_date": today(),
			"respondent": None if anonymous else key,
		}
	)  # fmt: skip
	owner = ANONYMOUS_OWNER if anonymous else frappe.session.user
	stamp(response, midnight(today()), owner)
	response.db_insert()
	for idx, values in enumerate(rows, 1):
		row = frappe.new_doc(ANSWER, parent_doc=response, parentfield="answers")
		row.update({**values, "name": frappe.generate_hash(length=16), "idx": idx})
		stamp(row, response.creation, owner)
		row.db_insert()
	return response.name


def stamp(doc, when, owner):
	doc.creation = doc.modified = when
	doc.owner = doc.modified_by = owner


def midnight(day):
	return datetime.combine(getdate(day), time())


# Analysis


def minimum_group_size():
	"""Smallest group a report or score may show (Campus Settings); never below 1."""
	return max(cint(frappe.db.get_single_value("Campus Settings", "feedback_minimum_group_size")), 1)


def indirect_co_scores(offering):
	"""{CO: {responses, average, percent, suppressed}} from the CO-tagged Likert answers of the offering's responses.

	average is the mean rating (1-5), percent that mean as a share of 5. A CO answered in fewer responses than the
	minimum group size is suppressed: its figures are None."""
	response, answer = frappe.qb.DocType(RESPONSE), frappe.qb.DocType(ANSWER)
	count, mean = Count(response.name).distinct(), Avg(answer.rating)
	rows = (
		frappe.qb.from_(response)
		.join(answer)
		.on((answer.parent == response.name) & (answer.parenttype == RESPONSE))
		.select(answer.course_outcome, count.as_("responses"), mean.as_("average"))
		.where((response.course_offering == offering) & (answer.question_type == "Likert") & answer.rating.isnotnull())
		.where(answer.course_outcome.isnotnull() & (answer.course_outcome != ""))
		.groupby(answer.course_outcome)
		.run(as_dict=True)
	)
	least = minimum_group_size()
	scores = {}
	for row in rows:
		if row.responses < least:
			scores[row.course_outcome] = {"responses": None, "average": None, "percent": None, "suppressed": 1}
		else:
			average = flt(row.average, 2)
			scores[row.course_outcome] = {"responses": row.responses, "average": average, "percent": flt(average / 5 * 100, 2), "suppressed": 0}
	return scores
