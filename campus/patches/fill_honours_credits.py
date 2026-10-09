"""M06-07 Classification Rules seeded before P2-T22 have no Honours / Minor credit requirement: set the seeded value
of their regulation (R2022 and R2026: 18). DML only."""

from campus.examinations.seed import fill_honours_credits


def execute():
	fill_honours_credits()
