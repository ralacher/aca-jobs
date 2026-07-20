# Container Jobs

This repository is the starting point for moving independently owned Python batch scripts from production-server edits and SQL Agent schedules into a governed delivery and execution platform.

The platform does not require application rewrites. A platform-owned runner launches each unchanged script as a child process, preserves its output and exit status, and adds lifecycle telemetry around it.

## Target Model

- GitHub is the source of truth for scripts and job configuration.
- Pull requests validate Python syntax, manifests, tests, and the container build.
- One scheduled Azure Container Apps Job resource represents each script.
- Jobs can share an immutable image while their Python and system dependencies remain compatible.
- A renewable Azure Blob lease prevents concurrent executions of the same job.
- Native Container Apps Job cron triggers provide fixed UTC schedules.
- Azure Monitor Logs and Workbooks provide fleet history, diagnostics, and dashboards.
- Managed identities and Key Vault references provide runtime access without stored credentials.

See [docs/architecture.md](docs/architecture.md) and [ADR 0002](docs/adr/0002-native-utc-scheduling.md) for the rationale and boundaries.
See [docs/operations.md](docs/operations.md) for workbook usage, alert policy, and incident response.

## Repository Layout

| Path | Purpose |
| --- | --- |
| `jobs/<job-id>/` | Unchanged script source and its declarative `job.json` manifest |
| `schemas/` | Versioned contracts validated for every job |
| `src/batchjobs_runner/` | Platform runtime wrapper; not application business logic |
| `tests/` | Runner and manifest contract tests |
| `.github/workflows/` | Pull-request validation and approved Azure release workflows |

The enabled `jobs/example-report` job is an inert pilot fixture, not a production workload.

## Local Validation

Python 3.11 or newer is required.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe tools\batchjobs_compile.py --output .\.cache\jobs.parameters.json
.\.venv\Scripts\python.exe -m compileall -q src jobs
az bicep build --file infra/main.bicep --stdout | Out-Null
```

Build the runtime image without executing any job:

```powershell
docker build --tag container-jobs:local .
```

Run the inert example explicitly:

```powershell
docker run --rm --env BATCHJOBS_JOB_ID=example-report container-jobs:local \
	--script /app/jobs/example-report/script.py --timeout-seconds 30
```

## Onboard a Job

1. Create `jobs/<job-id>/` and add the existing script without modifying it.
2. Copy and update the example `job.json` with its owner, five-field UTC cron schedule, resources, dependencies, and monitoring freshness threshold.
3. Leave retries at `0` until the owner confirms that repeating the script cannot duplicate side effects.
4. Run the local validation commands and open a pull request.
5. The GitHub validation and release workflows compile job parameters on the runner from `jobs/*/job.json` and deploy the generated output directly.

Before the first real pilot, complete the inventory for networking, ODBC drivers, file paths, credentials, expected duration, overlap behavior, and rollback ownership.

The initial Azure foundation is in [infra/README.md](infra/README.md). It deliberately uses two deployments: create ACR and the shared foundation first, push a digest-addressed image, then deploy every enabled manifest with that digest.

See [docs/release.md](docs/release.md) for the protected GitHub environment, Azure federation, RBAC, and automated release sequence.

All schedules use five-field cron expressions evaluated in UTC.
