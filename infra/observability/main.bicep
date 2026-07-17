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

var workbookName = guid(resourceGroup().id, environmentName, 'container-jobs-operations')
var workbookDefinition = replace(loadTextContent('workbook.json'), '__WORKSPACE_ID__', workspaceId)

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




output workbookId string = operationsWorkbook.id
output workbookName string = operationsWorkbook.name
output alertRuleIds array = []
