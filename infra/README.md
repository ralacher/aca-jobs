# Container Jobs - Azure Infrastructure

This directory contains the Bicep infrastructure-as-code for deploying the Azure Container Apps Jobs environment.

## Architecture Overview

The infrastructure deploys the following resources:

- **Log Analytics Workspace**: Centralized logging and monitoring
- **Azure Container Registry (Basic)**: Private container image registry with admin disabled
- **Storage Account (Standard_LRS)**: Blob storage for job lock coordination with shared key access disabled
  - **job-locks container**: Stores lease-based locks for overlap prevention
- **Blob Private Endpoint and Private DNS**: Routes lock traffic from the Container Apps VNet without public storage access
- **User-Assigned Managed Identity**: Workload identity for Container Apps Jobs
- **Container Apps Environment**: Workload-profile environment with VNet integration
- **Container Apps Jobs**: Native UTC schedule triggers generated from enabled manifests
- **Azure Workbook**: Fleet health, latest status, duration, failures, and console output
- **Scheduled-Query Alerts**: Failure, missing-completion, and opt-in repeated-overlap detection

### Security & Compliance

- ✅ ACR admin user disabled (identity-based authentication only)
- ✅ Storage shared key access disabled (Entra ID authentication only)
- ✅ Storage public network access disabled with private Blob connectivity
- ✅ Managed identity with least-privilege RBAC assignments
- ✅ TLS 1.2 minimum for storage
- ✅ Private image repository with registry authentication enforced
- ✅ VNet-integrated Container Apps environment

### Role Assignments

The managed identity is assigned the following roles:

- **Storage Blob Data Contributor** → Storage Account (for job lock management)
- **AcrPull** → Container Registry (for pulling container images)

## Prerequisites

Before deploying, ensure you have:

1. **Azure Subscription** with appropriate permissions
2. **Network address plan** for the Container Apps infrastructure subnet
  - By default, the pilot creates `10.42.0.0/16` with a dedicated `10.42.0.0/27` subnet
  - The pilot also creates `10.42.0.32/28` for the Blob private endpoint
  - Set `existingSubnetId` to use a landing-zone subnet instead; it must be delegated to `Microsoft.App/environments`
  - When using `existingSubnetId`, set `existingPrivateEndpointSubnetId` to a separate subnet in the same VNet
3. **Container Image** built and pushed after the foundation creates ACR
4. **Azure CLI** installed with Bicep support (`az bicep version`)

## Validation Status

The template compiles locally with `az bicep build`. It has not been submitted to Azure Resource Manager validation or deployed. Formal preflight requires an approved deployment plan plus real subscription, resource-group, subnet, image-digest, and caller-permission inputs. Run an Azure `what-if` and resource-group validation only after those values are reviewed; do not use the example parameter file for deployment.

## Deployment

Production changes use the approved GitHub Actions release workflow described in [../docs/release.md](../docs/release.md). The commands below remain useful for initial foundation setup and local troubleshooting.

### 1. Create Parameter File

Copy the example parameter file and fill in real values:

```bash
cp main.parameters.example.json main.parameters.dev.json
```

Edit `main.parameters.dev.json` and replace all `REPLACE-*` placeholders. Keep `deployJobs` false and `imageReference` empty for the first deployment.

- `environmentName`: Environment identifier (e.g., `dev`, `staging`, `prod`)
- `existingSubnetId`: Full resource ID of an existing delegated subnet, or empty to create the pilot network
- `existingPrivateEndpointSubnetId`: Full resource ID of a dedicated private-endpoint subnet; required with `existingSubnetId`
- `vnetAddressPrefix`: Pilot VNet address space used when `existingSubnetId` is empty
- `acaSubnetAddressPrefix`: Dedicated ACA infrastructure subnet; `/27` or larger
- `privateEndpointSubnetAddressPrefix`: Pilot private-endpoint subnet; defaults to `10.42.0.32/28`
- `imageReference`: Container image reference (e.g., `myacr.azurecr.io/container-jobs:v1.0.0`)
- `deployJobs`: Global second-phase switch for manifests whose `enabled` field is true
- `deployObservability`: Deploy the operations workbook and scheduled-query alerts
- `observabilityActionGroupIds`: Optional existing Azure Monitor Action Group resource IDs for notifications
- `tags`: Update with your team/project information

### 2. Compile and Validate Deployment Inputs

```bash
python ../tools/batchjobs_compile.py --output .cache/jobs.parameters.json
az bicep build --file main.bicep
```

`jobs.parameters.json` is generated deterministically from every `jobs/*/job.json` manifest by the GitHub workflows and is not committed. Do not edit generated output directly. The compiler rejects reserved platform environment variables and fails explicitly when a manifest requests secret or volume deployment, which are not implemented yet.

### 3. Deploy the Shared Foundation

```bash
# Create resource group if needed
az group create \
  --name rg-batchjobs-dev \
  --location eastus

# Deploy infrastructure
az deployment group create \
  --resource-group rg-batchjobs-dev \
  --template-file main.bicep \
  --parameters main.parameters.dev.json .cache/jobs.parameters.json
```

### 4. Build and Push the Image

Read `containerRegistryLoginServer` from the first deployment, then build and push the image using the Git commit as its tag. Resolve the pushed manifest to a digest and use the immutable form `<registry>/batchjobs/runtime@sha256:<digest>`.

### 5. Deploy Enabled Jobs

Set `deployJobs` to `true` and `imageReference` to the immutable digest reference, then repeat the deployment command with both parameter files. Only manifests with `enabled: true` create jobs. This global switch prevents the foundation deployment from referencing an image in the registry before it has been pushed.

### 6. Verify Deployment

```bash
# Check deployment status
az deployment group show \
  --resource-group rg-batchjobs-dev \
  --name main

# List outputs
az deployment group show \
  --resource-group rg-batchjobs-dev \
  --name main \
  --query properties.outputs
```

## Resource Naming Convention

Resources are named using the pattern:

```
<resource-prefix>-batchjobs-<environment>-<unique-suffix>
```

Where `<unique-suffix>` is deterministically generated from:
- Subscription ID
- Resource Group ID
- Environment Name

This ensures:
- ✅ Globally unique names (required for ACR, Storage)
- ✅ Consistent naming across deployments
- ✅ Easy identification of resources by environment

## Container Apps Job Configuration

Each generated job is configured from its manifest with:

- **Trigger Type**: Schedule, evaluated in UTC
- **Cron**: Five fields from `schedule.cronExpressionUtc`
- **Timeout**: 900 seconds (15 minutes)
- **Retry Limit**: 0 (fail fast)
- **Parallelism**: 1 replica
- **Completion Count**: 1 (one successful run required)
- **Resources**: 0.5 CPU, 1Gi memory
- **Command**: `/venv/bin/batchjobs-run`
- **Args**: `--script /app/jobs/example-report/script.py --timeout-seconds 900`

### Environment Variables

| Variable | Description |
|----------|-------------|
| `BATCHJOBS_JOB_ID` | Job identifier (`example-report`) |
| `BATCHJOBS_TRIGGER` | Configured trigger type (`schedule`) |
| `BATCHJOBS_LOCK_CONTAINER_URL` | Blob container URL for lock coordination |
| `BATCHJOBS_IMAGE_REVISION` | Container image reference (for telemetry/debugging) |
| `AZURE_CLIENT_ID` | Selects the job's user-assigned managed identity |

### Executing Jobs Manually

```bash
# Select a job name from outputs
JOB_NAME=$(az deployment group show \
  --resource-group rg-batchjobs-dev \
  --name main \
  --query 'properties.outputs.deployedJobNames.value[0]' \
  --output tsv)

# Start job execution
az containerapp job start \
  --name $JOB_NAME \
  --resource-group rg-batchjobs-dev

# Monitor execution
az containerapp job execution list \
  --name $JOB_NAME \
  --resource-group rg-batchjobs-dev \
  --output table
```

## Outputs

The deployment provides the following outputs:

| Output | Description |
|--------|-------------|
| `logAnalyticsWorkspaceId` | Log Analytics resource ID |
| `containerRegistryName` | ACR name for pushing images |
| `containerRegistryLoginServer` | ACR login server URL |
| `storageAccountName` | Storage account name |
| `jobLocksContainerUrl` | Full URL to job locks container |
| `managedIdentityId` | Managed identity resource ID |
| `managedIdentityClientId` | Client ID for identity configuration |
| `containerAppsEnvironmentName` | Environment name |
| `deployedJobNames` | Names of enabled jobs selected for deployment |
| `operationsWorkbookId` | Container Jobs Operations workbook resource ID |
| `observabilityAlertRuleIds` | Scheduled-query alert resource IDs |

## Next Steps

After initial deployment:

1. **Add Additional Jobs** by generating resources from validated manifests
2. **Connect Alert Notifications** by supplying existing Action Group resource IDs
3. **Review RBAC** permissions for CI/CD federated identities

## Known Limitations & Assumptions

- **Pilot Network by Default**: Review `10.42.0.0/16` before peering with an existing network; supply `existingSubnetId` in managed landing zones
- **UTC Schedules Only**: Daylight-saving changes require reviewed cron updates
- **No Business Calendars**: Holiday exclusions and missed-run recovery are not implemented
- **Basic ACR**: Consider upgrading to Standard for geo-replication in production
- **30-Day Log Retention**: Adjust Log Analytics retention based on compliance requirements
- **Public ACR Access**: Consider private endpoints for production
- **Existing Network DNS**: The deployment links a private Blob DNS zone to the VNet containing `existingPrivateEndpointSubnetId`; coordinate with centralized DNS if the landing zone manages private zones elsewhere

## Cost Estimation

Approximate monthly costs (East US, as of 2026):

- **Log Analytics**: ~$2.76/GB ingested + storage
- **ACR Basic**: ~$5/month
- **Storage (Standard_LRS)**: ~$0.02/GB + transactions
- **Container Apps Environment**: Free (Consumption workload profile)
- **Container Apps Job Execution**: ~$0.000012/vCPU-second + $0.000001/GiB-second

Actual costs depend on:
- Job execution frequency
- Log ingestion volume
- Image storage size
- Network egress

## Support & Troubleshooting

Common issues:

1. **Subnet Delegation**: Ensure subnet is delegated to `Microsoft.App/environments`
2. **Image Pull Failures**: Verify managed identity has AcrPull role and image exists
3. **Lock Failures**: Verify managed identity RBAC, Blob private-endpoint approval, and private DNS resolution
4. **VNet Integration**: Ensure subnet has sufficient address space (/27 minimum)

## API Versions

Current stable API versions used:

- Log Analytics: `2022-10-01`
- Container Registry: `2023-07-01`
- Storage Account: `2023-01-01`
- Managed Identity: `2023-01-31`
- Container Apps: `2023-05-01`
- Role Assignments: `2022-04-01`
