"""Synthetic policy documents for the demo corpus."""

DOCS: list[tuple[str, str]] = [
    (
        "parental-leave.md",
        """# Parental Leave Policy

## Eligibility
All employees are eligible for paid parental leave from their first day. This
covers the birth or adoption of a child and applies equally to all parents,
regardless of gender or family structure.

## Duration
Employees receive 16 weeks of fully paid leave. This may be taken in a single
block or split into two blocks within the first 12 months after the child
arrives. Additional unpaid leave up to 12 weeks is available on request.

## How to request
Notify your manager and the People team at least 8 weeks before the expected
start date where possible. Submit the request in the HR portal and set an
out-of-office plan covering your projects and any on-call shifts.

## Returning to work
A phased return of 4 weeks at reduced hours with full pay is available. Contact
your People partner to arrange a return plan.
""",
    ),
    (
        "remote-work.md",
        """# Remote Work Policy

## Overview
We are a remote-first company. Employees may work from anywhere within their
country of employment, subject to tax and compliance approval.

## Core hours
Teams agree on core collaboration hours, typically 10:00 to 15:00 in the team's
primary time zone. Outside core hours, work when it suits you.

## Home office
You are expected to maintain a quiet, secure workspace with a reliable internet
connection. Equipment is provided through the equipment request process.

## Communication
Keep your calendar and chat status current. Respond to messages within one
working day unless on leave.
""",
    ),
    (
        "expenses.md",
        """# Expense Policy

## Principles
Spend company money as if it were your own. Only expenses that are reasonable,
necessary, and business-related are reimbursable.

## Categories
Reimbursable categories include travel, meals during business travel, client
entertainment, and pre-approved training. Hardware must go through the
equipment request process, not personal reimbursement.

## Limits
Meals during travel are capped at $60 per day. Any single expense over $500
requires manager approval in advance.

## Submission
Submit expenses within 30 days through the expense tool, with receipts attached.
Late submissions require VP approval.
""",
    ),
    (
        "paid-time-off.md",
        """# Paid Time Off Policy

## Allowance
All employees receive 25 days of paid time off per year, accrued monthly. Up to
5 days may carry over into the next year.

## Sick leave
Sick leave is separate and uncapped within reason. You do not need a doctor's
note for absences under 5 consecutive days.

## Public holidays
Local public holidays are automatically added to your calendar based on your
country of employment.

## Requesting leave
Request time off in the HR portal at least 2 weeks in advance for planned leave.
Notify your manager and team in chat for unexpected absences.
""",
    ),
    (
        "benefits-overview.md",
        """# Benefits Overview

## Health
We provide medical, dental, and vision coverage. Premiums are 100% employer-paid
for employees and 50% for dependents.

## Retirement
We match retirement contributions up to 4% of salary.

## Learning
Every employee has a $1,500 annual learning budget for courses, books, and
conferences.

## Wellness
A monthly $100 wellness stipend covers gym memberships, mental health apps, and
fitness equipment.

## Parental and family
See the parental leave policy for details on family leave.
""",
    ),
    (
        "code-of-conduct.md",
        """# Code of Conduct

## Our commitment
We are committed to a respectful, inclusive workplace free of harassment and
discrimination.

## Expected behavior
Treat colleagues with respect, assume good intent, and give feedback directly
and kindly. Protect confidential information.

## Reporting concerns
Report concerns to your manager, any People team member, or the anonymous
reporting channel. Retaliation against reporters is prohibited and treated as a
serious violation.

## Enforcement
Violations are reviewed by the People team and may result in disciplinary action
up to and including termination.
""",
    ),
    (
        "security-policy.md",
        """# Information Security Policy

## Devices
All company devices must have full-disk encryption, screen lock, and the
endpoint security agent installed. Do not install unapproved software.

## Accounts
Use a password manager for all credentials. Enable multi-factor authentication
on every account that supports it. Never share credentials.

## Data handling
Classify data as public, internal, confidential, or restricted. Do not store
restricted data on personal devices or unapproved cloud services.

## Reporting incidents
Report lost devices, suspected compromise, or phishing attempts to the security
team immediately via the incident channel.
""",
    ),
    (
        "equipment-policy.md",
        """# Equipment Policy

## Standard issue
New hires receive a laptop, monitor, keyboard, mouse, and headset. Engineers may
request a higher-specification machine via their manager.

## Requesting equipment
Submit requests through the equipment request runbook. Standard items ship
within 3 business days.

## Returns and offboarding
All equipment must be returned on your last day. Damaged or lost equipment must
be reported to IT.

## Personal use
Limited personal use of company devices is allowed provided it does not
interfere with security or performance.
""",
    ),
    (
        "travel-policy.md",
        """# Travel Policy

## Booking
Book flights and hotels through the corporate travel platform. Economy class
for flights under 6 hours; premium economy for longer international flights.

## Accommodation
Hotel budget is $250 per night. Prefer locations close to the meeting venue.

## Offsites
Quarterly team offsites are fully covered. Coordinate with your manager and the
People team for logistics.

## Reimbursement
Use the expense policy for incidental travel costs such as ground transport and
meals.
""",
    ),
    (
        "performance-reviews.md",
        """# Performance Review Process

## Cadence
We run two review cycles per year: a mid-year check-in and an end-of-year review.

## Self-review
Write a self-review covering your impact, strengths, and growth areas. Link
concrete work where possible.

## Manager review
Your manager adds calibration feedback and shares a summary before the
compensation conversation.

## Calibration
Managers calibrate ratings across teams to ensure fairness. Promotion decisions
are made separately from compensation.
""",
    ),
    (
        "on-call-compensation.md",
        """# On-Call Compensation

## Eligibility
Engineers on the on-call rotation are eligible for on-call compensation.

## Rates
On-call weeks pay a flat stipend plus an hourly rate for pages handled outside
business hours.

## Time off in lieu
Engineers may choose time off in lieu instead of the stipend. Coordinate with
your manager to schedule recovery time after a heavy on-call week.
""",
    ),
    (
        "data-classification.md",
        """# Data Classification

## Levels
Data is classified into four levels: public, internal, confidential, and
restricted.

## Definitions
Public data is safe for external sharing. Internal data stays within the
company. Confidential data is limited to specific teams. Restricted data
includes personal data and credentials and requires explicit access controls.

## Handling
Always store data at or above its classification level. Apply the least
privilege principle when granting access.
""",
    ),
]
