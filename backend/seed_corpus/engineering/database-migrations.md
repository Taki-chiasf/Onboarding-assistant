# Database Migrations

## Tooling
Schema changes are managed with a migration framework. Migrations are versioned
and applied automatically before rollout.

## Rules
Migrations must be backward compatible so old and new versions can run side by
side during a rollout.

## Process
Add a migration with every schema change. Review migrations as carefully as code.

## Rollback
Rollback is manual and documented. Prefer additive changes that avoid destructive
rollbacks.
