// =============================================================================
// Container Jobs - Azure Infrastructure (Resource Group Scope)
// =============================================================================
// Main Bicep template for deploying Azure Container Apps Jobs infrastructure
// with Log Analytics, ACR, Storage, Managed Identity, and role assignments.
//
// Scope: Resource Group
// Pre-requisites: Existing VNet with subnet for Container Apps infrastructure

targetScope = 'resourceGroup'

// =============================================================================
// PARAMETERS
// =============================================================================

@description('Azure region for all resources')
param location string = resourceGroup().location

@description('Environment name used for resource naming (e.g., dev, staging, prod)')
@minLength(2)
@maxLength(10)
param environmentName string

@description('Resource ID of an existing subnet for Container Apps infrastructure. Leave empty to create a pilot VNet and subnet.')
param existingSubnetId string = ''

@description('Resource ID of a private-endpoint subnet in the same VNet as existingSubnetId. Required when existingSubnetId is set.')
param existingPrivateEndpointSubnetId string = ''

@description('Address prefix for the pilot VNet created when existingSubnetId is empty.')
param vnetAddressPrefix string = '10.42.0.0/16'

@description('Address prefix for the dedicated Container Apps infrastructure subnet.')
param acaSubnetAddressPrefix string = '10.42.0.0/27'

@description('Address prefix for private endpoints in the pilot VNet.')
param privateEndpointSubnetAddressPrefix string = '10.42.0.32/28'

@description('Container image reference (e.g., myacr.azurecr.io/container-jobs:sha256-abc123). Pinned by caller.')
param imageReference string = ''

@description('Deploy enabled jobs after their image has been pushed to the registry.')
param deployJobs bool = false

@description('Deploy the operations workbook and scheduled-query alert rules.')
param deployObservability bool = true

@description('Optional Azure Monitor action group resource IDs for alert notifications.')
param observabilityActionGroupIds array = []

@description('Job definitions generated from repository manifests.')
param jobDefinitions array = []

@description('Resource tags applied to all resources')
param tags object = {}

// =============================================================================
// VARIABLES
// =============================================================================

// Generate globally unique suffix from subscription, resource group, and environment
var uniqueSuffix = uniqueString(subscription().subscriptionId, resourceGroup().id, environmentName)

// Resource naming (Azure compliant)
var logAnalyticsName = 'log-batchjobs-${environmentName}-${uniqueSuffix}'
var acrName = 'acrbatchjobs${environmentName}${uniqueSuffix}' // alphanumeric only, max 50 chars
var storageName = 'st${take(environmentName, 6)}${take(uniqueSuffix, 12)}' // lowercase alphanumeric, max 24 chars
var identityName = 'id-batchjobs-${environmentName}-${uniqueSuffix}'
var acaEnvName = 'acaenv-batchjobs-${environmentName}-${uniqueSuffix}'
var vnetName = 'vnet-batchjobs-${environmentName}-${uniqueSuffix}'
var acaSubnetName = 'snet-aca'
var privateEndpointSubnetName = 'snet-private-endpoints'
var blobPrivateEndpointName = 'pe-${storageName}-blob'
var blobPrivateDnsZoneName = 'privatelink.blob.${environment().suffixes.storage}'
// Constants
var blobContainerName = 'job-locks'
var workloadProfileName = 'Consumption'
var enabledJobDefinitions = filter(jobDefinitions, job => job.enabled)
var acaSubnetId = !empty(existingSubnetId) ? existingSubnetId : '${pilotVnet.id}/subnets/${acaSubnetName}'
var privateEndpointSubnetId = !empty(existingSubnetId) ? existingPrivateEndpointSubnetId : '${pilotVnet.id}/subnets/${privateEndpointSubnetName}'
var privateEndpointVnetId = !empty(existingSubnetId) ? join(take(split(existingPrivateEndpointSubnetId, '/'), 9), '/') : pilotVnet.id

// Role definition IDs (Azure built-in roles)
var storageBlobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'

// =============================================================================
// RESOURCES
// =============================================================================

// -----------------------------------------------------------------------------
// Log Analytics Workspace
// -----------------------------------------------------------------------------
resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: logAnalyticsName
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
    features: {
      enableLogAccessUsingOnlyResourcePermissions: true
    }
  }
}

// -----------------------------------------------------------------------------
// Container Registry (Basic, Admin Disabled)
// -----------------------------------------------------------------------------
resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  tags: tags
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: 'Enabled'
    networkRuleBypassOptions: 'AzureServices'
  }
}

// -----------------------------------------------------------------------------
// Storage Account (Standard_LRS, Shared Key Disabled)
// -----------------------------------------------------------------------------
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: storageName
  location: location
  tags: tags
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    minimumTlsVersion: 'TLS1_2'
    publicNetworkAccess: 'Disabled'
    supportsHttpsTrafficOnly: true
    networkAcls: {
      defaultAction: 'Deny'
      bypass: 'AzureServices'
    }
  }
}

// Blob Service
resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-01-01' = {
  parent: storageAccount
  name: 'default'
  properties: {
    deleteRetentionPolicy: {
      enabled: true
      days: 7
    }
  }
}

// Job Locks Container
resource jobLocksContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  parent: blobService
  name: blobContainerName
  properties: {
    publicAccess: 'None'
  }
}

// -----------------------------------------------------------------------------
// User-Assigned Managed Identity
// -----------------------------------------------------------------------------
resource managedIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: identityName
  location: location
  tags: tags
}

// -----------------------------------------------------------------------------
// Pilot Virtual Network (created only when no landing-zone subnet is supplied)
// -----------------------------------------------------------------------------
resource pilotVnet 'Microsoft.Network/virtualNetworks@2024-05-01' = if (empty(existingSubnetId)) {
  name: vnetName
  location: location
  tags: tags
  properties: {
    privateEndpointVNetPolicies: 'Disabled'
    addressSpace: {
      addressPrefixes: [
        vnetAddressPrefix
      ]
    }
    subnets: [
      {
        name: acaSubnetName
        properties: {
          addressPrefix: acaSubnetAddressPrefix
          delegations: [
            {
              name: 'Microsoft.App.environments'
              properties: {
                serviceName: 'Microsoft.App/environments'
              }
            }
          ]
        }
      }
      {
        name: privateEndpointSubnetName
        properties: {
          addressPrefix: privateEndpointSubnetAddressPrefix
          privateEndpointNetworkPolicies: 'Disabled'
        }
      }
    ]
  }
}

resource blobPrivateDnsZone 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: blobPrivateDnsZoneName
  location: 'global'
  tags: tags
}

resource blobPrivateDnsVnetLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: blobPrivateDnsZone
  name: 'link-${vnetName}'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: privateEndpointVnetId
    }
  }
}

resource blobPrivateEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: blobPrivateEndpointName
  location: location
  tags: tags
  properties: {
    subnet: {
      id: privateEndpointSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: 'blob'
        properties: {
          privateLinkServiceId: storageAccount.id
          groupIds: [
            'blob'
          ]
        }
      }
    ]
  }
}

resource blobPrivateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: blobPrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'blob'
        properties: {
          privateDnsZoneId: blobPrivateDnsZone.id
        }
      }
    ]
  }
}

// -----------------------------------------------------------------------------
// Role Assignments
// -----------------------------------------------------------------------------

// Storage Blob Data Contributor (Identity -> Storage)
resource storageRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, managedIdentity.id, storageBlobDataContributorRoleId)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
    principalId: managedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// AcrPull (Identity -> ACR)
resource acrRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, managedIdentity.id, acrPullRoleId)
  scope: acr
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalId: managedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// -----------------------------------------------------------------------------
// Container Apps Environment (Workload Profile, VNet Integrated)
// -----------------------------------------------------------------------------
resource acaEnvironment 'Microsoft.App/managedEnvironments@2023-05-01' = {
  name: acaEnvName
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        #disable-next-line use-secure-value-for-secure-inputs
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
    vnetConfiguration: {
      infrastructureSubnetId: acaSubnetId
    }
    workloadProfiles: [
      {
        name: workloadProfileName
        workloadProfileType: 'Consumption'
      }
    ]
  }
}

// -----------------------------------------------------------------------------
// Container Apps Jobs (UTC Schedule Trigger)
// -----------------------------------------------------------------------------
resource containerJobs 'Microsoft.App/jobs@2023-05-01' = [for job in enabledJobDefinitions: if (deployJobs) {
  name: take('job-${uniqueString(job.id, environmentName)}-${job.id}', 32)
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${managedIdentity.id}': {}
    }
  }
  properties: {
    environmentId: acaEnvironment.id
    workloadProfileName: workloadProfileName
    configuration: {
      triggerType: 'Schedule'
      replicaTimeout: job.timeoutSeconds
      replicaRetryLimit: job.retryLimit
      scheduleTriggerConfig: {
        cronExpression: job.cronExpressionUtc
        replicaCompletionCount: 1
        parallelism: 1
      }
      registries: [
        {
          server: acr.properties.loginServer
          identity: managedIdentity.id
        }
      ]
    }
    template: {
      containers: [
        {
          name: job.id
          image: imageReference
          command: [
            '/venv/bin/batchjobs-run'
          ]
          args: concat([
            '--script'
            job.script
            '--timeout-seconds'
            string(job.timeoutSeconds)
            '--'
          ], job.arguments)
          resources: {
            cpu: job.cpu
            memory: job.memory
          }
          env: concat([
            {
              name: 'BATCHJOBS_JOB_ID'
              value: job.id
            }
            {
              name: 'BATCHJOBS_TRIGGER'
              value: 'schedule'
            }
            {
              name: 'BATCHJOBS_LOCK_CONTAINER_URL'
              value: '${storageAccount.properties.primaryEndpoints.blob}${blobContainerName}'
            }
            {
              name: 'BATCHJOBS_IMAGE_REVISION'
              value: imageReference
            }
            {
              name: 'AZURE_CLIENT_ID'
              value: managedIdentity.properties.clientId
            }
          ], job.environment)
        }
      ]
    }
  }
  dependsOn: [
    storageRoleAssignment
    acrRoleAssignment
  ]
}]

module observability './observability/main.bicep' = if (deployObservability) {
  params: {
    actionGroupIds: observabilityActionGroupIds
    environmentName: environmentName
    jobDefinitions: jobDefinitions
    location: location
    tags: tags
    workspaceId: logAnalytics.id
  }
}

// =============================================================================
// OUTPUTS
// =============================================================================

@description('Log Analytics Workspace ID')
output logAnalyticsWorkspaceId string = logAnalytics.id

@description('Log Analytics Workspace Customer ID (for instrumentation keys)')
output logAnalyticsCustomerId string = logAnalytics.properties.customerId

@description('Container Registry name')
output containerRegistryName string = acr.name

@description('Container Registry login server')
output containerRegistryLoginServer string = acr.properties.loginServer

@description('Container Registry resource ID')
output containerRegistryId string = acr.id

@description('Storage Account name')
output storageAccountName string = storageAccount.name

@description('Storage Account blob endpoint')
output storageAccountBlobEndpoint string = storageAccount.properties.primaryEndpoints.blob

@description('Job locks container URL')
output jobLocksContainerUrl string = '${storageAccount.properties.primaryEndpoints.blob}${blobContainerName}'

@description('User-assigned managed identity resource ID')
output managedIdentityId string = managedIdentity.id

@description('User-assigned managed identity client ID')
output managedIdentityClientId string = managedIdentity.properties.clientId

@description('User-assigned managed identity principal ID')
output managedIdentityPrincipalId string = managedIdentity.properties.principalId

@description('Container Apps Environment name')
output containerAppsEnvironmentName string = acaEnvironment.name

@description('Container Apps Environment resource ID')
output containerAppsEnvironmentId string = acaEnvironment.id

@description('Container Apps Environment default domain')
output containerAppsEnvironmentDefaultDomain string = acaEnvironment.properties.defaultDomain

@description('Subnet used by the Container Apps Environment')
output containerAppsInfrastructureSubnetId string = acaSubnetId

@description('Names of enabled jobs selected for deployment')
output deployedJobNames array = deployJobs ? map(enabledJobDefinitions, job => take('job-${uniqueString(job.id, environmentName)}-${job.id}', 32)) : []

@description('Azure Workbook resource ID for fleet operations.')
output operationsWorkbookId string = observability.?outputs.?workbookId ?? ''

@description('Azure Monitor scheduled-query alert rule resource IDs.')
output observabilityAlertRuleIds array = observability.?outputs.?alertRuleIds ?? []
