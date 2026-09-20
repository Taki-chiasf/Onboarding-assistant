# Testing Guidelines

## Levels
Write unit tests for pure logic, integration tests for boundaries, and a small
set of end-to-end tests for critical paths.

## Coverage
We gate merges on at least 80% coverage of core services.

## What to test
Test behavior, not implementation. Cover happy paths, error paths, and edge
cases.

## Running tests
Run the full suite locally before opening a pull request. Fix flaky tests rather
than skipping them.
