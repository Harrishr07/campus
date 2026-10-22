"""M05-03 R2022 Classification Rules seeded before P2-T12 fix 1 have no lateral-entry limit on their distinction
rows: set it to 4 years (P2-T19 carried ruling). DML only."""

from campus.examinations.seed import fill_lateral_distinction_years


def execute():
	fill_lateral_distinction_years()
