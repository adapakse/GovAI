// Szablon jednej instancji GovAI na Azure — VM + Docker Compose, Key Vault,
// Managed Identity. Reużywalny dla INT i dla każdego kolejnego klienta
// hostowanego na Azure GovAI (patrz infra/README.md dla onboardingu).
targetScope = 'subscription'

@description('Krótka nazwa instancji (np. "int" albo nazwa klienta) — używana w nazwach zasobów')
@minLength(2)
@maxLength(20)
param instanceName string

// polandcentral — region, w którym ta subskrypcja już działa (CRMtree), ma
// zatwierdzoną quotę VM (patrz komentarz przy vmSize).
param location string = 'polandcentral'

@description('''
Rozmiar VM. Docelowo burstable B-series (Standard_B2s / _v2) — najtańsze
sensowne dla całego stosu docker-compose — ale ta subskrypcja ma na razie
zatwierdzoną quotę 0 dla wszystkich rodzin B-series (i D*sv5) w każdym
regionie; jedyna rodzina z niezerową quotą to Dsv3. Domyślnie Standard_D2s_v3
(drożej niż burstable) jako tymczasowy, faktycznie działający wybór — po
zaakceptowaniu wniosku o quotę B-series (Azure Portal → Quotas) przełącz z
powrotem i redeployuj, sam VM jest bezstanowy.
''')
param vmSize string = 'Standard_D2s_v3'

@description('Branch repo klonowany przez cloud-init')
param gitBranch string = 'develop'

@description('URL repo git klonowanego przez cloud-init')
param gitRepoUrl string = 'https://github.com/adapakse/GovAI.git'

@description('CIDR dopuszczony do SSH (22), np. "1.2.3.4/32"')
param adminIpRange string

@description('Domena publiczna dla Caddy/ACME — puste = self-signed (tls internal + on_demand)')
param domainName string = ''

@description('Auto-shutdown VM poza godzinami — TYLKO dla środowisk testowych, nigdy dla instancji klienckich (wymóg 24/7)')
param enableAutoShutdown bool = false

@description('Godzina lokalna auto-shutdown w formacie HHmm, np. "2000"')
param autoShutdownTime string = '2000'

@description('Klucz publiczny SSH admina VM')
param adminSshPublicKey string

var resourceGroupName = 'rg-govai-${instanceName}'

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: resourceGroupName
  location: location
  tags: {
    project: 'govai'
    instance: instanceName
  }
}

module resources 'resources.bicep' = {
  name: 'govai-${instanceName}-resources'
  scope: rg
  params: {
    instanceName: instanceName
    location: location
    vmSize: vmSize
    gitBranch: gitBranch
    gitRepoUrl: gitRepoUrl
    adminIpRange: adminIpRange
    domainName: domainName
    enableAutoShutdown: enableAutoShutdown
    autoShutdownTime: autoShutdownTime
    adminSshPublicKey: adminSshPublicKey
  }
}

output vmPublicIp string = resources.outputs.vmPublicIp
output keyVaultName string = resources.outputs.keyVaultName
output managedIdentityClientId string = resources.outputs.managedIdentityClientId
output resourceGroupName string = resourceGroupName
