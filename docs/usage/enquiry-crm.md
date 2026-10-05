# Enquiry CRM (M04-05)

The public form `/admission-enquiry` creates a Lead, sends one WhatsApp acknowledgement and assigns the Lead
to an Admission Officer of the chosen college (round robin). "Convert to Applicant" (API
`campus.admissions.api.convert_lead_to_applicant`) creates the Student Applicant once and links both ways.

## Settings (Admission Settings, "Enquiry Acknowledgements")
- Acknowledge a number once per N hours (default 24; 0 turns the check off).
- Acknowledgements per college per hour (default 100; 0 turns it off). Past the ceiling the Lead is still saved
  and the Error Log gets one entry an hour.

## Deployment: client IP behind a proxy
The guest rate limit (10 enquiries per IP per hour) keys on `frappe.local.request_ip`. Behind nginx, a load
balancer or a CDN that value is the proxy's address unless the proxy forwards the real one, so every visitor
would share one limit. Make sure the proxy sets `X-Forwarded-For` (or `X-Real-IP`) and that Frappe's
request IP resolves to the real client address (check with a test request and the Error Log / `request_ip`
in a console) before opening the form to the public. The hidden honeypot field and the per-number and per-college
acknowledgement caps still apply regardless of the IP.

## Who sees which Leads
Leads are scoped by Company User Permissions. A Lead with no company is visible only to System Managers.
The round-robin rule of a college lists the enabled Admission Officers permitted for it and is refreshed
when their roles or Company User Permissions change.
