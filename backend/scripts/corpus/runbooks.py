"""Synthetic runbook documents for the demo corpus."""

DOCS: list[tuple[str, str]] = [
    (
        "vpn-setup.md",
        """# VPN Setup

## Overview
The VPN provides secure access to internal services from outside the office
network.

## Prerequisites
You need a company laptop and your SSO credentials.

## Steps
1. Install the VPN client from the software catalog.
2. Sign in with SSO and approve the multi-factor prompt.
3. Select the closest region and connect.

## Troubleshooting
If the client fails to connect, verify your internet, restart the client, and
confirm your account is active in the identity provider. Escalate to IT with the
error code.
""",
    ),
    (
        "sso-mfa-setup.md",
        """# SSO and Multi-Factor Authentication Setup

## Overview
All company services use single sign-on (SSO) with mandatory multi-factor
authentication (MFA).

## Enrolling MFA
1. Install an authenticator app on your phone.
2. Visit the identity provider account settings.
3. Scan the QR code and confirm a test code.

## Backup codes
Generate backup codes and store them in your password manager. Without MFA you
cannot access company systems.

## Lost device
If you lose your phone, contact IT immediately to reset your MFA.
""",
    ),
    (
        "laptop-setup.md",
        """# Laptop Setup

## Overview
Set up your new laptop in about an hour using this runbook.

## Steps
1. Sign in and run the device enrollment wizard.
2. Install the software catalog and sign in to SSO.
3. Configure your password manager and MFA.
4. Clone your team's repositories and run the local development setup.

## Verification
Open a terminal and confirm your development tools are on the path. Ask your
onboarding buddy to review your setup.
""",
    ),
    (
        "email-and-calendar.md",
        """# Email and Calendar

## Email
Use the company email client. Keep your inbox tidy with filters and folders.
Forwarding company email to personal accounts is not allowed.

## Calendar
Share your calendar with your team. Keep it accurate for remote collaboration.
Set working hours and block focus time.

## Meeting hygiene
Respond to invitations promptly. Decline meetings you cannot attend and propose
an alternative.
""",
    ),
    (
        "chat-usage.md",
        """# Chat Usage

## Channels
Join your team channel and the company announcements channel. Use public
channels for work so others can learn.

## Status
Set your status and availability. Use the out-of-office status when on leave.

## Threads
Reply in threads to keep channels readable. Use threads for follow-up discussion
on a topic.

## Notifications
Configure notifications to avoid overload. It is acceptable to silence
non-urgent channels during focus time.
""",
    ),
    (
        "accessing-wifi.md",
        """# Accessing Wi-Fi

## Office network
Connect to the office SSO-secured network using your company credentials.

## Remote network
When working remotely, the VPN provides equivalent access. See the VPN setup
runbook.

## Guest network
A guest network is available for visitors. It has no access to internal
services.

## Troubleshooting
Forget and re-add the network, then re-authenticate with SSO. Contact IT if the
issue persists.
""",
    ),
    (
        "request-access.md",
        """# Requesting Access

## Overview
Access to systems and data follows least privilege. Request only what you need.

## Steps
1. Open the access request form in the identity portal.
2. Select the system and role you need.
3. Provide a business justification.
4. Await approval from the system owner.

## Expiry
Access grants expire after 90 days unless renewed. Re-request access when
returning from long leave.
""",
    ),
    (
        "git-workflow.md",
        """# Git Workflow

## Branching
Work on short-lived feature branches off the main branch. Name branches with a
ticket reference and a short description.

## Commits
Write clear commit messages. Keep commits small and focused.

## Pull requests
Open a pull request early. Request review from the owning team. Address all
comments before merge.

## Merging
Use squash merges for feature work. The main branch must always stay green.
""",
    ),
    (
        "incident-response.md",
        """# Incident Response

## Severities
Incidents are severity 1 through 4, with 1 being the most severe. Severity 1
means a customer-facing outage.

## Who responds
The on-call engineer owns the incident until it is resolved. The incident
commander coordinates communication.

## Process
Declare the incident in the incident channel, open a war room, and update
status regularly. Write a postmortem for severity 1 and 2 incidents.

## Postmortems
Postmortems are blameless and focus on process and system improvements.
""",
    ),
    (
        "deploy-process.md",
        """# Deploy Process

## Overview
Deploys are automated and must pass the CI pipeline before reaching production.

## Steps
1. Merge your change to the main branch.
2. Wait for CI to build and test.
3. The change rolls out automatically to staging, then production.

## Rollbacks
If a deploy fails, revert the change and redeploy. The previous release remains
available for quick rollback.

## Deploy windows
Production deploys are allowed any time. Risky changes should deploy during
business hours when more people are available.
""",
    ),
    (
        "on-call-guide.md",
        """# On-Call Guide

## Overview
Engineers rotate through on-call shifts to keep services available around the
clock.

## Responsibilities
Respond to pages, triage incidents, and hand off cleanly at the end of your
shift.

## Escalation
Escalate to your team lead if you cannot resolve an incident within 30 minutes.

## Handoff
Write a short handoff note summarizing open incidents and any unfinished work.
""",
    ),
    (
        "local-dev-setup.md",
        """# Local Development Setup

## Prerequisites
Install the language runtimes and the package manager listed in the repository
readme.

## Steps
1. Clone the repository.
2. Install dependencies.
3. Copy the example environment file and fill in the required values.
4. Start the database and cache services.
5. Run the development server and open the health check.

## Verification
Run the test suite to confirm your environment is working before making
changes.
""",
    ),
    (
        "expense-submission.md",
        """# Expense Submission

## Overview
Submit work-related expenses for reimbursement using the expense tool.

## Steps
1. Open the expense tool and start a new report.
2. Add each expense with a category and description.
3. Attach receipts for expenses over $25.
4. Submit the report for approval.

## Approval
Your manager approves reports. Approved reports are paid in the next payroll
cycle.

## Common mistakes
Missing receipts and late submissions are the most common rejection reasons.
""",
    ),
    (
        "request-equipment.md",
        """# Requesting Equipment

## Overview
Request standard and specialty equipment through the equipment request process.

## Steps
1. Open the equipment request form.
2. Select the item type and quantity.
3. Provide a shipping address.
4. Submit for IT approval.

## Lead times
Standard items ship within 3 business days. Custom items may take longer and
require manager approval.

## Follow-up
Track your request status in the IT portal. Contact IT for anything over a week
late.
""",
    ),
]
