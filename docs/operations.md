# Container Jobs Operations

## Workbook

The `Container Jobs Operations - <environment>` Azure Workbook is scoped to the platform Log Analytics workspace. It provides:

- fleet execution, success, failure, and overlap-skip counts;
- latest terminal status per job;
- average and 95th-percentile duration trends;
- failure, timeout, lock, and rejection details; and
- recent unchanged-script stdout and stderr.

Use the time-range and job parameters to narrow all panels. Lifecycle records are identified by the `batchjobs.lifecycle.v1` schema. Console output remains unstructured so existing scripts do not need to change.

## Alert Rules

The deployment creates these scheduled-query alerts:

| Signal | Severity | Evaluation | Condition |
| --- | --- | --- | --- |
| Job failure | 2 | Every 5 minutes | A `failed`, `timed_out`, `lock_failed`, or `rejected` lifecycle event |
| Missing completion | 3 | Hourly | No `completed`, `failed`, or `timed_out` event within the manifest's `monitoring.maxSilenceMinutes` |
| Repeated overlap | 3 | Every 15 minutes | At least three `skipped_overlap` events in one hour; opt-in per manifest |

Alert rules work without notification destinations. Set `observabilityActionGroupIds` to one or more existing Azure Monitor Action Group resource IDs to notify email, SMS, Teams, ITSM, or automation destinations.

## Manifest Policy

Each job can declare:

```json
"monitoring": {
  "maxSilenceMinutes": 1440,
  "alertOnFailure": true,
  "alertOnStale": false,
  "alertOnOverlap": false
}
```

Enable `alertOnStale` only when the longest expected gap, including weekends, holidays, and maintenance windows, fits Azure Monitor's 2,880-minute query limit. Choose `maxSilenceMinutes` within that bound. Keep stale alerting disabled for schedules with longer legitimate gaps, and enable overlap alerts only when repeated skips indicate a scheduling or runtime problem.

## Response

### Failure or timeout

1. Open the workbook's failure row and note the job, execution, image revision, exit code, and timestamp.
2. Review console output for the same execution.
3. Correct source, dependencies, configuration, or external connectivity through the normal pull-request path.
4. Deploy an immutable image digest and manually start the job once.
5. Confirm a `completed` lifecycle event before resolving the alert.

### Lock failure

1. Verify the storage private endpoint and `privatelink.blob.core.windows.net` resolution.
2. Verify the job identity has `Storage Blob Data Contributor` on the lock storage account.
3. Check storage and identity health before retrying. Do not bypass the overlap lock.

### Missing completion

1. Confirm the job is enabled and its UTC cron is correct.
2. Check Container Apps execution history for image-pull, startup, or platform failures that occurred before the runner emitted telemetry.
3. Compare the threshold with expected weekends and maintenance windows.
4. Start one manual execution only after confirming it will not duplicate side effects.

### Repeated overlap

1. Compare execution duration with schedule frequency.
2. Confirm an earlier execution is still active before taking action.
3. Increase schedule spacing or investigate abnormal duration; do not delete the lease while a job may still be running.
