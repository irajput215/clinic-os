# SMS: blocked on vendor decision D7a

Reminders by SMS, the "with the doctor" message and a patient-portal OTP all send a mobile number and
message text to a third party, which needs an approved vendor, a data-flow record and an Australian
processing position first ([`../../decisions-needed.md`](../../decisions-needed.md) D7a). Nothing here
is planned in detail until D7a is answered; the email flow (D-009) covers reminders until then.

When D7a is answered, this folder gets the five docs3 files, and the integration follows the FEAT-13
adapter contract (one interface, a simulated driver for CI, no real send from a test).
