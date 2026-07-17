# Release And Deployment

The `Release` GitHub Actions workflow validates the repository, requires an explicit manual start, builds and pushes the runtime image with Azure Container Registry Tasks, resolves the image to an immutable digest, previews the Bicep changes, and deploys the enabled jobs through the `dev` environment.

The release is started with the **Run workflow** action. This manual dispatch is the deployment approval: merges do not mutate Azure. Concurrent releases are serialized so that an older deployment cannot overtake a newer one.

## GitHub Environment

Create a GitHub environment named `dev` and restrict deployment branches to `main`. The current private-repository billing plan does not support GitHub's required-reviewer protection rule, so the manually dispatched workflow provides the approval gate before the entire Azure-mutating job, including the ACR build.

If the repository moves to a plan that supports required reviewers for private repositories, add the deployment approver to the `dev` environment and enable **Prevent self-review** without changing the workflow.

Configure these environment variables:

| Variable | Example value |
| --- | --- |
| `AZURE_ACR_NAME` | `<registry-name>` |
| `AZURE_CLIENT_ID` | Client ID of the GitHub deployment identity |
| `AZURE_ENVIRONMENT_NAME` | `dev` |
| `AZURE_LOCATION` | `<azure-region>` |
| `AZURE_RESOURCE_GROUP` | `<resource-group>` |
| `AZURE_SUBSCRIPTION_ID` | `<subscription-id>` |
| `AZURE_TENANT_ID` | Tenant ID containing the deployment identity |

These values are identifiers rather than credentials. Do not create or store a client secret for this workflow.

## Azure Federation And RBAC

Create an Entra application or user-assigned managed identity for GitHub deployment and add a federated identity credential with:

| Setting | Value |
| --- | --- |
| Issuer | `https://token.actions.githubusercontent.com` |
| Subject | `repo:<owner>/<repository>:environment:dev` |
| Audience | `api://AzureADTokenExchange` |

Grant the deployment identity the minimum permissions needed to create resources in the target resource group, run ACR Tasks, and manage the role assignments declared by Bicep. The current template requires resource deployment permissions plus role-assignment permissions because it grants the runtime managed identity `AcrPull` and `Storage Blob Data Contributor`.

Scope deployment roles to the target resource group. A practical baseline is `Contributor` plus `Role Based Access Control Administrator`; replace it with a narrower custom role after the pilot if required by policy.

## Release Sequence

1. The validation job runs unit tests, verifies generated job parameters, and compiles Bicep.
2. An authorized repository user approves the release by manually starting the workflow against `main`.
3. The deploy job signs in to Azure using workload identity federation.
4. ACR Tasks builds and pushes `batchjobs/runtime:git-<commit>`.
5. The workflow resolves the tag to `<registry>/batchjobs/runtime@sha256:<digest>`.
6. Azure Resource Manager validates and previews the Bicep deployment.
7. Bicep deploys the shared platform and every enabled job using the immutable image reference.

The workflow summary records the image digest, deployment name, resource group, and final provisioning state. Rollback automation and post-deployment integration tests are intentionally outside this release slice.
