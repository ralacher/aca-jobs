targetScope = 'resourceGroup'

@description('Azure region for monitoring resources.')
param location string

@description('Environment name used in monitoring resource names.')
param environmentName string

@description('Resource ID of the Log Analytics workspace containing Container Apps logs.')
param workspaceId string

@description('Enabled job definitions with compiled monitoring policies.')
param jobDefinitions array

@description('Optional Azure Monitor action group resource IDs for alert notifications.')
param actionGroupIds array = []

@description('Resource tags applied to monitoring resources.')
param tags object = {}

var enabledJobDefinitions = filter(jobDefinitions, job => job.enabled)
var failureAlertJobs = filter(enabledJobDefinitions, job => job.monitoring.alertOnFailure)
var staleAlertJobs = filter(enabledJobDefinitions, job => job.monitoring.alertOnStale)
var overlapAlertJobs = filter(enabledJobDefinitions, job => job.monitoring.alertOnOverlap)
var workbookName = guid(resourceGroup().id, environmentName, 'container-jobs-operations')
var workbookDefinition = replace(loadTextContent('workbook.json'), '__WORKSPACE_ID__', workspaceId)
var failureQuery = '''
ContainerAppConsoleLogs_CL
| extend lifecycle = parse_json(Log_s)
| where tostring(lifecycle.schema) == 'batchjobs.lifecycle.v1'
| extend event = tostring(lifecycle.event), job_id = tostring(lifecycle.job_id), execution_id = tostring(lifecycle.execution_id), error_type = tostring(lifecycle.error_type)
| where event in ('failed','timed_out','lock_failed','rejected')
| project TimeGenerated, job_id, event, execution_id, error_type
'''

resource operationsWorkbook 'Microsoft.Insights/workbooks@2023-06-01' = {
  name: workbookName
  location: location
  kind: 'shared'
  tags: tags
  properties: {
    category: 'workbook'
    description: 'Fleet health, execution history, duration, failures, overlap skips, and console output for container jobs.'
    displayName: 'Container Jobs Operations - ${environmentName}'
    serializedData: workbookDefinition
    sourceId: workspaceId
    version: 'Notebook/1.0'
  }
}

resource failureAlert 'Microsoft.Insights/scheduledQueryRules@2023-12-01' = if (length(failureAlertJobs) > 0) {
  name: 'alert-batchjobs-${environmentName}-failures'
  location: location
  tags: tags
  properties: {
    actions: {
      actionGroups: actionGroupIds
      customProperties: {
        signal: 'job-failure'
      }
    }
    autoMitigate: false
    criteria: {
      allOf: [
        {
          failingPeriods: {
            minFailingPeriodsToAlert: 1
            numberOfEvaluationPeriods: 1
          }
          operator: 'GreaterThan'
          query: failureQuery
          threshold: 0
          timeAggregation: 'Count'
        }
      ]
    }
    description: 'Detects failed, timed out, rejected, or lock-failed container job lifecycle events.'
    displayName: 'Container jobs - failures (${environmentName})'
    enabled: true
    evaluationFrequency: 'PT5M'
    muteActionsDuration: 'PT5M'
    scopes: [
      workspaceId
    ]
    severity: 2
    skipQueryValidation: false
    windowSize: 'PT5M'
  }
}

resource staleAlerts 'Microsoft.Insights/scheduledQueryRules@2023-12-01' = [for job in staleAlertJobs: {
  name: take('alert-batchjobs-${environmentName}-${job.id}-stale', 260)
  location: location
  tags: tags
  properties: {
    actions: {
      actionGroups: actionGroupIds
      customProperties: {
        job_id: job.id
        signal: 'job-stale'
      }
    }
    autoMitigate: false
    criteria: {
      allOf: [
        {
          failingPeriods: {
            minFailingPeriodsToAlert: 1
            numberOfEvaluationPeriods: 1
          }
          operator: 'GreaterThan'
          query: '''
let terminalEvents = toscalar(
    ContainerAppConsoleLogs_CL
    | where TimeGenerated > ago(${job.monitoring.maxSilenceMinutes}m)
    | extend lifecycle = parse_json(Log_s)
    | where tostring(lifecycle.schema) == 'batchjobs.lifecycle.v1'
    | where tostring(lifecycle.job_id) == '${job.id}'
    | where tostring(lifecycle.event) in ('completed','failed','timed_out')
    | count
);
print MissingCompletion = iff(terminalEvents == 0, 1, 0)
| where MissingCompletion == 1
'''
          threshold: 0
          timeAggregation: 'Count'
        }
      ]
    }
    description: 'Detects when ${job.id} has no terminal lifecycle event within ${job.monitoring.maxSilenceMinutes} minutes.'
    displayName: 'Container job stale - ${job.id} (${environmentName})'
    enabled: true
    evaluationFrequency: 'PT1H'
    muteActionsDuration: 'PT1H'
    overrideQueryTimeRange: 'P2D'
    scopes: [
      workspaceId
    ]
    severity: 3
    skipQueryValidation: false
    windowSize: 'PT1H'
  }
}]

resource overlapAlerts 'Microsoft.Insights/scheduledQueryRules@2023-12-01' = [for job in overlapAlertJobs: {
  name: take('alert-batchjobs-${environmentName}-${job.id}-overlap', 260)
  location: location
  tags: tags
  properties: {
    actions: {
      actionGroups: actionGroupIds
      customProperties: {
        job_id: job.id
        signal: 'repeated-overlap'
      }
    }
    autoMitigate: false
    criteria: {
      allOf: [
        {
          failingPeriods: {
            minFailingPeriodsToAlert: 1
            numberOfEvaluationPeriods: 1
          }
          operator: 'GreaterThan'
          query: '''
ContainerAppConsoleLogs_CL
| extend lifecycle = parse_json(Log_s)
| where tostring(lifecycle.schema) == 'batchjobs.lifecycle.v1'
| where tostring(lifecycle.job_id) == '${job.id}' and tostring(lifecycle.event) == 'skipped_overlap'
| summarize OverlapSkips = count()
| where OverlapSkips >= 3
'''
          threshold: 0
          timeAggregation: 'Count'
        }
      ]
    }
    description: 'Detects three or more overlap skips for ${job.id} within one hour.'
    displayName: 'Container job repeated overlap - ${job.id} (${environmentName})'
    enabled: true
    evaluationFrequency: 'PT15M'
    muteActionsDuration: 'PT1H'
    scopes: [
      workspaceId
    ]
    severity: 3
    skipQueryValidation: false
    windowSize: 'PT1H'
  }
}]

var staleAlertIds = [for (job, index) in staleAlertJobs: staleAlerts[index].id]
var overlapAlertIds = [for (job, index) in overlapAlertJobs: overlapAlerts[index].id]

output workbookId string = operationsWorkbook.id
output workbookName string = operationsWorkbook.name
output alertRuleIds array = concat(
  length(failureAlertJobs) > 0 ? [failureAlert.id] : [],
  staleAlertIds,
  overlapAlertIds
)
