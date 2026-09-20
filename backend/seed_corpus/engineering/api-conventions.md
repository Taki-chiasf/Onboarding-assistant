# API Conventions

## Style
Use a typed API framework and consistent error shapes. Every endpoint returns
JSON.

## Errors
Return structured errors with a machine-readable code and a human-readable
message.

## Versioning
Version breaking changes with a URL prefix. Avoid breaking changes to stable
endpoints.

## Authentication
All endpoints require authentication. Authorization is checked per resource.
