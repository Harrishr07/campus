# Anna University autonomous college rules (research, 4 Oct 2026)

Sources:
- UGC (Conferment of Autonomous Status upon Colleges ...) Regulations 2022/2023: https://www.ugc.gov.in/pdfnews/1392932_Autonomous-Regulations-on-10oct22.pdf
- SXCCE regulations page: https://www.sxcce.edu.in/web2/academics/regulations.php
  - SXCCE UG R2022 (amendments 1-3 incorporated)
  - SXCCE UG R2026
  - Anna University UG R2021 (affiliated colleges), which SXCCE followed before autonomy

## 1. Who does what

| Item | Issued/decided by | Evidence |
|---|---|---|
| Syllabus, regulations, exams, results | Autonomous college (BoS → Academic Council) | UGC 2023 cl. 3; R2022 cl. 21 |
| Mark sheets / grade sheets / consolidated grade sheet | College (COE) | UGC cl. 3.4 "announce results, issue mark sheets, and other certificates" |
| **Degree** | **Affiliating university**, with the college name on the certificate | UGC cl. 3.4; R2022 cl. 16.1(VII) and R2026 cl. 22.2 "award of degree approved by the Syndicate" |
| Provisional certificate | Varies (university for its own colleges; college COE for many autonomous colleges) | Keep as a setting |

Product setting: `degree_awarding_body` = University (default) / College, plus `provisional_certificate_issuer`.
The college always produces the convocation list and degree data for the university.

## 2. Statutory bodies (UGC 2023 cl. 12)

| Body | Chair | Term | Min meetings | Quorum / notes |
|---|---|---|---|---|
| Governing Body | Head of parent body (self-financing) | 5 years | Every 6 months | ≥50% members **and** university nominee present |
| Academic Council | Principal | Nominated members 3 years | Every 6 months | 3 university nominees (≥ Professor); faculty member secretary |
| Board of Studies | HOD | Nominated members 3 years | Every 6 months | All department faculty + experts + alumni nominee |
| Finance Committee | Principal | 3 years | Every 6 months | Finance officer is member secretary |

Non-statutory committees named: Planning & Evaluation, Grievance Redressal, Examination, Admission,
Library, Student Welfare, ICC, Extra-curricular, Academic Audit.
Also from R2022: Class Committee (per class, ≥4 student reps, first meeting within week 1, minutes in 2 days),
Course Committee (common courses), Disciplinary Committee, Project Review Committee.

## 3. Rule matrix: same college, three regulations

| Rule | AU R2021 (affiliated) | SXCCE R2022 | SXCCE R2026 |
|---|---|---|---|
| Total credits | per curriculum | 165-170 + 20 extra activity credits (15 LES) | per curriculum |
| Max duration | 14 sem (HSC), 12 (LES) | 14 / 12 | per cl. 5.2 |
| Max credits / semester | 36 (excl. RA/W) | 36 (excl. U/WD), drop ≤6 credits within 30 days, add ≤6 credits/2 courses (sem V-VIII) | similar |
| Attendance | ≥75% overall; 65-74% with medical/sports; <65% repeat semester | same as R2021 (overall = attended / (periods per week × 15)) | **≥80% overall** (average of course %), **≥70%** with medical, and **≥75% in each course**; attendance gives up to 5 CIA marks in bands 80-85 / 86-90 / 91-95 / >95 |
| CIA : ESE, theory | 40 : 60 | 40 : 60 (2 assessments × 100 → 40; each = 40 assignment + 60 test) | 40 : 60 |
| CIA : ESE, theory with lab | - | 50 : 50 (split by L-T-P pattern) | 50 : 50 |
| CIA : ESE, lab | 60 : 40 | 60 : 40 (75 observation/record + 25 test) | 60 : 40 |
| CIA : ESE, project | 40 : 60 | 60 : 40 (3 reviews 20 each; report 10, viva 30) | 60 : 40 (reviews 25/25/50%) |
| Pass rule | ESE ≥45% and total ≥50% | same; **3rd attempt onwards: ESE ≥50% alone**; CIA retained from first attempt | ESE ≥45% and total ≥50% |
| Internal-only courses | 50% of CIA | 50% of CIA | similar |
| Grade letters | O 10, A+ 9, A 8, B+ 7, B 6, C 5, U 0 | O 10 (91-100), A+ 9 (81-90), A 8 (71-80), B+ 7 (61-70), B 6 (56-60), C 5 (50-55), U, SA, WD | **S 10** (91-100), A+ 9 (81-90), A 8 (71-80), B+ 7 (66-70), **B 6.5** (61-65), **C+ 6** (56-60), C 5 (50-55), U, SA, **WC** |
| Grading method | absolute | **relative (Box-Cox normalisation) if passed students > 30**, else absolute; labs/projects always absolute | **absolute for all** |
| NPTEL/online grading | - | mapped table | separate ranges (S 91-100 … C 40-45, U <40) |
| GPA/CGPA | Σ(C×GP)/ΣC | Σ(C×GP)/ΣC over **passed** courses; U excluded; additional courses excluded unless Honours/Minor completed | same idea, 2 decimals |
| % conversion | - | CGPA × 10 | CGPA × 10 |
| First class with distinction | CGPA ≥8.5, first appearance | CGPA ≥8.5, all passed first appearance within 5 yrs (4 LES), no SA, withdrawal not an attempt | CGPA ≥8.5, first appearance; Honours variant |
| First class | CGPA ≥6.5 | CGPA ≥6.5 within 5 yrs (Honours ≥7.5) | similar |
| Honours / Minor | CGPA ≥7.5 at sem IV | +18 credits; eligibility CGPA ≥7.5 up to sem III, no arrears (Honours) | +additional courses |
| Revaluation | theory only | photocopy → faculty justification → revaluation → review; not for lab/EEC | similar |
| Withdrawal | yes | once in programme, within 10 days of exam, not counted as attempt | WC code |
| Break of study | yes | max 1 year (+1 exceptional), rejoin under regulation in force, bridge courses | similar |

## 4. Design consequences

1. Grade scheme is **per regulation**: letters, grade points (6.5 is valid, so use Float) and mark ranges all change.
2. Grading **method** must be pluggable: `absolute`, `relative_boxcox` (with min cohort size 30, passed-only input),
   plus a separate table for online/NPTEL courses.
3. Pass rule needs **attempt-aware** clauses (3rd attempt: ESE ≥50% alone) and **CIA carry-forward** across attempts.
4. Attendance rule needs: overall formula (sum-based vs average-of-courses), per-course minimum, medical band,
   and **attendance marks bands** feeding CIA.
5. CIA composition differs by course type and by L-T-P pattern (theory-with-lab table), so it is a template per regulation + course type.
6. Result codes are data: SA, U, WD/WC, AB, RA.
7. Classification rules are data: CGPA threshold, first-appearance requirement, max years, break-of-study inclusion, Honours/Minor variants.
8. Students rejoining after a break move to the regulation in force, with bridge courses. Support regulation change per student with history.
9. Extra Activity Credits (R2022 Annexure 1: 47 activity types, 20 credits required) map to Co-curricular Credit Records with an activity-credit master.
10. The degree is awarded by the university Syndicate: generate the convocation/degree list export and keep the degree certificate print behind the `degree_awarding_body` setting.
