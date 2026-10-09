"""M06-06 Exam Rule Sets seeded before P2-T20 have no photocopy / revaluation window: set the seeded values. DML only."""

from campus.examinations.seed import fill_revaluation_rules


def execute():
	fill_revaluation_rules()
