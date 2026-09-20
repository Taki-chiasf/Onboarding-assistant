# Security in Code

## Input validation
Validate all input at the boundary. Never trust client-supplied data.

## Secrets
Never commit secrets. Load credentials from the secrets manager at runtime.

## Least privilege
Run services with the minimum permissions required. Scope database access to
what a service needs.

## Dependencies
Keep dependencies up to date and scan them for known vulnerabilities in CI.
