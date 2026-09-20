# Deploy Process

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
