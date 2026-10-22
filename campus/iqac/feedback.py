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
from contextlib import suppress
from datetime import datetime, time

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, today
from frappe.utils.password import get_encryption_key

from campus.campus_messaging.api import audience_members, recipient_keys_for_user

RESPONSE, TOKEN, ANSWER = "Feedback Response", "Feedback Response Token", "Feedback Answer"
EXTERNAL = ("Alumni", "Employers")
LIKERT = range(1, 6)
TEXT_LIMIT = 2000
ANONYMOUS_OWNER = "Guest"
SAVEPOINT = "feedback_response"
CO_AUDIENCE = "Course Offering Students"
USER_FIELDS = {"Student": "user", "Guardian": "user", "Employee": "user_id"}  # the login a key belongs to
MINIMUM_GROUP_FLOOR = 3
MINIMUM_GROUP_DEFAULT = 5  # a blank Campus Settings value means this
REQUEST_FIELDS = ("campaign", "answers", "member", "signature")


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


def not_available():
	"""The one refusal for an unknown campaign, a bad link and a caller the campaign does not address."""
	frappe.throw(_("This feedback is not available to you."), frappe.PermissionError)


def respondent_keys(campaign, addressed, member=None, signature=None):
	"""Every key the caller answers as among `addressed`: an invited member by a valid signed link, else each record of
	the session user (all are claimed, so nobody answers again under another of their records)."""
	if member or signature:
		key = f"External Member:{member}"
		if campaign.audience not in EXTERNAL or key not in addressed or not valid_signature(campaign.name, key, signature):
			not_available()
		return [key]
	matches = sorted(recipient_keys_for_user(frappe.session.user) & set(addressed))
	if not matches:
		not_available()
	return matches


def check_audience_size(campaign, addressed):
	"""An anonymous campaign addressing fewer people than the minimum group size could be traced through the offering
	and instructor its responses keep, so it takes no answers or invitations."""
	least = minimum_group_size()
	if too_small(campaign, addressed):
		frappe.throw(
			_("The audience of this anonymous campaign is too small (fewer than {0}) to keep answers anonymous. Widen the audience or make the campaign named.").format(least)
		)


def too_small(campaign, addressed):
	"""True for an anonymous campaign addressing fewer people than the minimum group size."""
	return bool(cint(campaign.is_anonymous)) and audience_size(addressed) < minimum_group_size()


def audience_size(keys):
	"""How many people `keys` address: a person's Student / Guardian / Employee record and their login count once."""
	by_doctype = {}
	for key in set(keys):
		doctype, _sep, name = key.partition(":")
		by_doctype.setdefault(doctype, set()).add(name)
	people = set()
	for doctype, names in by_doctype.items():
		users = login_of(doctype, names)
		people.update(f"User:{users[name]}" if users.get(name) else f"{doctype}:{name}" for name in names)
	return len(people)


def login_of(doctype, names):
	"""{record name: user} for records of `doctype` that have a login (External Members have none)."""
	if doctype == "User":
		return {name: name for name in names}
	field = USER_FIELDS.get(doctype)
	if not field:
		return {}
	return dict(frappe.get_all(doctype, {"name": ["in", list(names)], field: ["is", "set"]}, ["name", field], as_list=True))


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
		addressed = respondents(campaign)
		mine = sorted(keys & set(addressed))
		if mine and not too_small(campaign, addressed) and not any(has_responded(campaign.name, key) for key in mine):
			result.append(frappe._dict(name=campaign.name, campaign_title=campaign.campaign_title, end_date=campaign.end_date))
	return result


# Recording a response


@frappe.whitelist(allow_guest=True, methods=["POST"])
def submit_response(campaign=None, answers=None, member=None, signature=None):
	"""Record the caller's answers ({question row name: value}, JSON) to an open campaign, once per respondent.

	Nothing but a ValidationError / PermissionError leaves this function, so no request error snapshot (which holds the
	frames' locals: the answers and the respondent) is ever taken. A refusal names no answer. Any other failure, even
	one whose rollback or Error Log write fails too, is undone, logged by its class name only and reported as one generic
	ValidationError raised outside the handler, so no exception chain carries it either. Missing arguments default to
	None and are refused inside, never as a TypeError before the fields are taken out.

	The posted fields are taken out of frappe.form_dict first: Frappe copies form_dict and the session user into the
	metadata of every Error Log and request error snapshot, so nothing logged later in this request may see them."""
	for field in REQUEST_FIELDS:
		frappe.form_dict.pop(field, None)
	failed = None
	try:
		frappe.db.savepoint(SAVEPOINT)
		return record_response(campaign, answers, member, signature)
	except (frappe.ValidationError, frappe.PermissionError):
		undo_attempt()  # e.g. a second key already claimed: nothing of this attempt stays
		raise
	except Exception as error:
		failed = type(error).__name__
		undo_attempt()
	with suppress(Exception):
		log_failure(failed)
	frappe.throw(_("Your feedback could not be recorded. Please try again later."))


def undo_attempt():
	"""Roll back to the savepoint or, if that fails (deadlock, lost connection, no savepoint), the whole transaction;
	never raises."""
	try:
		frappe.db.rollback(save_point=SAVEPOINT)
	except Exception:
		with suppress(Exception):
			frappe.db.rollback()


def log_failure(error_class):
	"""An Error Log row naming the failure's class only, with empty metadata (log_error would add the request and user),
	owner "Guest" and the day's midnight, so neither its owner nor its time marks the respondent."""
	log = frappe.new_doc("Error Log")
	log.update({"name": frappe.generate_hash(length=16), "method": _("Feedback response failed"), "error": error_class, "metadata": "{}"})
	stamp(log, midnight(today()), ANONYMOUS_OWNER)
	log.db_insert()


def record_response(name, answers, member, signature):
	if frappe.session.user == "Guest" and not (member or signature):
		frappe.throw(_("Please log in to give feedback."), frappe.PermissionError)
	if not (isinstance(name, str) and frappe.db.exists("Feedback Campaign", name)):
		not_available()
	campaign = frappe.get_doc("Feedback Campaign", name)  # respondents cannot read campaigns; checked next
	addressed = respondents(campaign)
	keys = respondent_keys(campaign, addressed, member, signature)
	check_audience_size(campaign, addressed)
	if not is_open(campaign):
		frappe.throw(_("This feedback is not open."))
	rows = answer_rows(frappe.get_doc("Feedback Form", campaign.form), answers)
	for key in keys:
		claim_token(campaign, key)
	return store_response(campaign, keys[0], rows)


def answer_rows(form, answers):
	"""Answer rows for the form's questions, checked: Likert 1-5, a listed option, text within the limit, required answered."""
	from campus.iqac.doctype.feedback_form.feedback_form import choice_options

	try:
		values = json.loads(answers) if isinstance(answers, str) else answers
	except ValueError:
		values = None
	if not isinstance(values, dict):
		frappe.throw(_("The answers are not in the expected form."))
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
	"""Smallest group a report or score may show (Campus Settings; blank means MINIMUM_GROUP_DEFAULT); never below
	MINIMUM_GROUP_FLOOR."""
	value = cint(frappe.db.get_single_value("Campus Settings", "feedback_minimum_group_size")) or MINIMUM_GROUP_DEFAULT
	return max(value, MINIMUM_GROUP_FLOOR)


def indirect_co_scores(offering):
	"""{CO: {responses, average, percent, suppressed}} from the CO-tagged Likert answers to the offering's closed
	"Course Offering Students" campaigns.

	Each (campaign, CO) cell answered by fewer respondents than the minimum group size is dropped before the cells are
	pooled, so no small campaign shows by difference. average is the mean rating (1-5), percent that mean as a share of
	5; a CO with no cell left is suppressed (figures None)."""
	least = minimum_group_size()
	scores = {}
	for co, cells in co_cells(offering).items():
		kept = [cell for cell in cells if cell.responses >= least]
		if not kept:
			scores[co] = {"responses": None, "average": None, "percent": None, "suppressed": 1}
			continue
		average = flt(sum(c.total for c in kept) / sum(c.ratings for c in kept), 2)
		scores[co] = {"responses": sum(c.responses for c in kept), "average": average, "percent": flt(average / 5 * 100, 2), "suppressed": 0}
	return scores


def co_cells(offering):
	"""{CO: [(campaign, responses, ratings, total)]} for the offering's closed student campaigns, from the ratings of
	(campaign, question) cells with at least the minimum group size only: a CO tagged on an optional question answered by
	a few would otherwise show them as the difference between the CO and its other questions."""
	campaign, response, answer = frappe.qb.DocType("Feedback Campaign"), frappe.qb.DocType(RESPONSE), frappe.qb.DocType(ANSWER)
	ratings = (
		frappe.qb.from_(response)
		.join(campaign)
		.on(campaign.name == response.campaign)
		.join(answer)
		.on((answer.parent == response.name) & (answer.parenttype == RESPONSE))
		.select(answer.course_outcome, response.campaign, answer.question_row, response.name.as_("response"), answer.rating)
		.where((response.course_offering == offering) & (campaign.audience == CO_AUDIENCE) & (campaign.end_date < today()))
		.where((answer.question_type == "Likert") & answer.rating.isnotnull())
		.where(answer.course_outcome.isnotnull() & (answer.course_outcome != ""))
		.run(as_dict=True)
	)  # fmt: skip
	pooled = {}
	for item in large_question_answers(ratings, minimum_group_size())[0]:
		cell = pooled.setdefault((item.course_outcome, item.campaign), frappe._dict(campaign=item.campaign, responses=set(), ratings=0, total=0))
		cell.responses.add(item.response)
		cell.ratings += 1
		cell.total += item.rating
	cells = {item.course_outcome: [] for item in ratings}  # a CO left with no cell shows as suppressed
	for (co, _campaign), cell in pooled.items():
		cells.setdefault(co, []).append(frappe._dict(cell, responses=len(cell.responses)))
	return cells


def large_question_answers(items, least):
	"""The answers among `items` (each with campaign, question_row, response) whose (campaign, question row) was
	answered by at least `least` responses, and how many (campaign, question) cells were dropped."""
	answered = {}
	for item in items:
		answered.setdefault((item.campaign, item.question_row), set()).add(item.response)
	kept = [item for item in items if len(answered[(item.campaign, item.question_row)]) >= least]
	return kept, sum(1 for responses in answered.values() if len(responses) < least)
