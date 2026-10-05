# NAAC reference notes (from SXCCE documents)

Sources (PDFs not committed; download from the SXCCE NAAC page): AQAR-Final.pdf (SXCCE AQAR 2023-24, 128 pages), SXCCESSR.pdf (SXCCE SSR Cycle 1, March 2017, 326 pages),
https://www.sxcce.edu.in/web2/IQAC/naac.php, NAAC MBGL presentation (AKS University, Dec 2025).

## Institution profile (design-partner shape)
- St. Xavier's Catholic College of Engineering, Nagercoil, TN. Self-financing, co-ed, rural.
- Affiliated to Anna University; Autonomous since 26/05/2022.
- NAAC: Cycle 1 A (3.02, 2017-2022), Cycle 2 A (3.02, valid to 31/12/2027). Also NBA.
- AQAR 2023-24 extended profile: 16 programmes, 2327 students, 622 final-year, 675 courses,
  161 full-time teachers, 72 classrooms/seminar halls, 1031 computers, INR 747.54 lakh non-salary spend.

## Framework versions seen
| Document | Framework | Numbering |
|---|---|---|
| SSR 2017 | Pre-RAF, question-based (e.g. 1.1.1 "State the vision...") | Mostly narrative, plus 35-item department evaluative report per department |
| AQAR 2023-24 | RAF 2017 revised (7 criteria) | Metric IDs like 2.6.3, sub-metric 2.6.3.1 |
| Next cycle (after 2027) | Binary + MBGL, DCF 2025 (announced 10 Feb 2025) | Official metric list not finalised as of the Dec 2025 source |

Same college, three different formats in about 10 years, so metric definitions must be versioned data.

## AQAR structure
- Part A: institution data, IQAC composition, IQAC meetings count, NEP items (multidisciplinary, ABC, skill, IKS, OBE, online).
- Extended Profile: base counts (1.1, 2.1-2.3, 3.1-3.3, 4.1-4.4) reused as denominators.
- Part B: 7 criteria -> key indicators (e.g. 2.5) -> metrics (2.5.1) -> sub-metric inputs (2.5.1.1).

Metric answer types:
1. Quantitative number (e.g. 2.5.1 days to result = 16).
2. Option choice (e.g. 1.4.1 "A. All 4 of the above").
3. Qualitative narrative (word-limited text, e.g. 2.5.3, 2.6.2).
4. Every metric has named evidence slots ("Data Template", "Any additional information") plus URL fields.

## Metrics computable from operational modules (examples)
| Metric | Source module |
|---|---|
| 2.1.1 students admitted; 2.1.2 reserved seats filled | M04 Admissions |
| 2.2.2 student-teacher ratio; 2.3.3 mentor ratio | M05 + M07 |
| 2.4.1-2.4.3 faculty vs sanctioned posts, PhD, experience | M07 / HRMS Employee |
| 2.5.1 days exam end to result; 2.5.2 evaluation grievances; 2.6.3 pass % | M06 COE |
| 2.6.2 CO/PO attainment | M03 OBE |
| 3.2.1 grants; 3.2.2 teachers with projects; 3.5.1 consultancy revenue | M08 + ERPNext GL |
| 3.4.3 CARE papers; 3.4.5/3.4.6 citations, h-index | M08 publications |
| 4.1.4 / 4.4.1 expenditure | ERPNext accounts (cost centre / account mapping) |
| 5.1.1 / 5.1.2 scholarships | M05-05 |
| 5.2.1 placement; 5.2.2 higher studies; 5.2.3 competitive exams | M14 |
| 6.3.2-6.3.4 faculty support, FDPs | HRMS Training Event / M07-05 |

## SXCCE OBE rule (example of config, not a universal rule)
- CO attainment = 80% direct + 20% indirect (course exit survey).
- Direct (theory) = 60% end-semester exam + 40% continuous assessment.
- PO/PSO attainment = CO attainment via CO-PO mapping (direct) + programme exit survey (indirect).
- Targets set before each academic year.

## COE observations (AQAR 2.5.3)
- In-house system for CIA, separate software for end-semester exams. That's a replacement target.
- Question bank is tagged by CO and cognitive (Bloom's) level.

## Public disclosure
The website lists SSR, AQARs 2017-2024, IQAC minutes, academic calendars, a 10-year strategic plan,
annual benchmarks, COE annual reports and best practices. AQAR asks for URLs to these. The product
should publish evidence to stable public URLs.
