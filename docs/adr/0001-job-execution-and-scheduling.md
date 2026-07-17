# ADR 0001: Job Execution and Scheduling

- Status: Superseded by [ADR 0002](0002-native-utc-scheduling.md)
- Date: 2026-07-16

## Decision

Represent each script as a separate manual Azure Container Apps Job, use shared immutable images where dependencies permit, and invoke scheduled executions from Azure Logic Apps Standard.

## Rationale

One job resource per script provides independent timeout, retry, resources, identity, configuration, execution history, permissions, and run-now behavior. Sharing an image avoids rebuilding nearly identical operating-system layers for every script while image digests preserve reproducibility.

Container Apps scheduled jobs use UTC cron expressions. The required local-time schedules must remain stable across daylight-saving changes, so Logic Apps recurrence workflows own scheduling and start manual job executions using managed identity.

A single generic job with per-execution command overrides was rejected as the default. Overrides replace the complete execution template, require a custom scheduler for every invocation, weaken per-script configuration boundaries, and complicate operator visibility.

## Consequences

- Infrastructure generates many small job resources and scheduler workflows from reviewed manifests.
- Schedule settings are stored in Git and changed through pull requests.
- Jobs may move into different image compatibility groups if Python or package requirements conflict.
- Job chains, business calendars, and missed-run recovery need later ADRs if inventory identifies them.
- The runner must add overlap prevention before production cutover because Container Apps can start concurrent executions of a manual job.
