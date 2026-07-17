# ADR 0002: Native UTC Scheduling

- Status: Accepted for pilot
- Date: 2026-07-16
- Supersedes: [ADR 0001](0001-job-execution-and-scheduling.md)

## Decision

Represent each script as a separate scheduled Azure Container Apps Job. Store one five-field UTC cron expression in each job manifest and deploy it directly as the job's schedule trigger. Keep manual job starts available for run-now operations.

## Rationale

Schedules are expressed and operated in UTC. Native Container Apps Job scheduling removes the Logic Apps hosting, identity, deployment, monitoring, and failure surface while preserving per-script resources, timeout, retries, execution history, and manual starts.

The manifest field is named `cronExpressionUtc` so reviewers cannot mistake a wall-clock schedule for a time-zone-aware schedule. CI validates both the five-field shape and cron semantics before Bicep receives generated parameters.

## Consequences

- UTC offsets do not change for daylight-saving time. Owners must submit a reviewed manifest change if they want a schedule to move seasonally.
- Schedule changes remain Git changes made through pull requests.
- Native scheduling does not provide business calendars, holiday exclusions, dependencies, or missed-run recovery. Add separate decisions if the inventory requires those capabilities.
- Manual run-now starts execute the same scheduled job definition and remain protected by the overlap lease.