# Contributing

## Pull requests
Keep pull requests small and single-purpose. A review looks for:
- a clear description of the change and its risk,
- tests that fail before the change and pass after it,
- typed function signatures at service boundaries,
- no secrets, tokens, or customer data anywhere in the diff,
- migrations that stay backward compatible with the previous release.

## Style
Formatting and linting run in CI. Run `make lint` and `make format` before
pushing.

## Reviews
At least one approval is required. Reviewers focus on correctness and
operability; style is automated. Design changes are discussed in an ADR before
the code is written.
