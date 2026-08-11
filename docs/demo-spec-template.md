# Demo Confluence spec: Patient Appointment Scheduling

Paste this into a new page in the `SD` space
(https://neurealm-team-juadifpx.atlassian.net/wiki/spaces/SD/overview).
Confluence's editor will reformat headings/lists automatically if you paste
as plain text, or you can type it directly using the editor's own
heading/list tools.

After creating the page, grab its **page ID** from the URL —
`.../wiki/spaces/SD/pages/<PAGE_ID>/<title-slug>` — that's the value to
paste into http://localhost:8000/ui/simulate (or the `page.id` field if
you're using the webhook curl payload directly).

---

## Page content (v1 — baseline, matches what's already built)

```
Title: Patient Appointment Scheduling — Feature Spec

Overview
Patients can browse providers and book an appointment at a specific date
and time. Patients can cancel their own upcoming appointments. A provider
cannot be double-booked for the same time slot while an appointment against
it is active.

User Stories
- As a patient, I can view a list of providers and their specialties.
- As a patient, I can book an appointment with a provider for a given date
  and time, optionally including a reason for the visit.
- As a patient, I can view my own upcoming and past appointments.
- As a patient, I can cancel an appointment I booked.
- As the system, I must prevent two active appointments from being booked
  against the same provider at the same time.

Business Rules
- An appointment's status is one of: scheduled, completed, cancelled.
- Only appointments with status "scheduled" count toward the
  double-booking check — a cancelled slot can be rebooked.
- Patients may only cancel their own appointments.

Out of Scope (for now)
- Provider-side scheduling / availability windows.
- Email or SMS reminders.
- Rescheduling (patients must cancel and rebook).
```

---

## Suggested v2 edit (to trigger the demo pipeline)

Once the page above exists and `care-scheduler` is pushed, edit the page in
Confluence to add one of these under **User Stories** (pick one — each maps
to a clean, boundable code change):

**Option A — cancellation reason (smallest diff):**
```
- As a patient, when I cancel an appointment, I must provide a short reason,
  which is stored on the appointment and shown to staff in the admin.
```

**Option B — daily appointment cap per provider:**
```
- As the system, I must prevent a provider from being booked for more than
  8 scheduled appointments on the same calendar day.
```

**Option C — reminder flag (schema-only, no email sending required):**
```
- As the system, I must track whether a 24-hour reminder has been sent for
  each scheduled appointment (a boolean field is enough for now — actual
  email delivery is out of scope).
```

Save the page, note its new version number in Confluence's page history,
then fire the webhook curl (see confluence-to-pr-agent/SETUP.md) with that
page's ID.
