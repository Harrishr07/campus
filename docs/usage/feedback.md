# Feedback (P3-T07, M01-05, M03-03, M07-04)

## Forms and campaigns

1. **Feedback Form** (IQAC > Feedback): the questions. Each question is one of three types:
   - **Likert**: a rating from 1 (strongly disagree) to 5 (strongly agree);
   - **Choice**: one option, listed one per line;
   - **Text**.

   A Likert question can carry a **CO** tag (CO1, CO2, ...), the same tags used on CIA questions. Set-up seeds placeholder forms for you to reword: Course Exit Survey (CO1-CO5), Programme Exit Survey, Student Satisfaction Survey, and Curriculum Feedback for Students, Teachers, Employers and Alumni.
2. **Feedback Campaign**: set the form, the college, the **Audience**, the window (**Opens On** / **Closes On**), **Anonymous** (on by default) and **Remind Every (Days)**.
   - **Course Offering Students**, **Parents** and **Teachers**: the students, their guardians, or the instructors of the **Course Offering** (a course Student Group). You can also pick a messaging **Audience Rule** of the college instead.
   - **Students**: needs an Audience Rule or a course offering.
   - **Alumni** and **Employers**: list them as **Invitees** (External Members). Each gets a signed link and needs no login.

   Once a response exists, the form, audience, offering, instructor, college and anonymity can't change.
3. **Send Invitations** (button) sends the `Feedback Invitation` message to everyone the campaign addresses, through the bulk runner. Reminders (`Feedback Reminder`) go out every N days after the opening, until the window closes. They go to everyone addressed, including people who have already answered (see Anonymity). Edit the wording in Message Template.
4. Students and parents see open campaigns under **Feedback** in /campus-portal. Everyone answers at `/feedback/<campaign>`.
5. **Action Taken** and **Action Taken Report** on the campaign record what the college did. Feedback Campaign is listed under Evidence Sources in Campus Settings, with the report as its file, so **Attach as Evidence** works for NAAC 1.4.

## Anonymity

In an anonymous campaign, a **Feedback Response** keeps:
- the campaign, the form, the offering and instructor (copied from the campaign);
- the day (no time);
- the answers.

It keeps no user, owner, respondent record or IP. It is written by a plain insert, so there is no Version, document follow, comment or notification. Its owner is "Guest" and its times are midnight of the day.

One response per respondent is enforced by **Feedback Response Token**:
- its name is a keyed hash (the site's encryption key) of campaign and respondent;
- its owner is "Guest" and its times are the campaign's opening day;
- it keeps nothing else, so it can't be matched to a response.

Only System Manager can open single responses or tokens. Staff see the analysis.

Reminders go to everyone addressed so that the Message Log never shows, day by day, who has answered.

A **named** (not anonymous) campaign also stores the respondent on the response.

## Analysis

**Feedback Analysis** (report; IQAC Coordinator, System Manager, Principal) groups by **Question**, **Course** (offering) or **Faculty** (the campaign's instructor) and shows the response count and average rating:
- per question, the 1-5 distribution, or the counts of each choice;
- free-text answers are counted but never listed.

Only campaigns of the colleges you are permitted for are counted. A group with fewer responses than **Campus Settings > Feedback Minimum Group Size** (seeded 5) is not shown, and the report says how many groups were hidden.

`campus.iqac.api.indirect_co_scores(offering)` returns the indirect CO attainment of an offering: `{CO: {responses, average, percent, suppressed}}` from its CO-tagged Likert answers. **percent** is the mean rating as a share of 5. A CO with fewer responses than the minimum group size is suppressed and its figures are None.

## Deferred

- Self-appraisal "Student Feedback" quantity (campus.faculty.self_appraisal.phase3_quantity), and NAAC 1.4.1 / 1.4.2 data points from campaigns.
- Listing free-text comments to staff, and checks against differencing (overlapping filters that each pass the minimum).
- Message Log keeps the rendered invitation, including an invitee's signed link. A user who can read Message Log could answer for that invitee once.
- Database server logs (binary / general log) and backups are outside the app's control: insert order there is not anonymised.
