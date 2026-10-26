"""M01-02 Seed structure of NAAC-AQAR-RAF2017 (criterion -> key indicator -> metric -> sub-metric, plus Extended Profile).

Codes and short titles follow the SXCCE AQAR 2023-24 (docs/research/naac-reference-notes.md). The official template is
not available, so every title is a placeholder and every node says so. Each node's parent is its code less the last
segment; Extended Profile nodes are roots coded EP-<number> so they do not clash with the key indicator of the same number.
"""

PLACEHOLDER = "placeholder - replace with official template"
PASS_PCT = "round(final_year_passed / final_year_appeared * 100, 2)"
FEEDBACK_CHOICES = "A. All 4 of the above\nB. Any 3 of the above\nC. Any 2 of the above\nD. Any 1 of the above\nE. None of the above"
NARRATIVE_WORDS = 500

CRITERIA = {
	"1": "Curricular Aspects",
	"2": "Teaching-Learning and Evaluation",
	"3": "Research, Innovations and Extension",
	"4": "Infrastructure and Learning Resources",
	"5": "Student Support and Progression",
	"6": "Governance, Leadership and Management",
	"7": "Institutional Values and Best Practices",
}
KEY_INDICATORS = {
	"1.1": "Curriculum Design and Development",
	"1.2": "Academic Flexibility",
	"1.3": "Curriculum Enrichment",
	"1.4": "Feedback System",
	"2.1": "Student Enrolment and Profile",
	"2.2": "Student Teacher Ratio",
	"2.3": "Teaching-Learning Process",
	"2.4": "Teacher Profile and Quality",
	"2.5": "Evaluation Process and Reforms",
	"2.6": "Student Performance and Learning Outcomes",
	"3.1": "Promotion of Research",
	"3.2": "Resource Mobilization for Research",
	"3.3": "Innovation Ecosystem",
	"3.4": "Research Publications and Awards",
	"3.5": "Consultancy",
	"3.6": "Extension Activities",
	"3.7": "Collaboration",
	"4.1": "Physical Facilities",
	"4.2": "Library as a Learning Resource",
	"4.3": "IT Infrastructure",
	"4.4": "Maintenance of Campus Infrastructure",
	"5.1": "Student Support",
	"5.2": "Student Progression",
	"5.3": "Student Participation and Activities",
	"5.4": "Alumni Engagement",
	"6.1": "Institutional Vision and Leadership",
	"6.2": "Strategy Development and Deployment",
	"6.3": "Faculty Empowerment Strategies",
	"6.4": "Financial Management and Resource Mobilization",
	"6.5": "Internal Quality Assurance System",
	"7.1": "Institutional Values and Social Responsibilities",
	"7.2": "Best Practices",
	"7.3": "Institutional Distinctiveness",
}
# code, title, answer type (N Number, P Percent, C Choice, T Narrative), unit; metrics other than the formula ones are answered by hand
METRICS = [
	("1.1.1", "Curriculum planning and delivery", "T", None),
	("1.1.2", "Programmes where syllabus was revised", "P", "%"),
	("1.1.3", "Courses on employability, entrepreneurship or skill development", "P", "%"),
	("1.2.1", "New courses introduced", "P", "%"),
	("1.2.2", "Programmes with CBCS or elective options", "P", "%"),
	("1.2.3", "Students in certificate or add-on programmes", "N", "students"),
	("1.3.1", "Cross-cutting issues in the curriculum", "T", None),
	("1.3.2", "Value-added courses offered", "N", "courses"),
	("1.3.3", "Students undertaking projects, field work or internships", "P", "%"),
	("1.4.1", "Structured feedback on the curriculum", "C", None),
	("1.4.2", "Feedback is analysed and communicated", "C", None),
	("2.1.1", "Students admitted", "N", "students"),
	("2.1.2", "Seats filled against seats reserved", "P", "%"),
	("2.2.1", "Learning levels of students assessed", "T", None),
	("2.2.2", "Student to full-time teacher ratio", "N", "ratio"),
	("2.3.1", "Student-centric teaching methods", "T", None),
	("2.3.2", "ICT-enabled teaching tools", "T", None),
	("2.3.3", "Mentor to mentee ratio", "N", "ratio"),
	("2.4.1", "Full-time teachers against sanctioned posts", "N", "teachers"),
	("2.4.2", "Full-time teachers with Ph.D.", "P", "%"),
	("2.4.3", "Teaching experience of full-time teachers", "N", "years"),
	("2.5.1", "Days from last exam to declaration of results", "N", "days"),
	("2.5.2", "Examination-related grievances", "P", "%"),
	("2.5.3", "IT integration and reforms in the evaluation process", "T", None),
	("2.6.1", "Programme and course outcomes", "T", None),
	("2.6.2", "Attainment of programme and course outcomes", "T", None),
	("2.6.3", "Pass percentage of final year students", "P", "%"),
	("3.1.1", "Research promotion policy", "T", None),
	("3.2.1", "Grants for research projects", "N", "INR lakhs"),
	("3.2.2", "Teachers with research projects", "N", "teachers"),
	("3.3.1", "Innovation ecosystem and incubation", "T", None),
	("3.3.2", "Workshops on research methodology, IPR and entrepreneurship", "N", "workshops"),
	("3.4.1", "Research ethics and plagiarism policy", "T", None),
	("3.4.3", "Research papers in UGC-CARE listed journals", "N", "papers"),
	("3.4.4", "Books and chapters published", "N", "publications"),
	("3.4.5", "Citations of research papers", "N", "citations"),
	("3.4.6", "h-index of research papers", "N", "h-index"),
	("3.5.1", "Revenue from consultancy", "N", "INR lakhs"),
	("3.6.1", "Extension activities and their impact", "T", None),
	("3.6.2", "Awards for extension activities", "N", "awards"),
	("3.7.1", "Collaborative activities and MoUs", "N", "activities"),
	("4.1.1", "Facilities for teaching-learning", "T", None),
	("4.1.2", "Facilities for sports, games and cultural activities", "T", None),
	("4.1.4", "Expenditure on infrastructure augmentation", "N", "INR lakhs"),
	("4.2.1", "Library automation", "T", None),
	("4.2.2", "Subscriptions to e-resources", "N", "INR lakhs"),
	("4.3.1", "IT facilities and Wi-Fi", "T", None),
	("4.3.2", "Student to computer ratio", "N", "ratio"),
	("4.4.1", "Expenditure on maintenance of infrastructure", "P", "%"),
	("5.1.1", "Students benefitting from government scholarships", "P", "%"),
	("5.1.2", "Students benefitting from institutional scholarships", "P", "%"),
	("5.1.3", "Capacity-building and skill-enhancement activities", "N", "activities"),
	("5.2.1", "Placement of outgoing students", "P", "%"),
	("5.2.2", "Students progressing to higher education", "P", "%"),
	("5.2.3", "Students qualifying in competitive exams", "N", "students"),
	("5.3.1", "Awards in sports and cultural activities", "N", "awards"),
	("5.4.1", "Alumni contribution", "N", "INR lakhs"),
	("6.1.1", "Vision and mission and their deployment", "T", None),
	("6.2.1", "Perspective and strategic plan", "T", None),
	("6.3.1", "Welfare measures for teaching and non-teaching staff", "T", None),
	("6.3.2", "Teachers given financial support for conferences", "N", "teachers"),
	("6.3.3", "Professional development programmes for staff", "N", "programmes"),
	("6.3.4", "Teachers attending FDPs", "N", "teachers"),
	("6.4.1", "Resource mobilization and financial audit", "T", None),
	("6.5.1", "IQAC structure and functioning", "T", None),
	("6.5.2", "Quality assurance initiatives", "T", None),
	("7.1.1", "Gender equity and sensitization", "T", None),
	("7.1.2", "Energy and environment initiatives", "T", None),
	("7.2.1", "Best practices", "T", None),
	("7.3.1", "Institutional distinctiveness", "T", None),
]  # fmt: skip
# data point formulas available today; every other metric is answered by hand
FORMULAS = {"2.1.1": "students_admitted", "2.6.3": PASS_PCT}
SUB_METRICS = [
	("2.1.1.1", "Students admitted in the year", "N", "students"),
	("2.5.1.1", "Days from last exam to declaration of results", "N", "days"),
	("2.6.3.1", "Final year students who passed", "N", "students"),
	("2.6.3.2", "Final year students who appeared", "N", "students"),
	("5.1.1.1", "Students receiving government scholarships", "N", "students"),
	("5.1.2.1", "Students receiving institutional scholarships", "N", "students"),
]
EXTENDED_PROFILE = [
	("1.1", "Programmes offered"), ("2.1", "Students"), ("2.2", "Final year students"), ("2.3", "Outgoing students"),
	("3.1", "Full-time teachers"), ("3.2", "Sanctioned posts"), ("3.3", "Teachers with Ph.D."),
	("4.1", "Classrooms and seminar halls"), ("4.2", "ICT-enabled classrooms"), ("4.3", "Computers"),
	("4.4", "Expenditure excluding salary"),
]  # fmt: skip
DEPARTMENT_WISE = {"2.1.1", "2.2.2", "2.4.1", "2.4.2", "2.6.3", "5.2.1"}
COE_METRICS = ("2.5.", "2.6.")
FILE_SLOTS = ("Data Template", "Any additional information")
ANSWER_TYPES = {"N": "Number", "P": "Percent", "C": "Choice", "T": "Narrative"}


def evidence_slots(*file_slots, url_slot=True):
	slots = [{"slot_name": name, "kind": "File"} for name in file_slots]
	return slots + ([{"slot_name": "Link to the relevant document", "kind": "URL"}] if url_slot else [])


def node(code, title, node_type, **values):
	return {"code": code, "title": title, "node_type": node_type, "description": PLACEHOLDER, **values}


def metric_node(code, title, answer, unit, node_type="Metric"):
	values = {"answer_type": ANSWER_TYPES[answer], "unit": unit, "owner_role": "IQAC Coordinator"}
	if answer == "T":
		values["word_limit"] = NARRATIVE_WORDS
	if answer == "C":
		values["choices"] = FEEDBACK_CHOICES
	if answer in "NP":
		values["period"] = "Academic Year" if code in FORMULAS else "Last 5 Years"
	if code.startswith(COE_METRICS):
		values["owner_role"] = "COE"
	if node_type == "Metric":
		values["evidence_slots"] = evidence_slots(*FILE_SLOTS)
		values["formula"] = FORMULAS.get(code)
	values["department_wise"] = int(code in DEPARTMENT_WISE)
	return node(code, title, node_type, **values)


def seed_nodes():
	"""Node specs in creation order (parents first); `parent` is a code within the framework."""
	specs = [node(code, title, "Criterion") for code, title in CRITERIA.items()]
	specs += [node(code, title, "Key Indicator") for code, title in KEY_INDICATORS.items()]
	specs += [metric_node(*row) for row in METRICS]
	specs += [metric_node(*row, node_type="Sub-Metric") for row in SUB_METRICS]
	for spec in specs:
		spec["parent"] = spec["code"].rpartition(".")[0] or None
	for code, title in EXTENDED_PROFILE:
		profile = node(f"EP-{code}", title, "Extended Profile", answer_type="Number", period="Academic Year")
		specs.append(
			{**profile, "parent": None, "evidence_slots": evidence_slots("Data Template", url_slot=False)}
		)
	return specs
