"""M03-02, M03-03, M02 Seed values of the Curriculum Rule, Registration Rule and Attendance Rule of a regulation, keyed by
regulation code: one source for the demo data and the pilot setup kit (source: docs/research/anna-university-autonomous-rules.md,
section 3; unsourced values are listed under "Pending confirmation" in docs/rulings.md)."""

CREDIT_PER_PERIOD = {
	"lecture_credit_per_period": 1,
	"tutorial_credit_per_period": 1,
	"practical_credit_per_period": 0.5,
}
CREDIT_RANGE = {"min_total_credits": 165, "max_total_credits": 170}
REGISTRATION = {
	"max_credits_per_semester": 36, "excluded_types": "Arrear\nDropped", "max_drop_credits": 6, "drop_window_days": 30,
	"add_from_semester": 5, "max_add_credits": 6, "max_add_courses": 2, "elective_min_enrolment": 10,
}  # fmt: skip
HONOURS = {"honours_min_cgpa": 7.5, "honours_cgpa_upto_semester": 3, "honours_no_arrears": 1}

RULES = {
	"R2022": {
		"curriculum_rule": {**CREDIT_PER_PERIOD, **CREDIT_RANGE},
		"registration_rule": {**REGISTRATION, **HONOURS},
		"attendance_rule": {
			"formula": "sum_based", "overall_min_pct": 75, "medical_band_min_pct": 65, "per_course_min_pct": 0,
			"od_counts": 1, "medical_counts": 1, "condonation_fee": 500,
		},
	},
}  # fmt: skip
