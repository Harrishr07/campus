"""M01-05 Seed Feedback Forms and the invitation / reminder Message Templates (install and migrate, never overwriting).

The official survey wording (NAAC Student Satisfaction Survey, university exit surveys) is not available, so every form is
a labelled placeholder with stand-in questions for the college to replace.
"""

import frappe

PLACEHOLDER = "Placeholder questions - replace with the official or the college's own wording."
AGREE = "Likert"


def likert(*questions):
	return [{"question": q, "question_type": AGREE} for q in questions]


def comments():
	return [{"question": "Any other comments or suggestions", "question_type": "Text", "is_required": 0}]


COURSE_EXIT = [
	{"question": f"The course helped me attain CO{n}: (outcome {n} of the course)", "question_type": AGREE, "course_outcome": f"CO{n}"}
	for n in range(1, 6)
] + comments()
CURRICULUM = [
	"The syllabus is relevant to current needs of industry and society",
	"The courses are well sequenced and balanced between theory and practice",
	"The electives offer enough choice",
	"The learning outcomes are clearly stated and achievable",
]
SEEDED_FORMS = {
	"Course Exit Survey": COURSE_EXIT,
	"Programme Exit Survey": likert(
		"The programme met its stated programme outcomes", "The programme prepared me for employment or higher studies",
		"The faculty were accessible and supportive", "The infrastructure and library met my needs",
	) + comments(),
	"Student Satisfaction Survey": likert(
		"The syllabus was covered in the classes", "Teachers prepared well for the classes", "Teachers communicated clearly",
		"Internal assessment was fair and timely", "The mentoring system helped me", "The institution encouraged co-curricular activities",
	) + [{"question": "How would you rate the teaching-learning process overall?", "question_type": "Choice", "options": "Excellent\nVery good\nGood\nFair\nPoor"}] + comments(),
	"Curriculum Feedback - Students": likert(*CURRICULUM) + comments(),
	"Curriculum Feedback - Teachers": likert(*CURRICULUM, "I had a say in designing or revising the syllabus") + comments(),
	"Curriculum Feedback - Employers": likert(
		"Graduates of the college have the skills our work needs", "The curriculum covers current industry practice",
		"Graduates communicate and work in teams well",
	) + comments(),
	"Curriculum Feedback - Alumni": likert(*CURRICULUM[:2], "The curriculum prepared me for my career") + comments(),
}  # fmt: skip
TEMPLATES = {
	"Feedback Invitation": (
		"Your feedback please: {{ doc.campaign_title }}",
		"You are invited to give feedback \"{{ doc.campaign_title }}\" by {{ frappe.format(doc.end_date, {'fieldtype': 'Date'}) }}."
		"{% if doc.is_anonymous %} Your answers are anonymous.{% endif %} Answer here: {{ context.link }}",
	),
	"Feedback Reminder": (
		"Reminder: {{ doc.campaign_title }}",
		"If you have not yet given your feedback \"{{ doc.campaign_title }}\", please do so by "
		"{{ frappe.format(doc.end_date, {'fieldtype': 'Date'}) }}: {{ context.link }} (please ignore this if you already have).",
	),
}
MINIMUM_GROUP_SIZE = 5  # the seeded default only; the college sets its own in Campus Settings


def setup_feedback():
	seed_feedback_forms()
	seed_feedback_templates()
	seed_minimum_group_size()


def seed_feedback_forms():
	for name, questions in SEEDED_FORMS.items():
		if frappe.db.exists("Feedback Form", name):
			continue
		frappe.get_doc(
			{"doctype": "Feedback Form", "form_name": name, "is_placeholder": 1, "description": PLACEHOLDER, "questions": questions}
		).insert(ignore_permissions=True)


def seed_feedback_templates():
	for event_key, (subject, body) in TEMPLATES.items():
		if frappe.db.exists("Message Template", event_key):
			continue
		frappe.get_doc(
			{
				"doctype": "Message Template", "event_key": event_key, "purpose": "transactional",
				"channels": [{"channel": "email"}], "bodies": [{"language": "en", "subject": subject, "body": body}],
			}
		).insert(ignore_permissions=True)  # fmt: skip


def seed_minimum_group_size():
	if not frappe.db.get_single_value("Campus Settings", "feedback_minimum_group_size"):
		frappe.db.set_single_value("Campus Settings", "feedback_minimum_group_size", MINIMUM_GROUP_SIZE)
