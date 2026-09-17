// Zasoby jednej instancji GovAI wewnątrz jej dedykowanej resource group.
// Wywoływane przez instance.bicep — nie deployuj tego pliku bezpośrednio.
param instanceName string
param location string
param vmSize string
param gitBranch string
param gitRepoUrl string
param adminIpRange string
param domainName string
param enableAutoShutdown bool
param autoShutdownTime string
param adminSshPublicKey string

var namePrefix = 'govai-${instanceName}'
// Key Vault: max 24 znaki, tylko litery/cyfry/myślniki
var keyVaultName = take('kv-${namePrefix}', 24)

// ── Sieć ─────────────────────────────────────────────────────────────────

resource nsg 'Microsoft.Network/networkSecurityGroups@2023-09-01' = {
  name: 'nsg-${namePrefix}'
  location: location
  properties: {
    securityRules: [
      {
        name: 'allow-https'
        properties: {
          priority: 100
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: '*'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '443'
        }
      }
      {
        name: 'allow-http'
        properties: {
          priority: 110
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: '*'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '80'
        }
      }
      {
        name: 'allow-ssh-admin'
        properties: {
          priority: 120
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: adminIpRange
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '22'
        }
      }
    ]
  }
}

resource vnet 'Microsoft.Network/virtualNetworks@2023-09-01' = {
  name: 'vnet-${namePrefix}'
  location: location
  properties: {
    addressSpace: {
      addressPrefixes: ['10.10.0.0/24']
    }
    subnets: [
      {
        name: 'default'
        properties: {
          addressPrefix: '10.10.0.0/24'
          networkSecurityGroup: { id: nsg.id }
        }
      }
    ]
  }
}

resource publicIp 'Microsoft.Network/publicIPAddresses@2023-09-01' = {
  name: 'pip-${namePrefix}'
  location: location
  sku: { name: 'Standard' }
  properties: {
    publicIPAllocationMethod: 'Static'
  }
}

resource nic 'Microsoft.Network/networkInterfaces@2023-09-01' = {
  name: 'nic-${namePrefix}'
  location: location
  properties: {
    ipConfigurations: [
      {
        name: 'ipconfig1'
        properties: {
          privateIPAllocationMethod: 'Dynamic'
          subnet: { id: vnet.properties.subnets[0].id }
          publicIPAddress: { id: publicIp.id }
        }
      }
    ]
  }
}

// ── Tożsamość + Key Vault ───────────────────────────────────────────────

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-${namePrefix}'
  location: location
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  properties: {
    sku: { family: 'A', name: 'standard' }
    tenantId: subscription().tenantId
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 90
    // Publiczny z firewallem — private endpoint odłożone do realnego wdrożenia
    // klienckiego (patrz docs/PRODUCTION_READINESS_BACKLOG.md, 1.7).
    networkAcls: {
      defaultAction: 'Allow'
      bypass: 'AzureServices'
    }
  }
}

var keyVaultSecretsUserRoleId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6'
)
var keyVaultSecretsOfficerRoleId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions', 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7'
)

// VM-owa tożsamość czyta sekrety w runtime (fetch-secrets.sh)
resource kvReaderAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, identity.id, 'secrets-user')
  scope: keyVault
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: keyVaultSecretsUserRoleId
  }
}

// Osobna tożsamość — tylko do jednorazowego zasiania sekretów przy deployu
resource seedIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-${namePrefix}-seed'
  location: location
}

resource kvSeedAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, seedIdentity.id, 'secrets-officer')
  scope: keyVault
  properties: {
    principalId: seedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: keyVaultSecretsOfficerRoleId
  }
}

// Generuje jwt-secret/db-password losowo (idempotentnie — nie nadpisuje przy
// redeployu). anthropic-api-key/deepseek-api-key dostają placeholder — GovAI
// nigdy nie przechowuje prawdziwych kluczy klienta, admin uzupełnia ręcznie
// po deployu (patrz infra/README.md).
resource seedSecrets 'Microsoft.Resources/deploymentScripts@2023-08-01' = {
  name: 'ds-${namePrefix}-seed-secrets'
  location: location
  kind: 'AzureCLI'
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${seedIdentity.id}': {}
    }
  }
  properties: {
    azCliVersion: '2.60.0'
    retentionInterval: 'PT1H'
    timeout: 'PT10M'
    cleanupPreference: 'OnSuccess'
    environmentVariables: [
      { name: 'VAULT_NAME', value: keyVault.name }
    ]
    scriptContent: '''
      set -e
      for name in jwt-secret db-password; do
        if ! az keyvault secret show --vault-name "$VAULT_NAME" --name "$name" >/dev/null 2>&1; then
          az keyvault secret set --vault-name "$VAULT_NAME" --name "$name" --value "$(python3 -c 'import secrets; print(secrets.token_hex(32))')" >/dev/null
        fi
      done
      for name in anthropic-api-key deepseek-api-key; do
        if ! az keyvault secret show --vault-name "$VAULT_NAME" --name "$name" >/dev/null 2>&1; then
          az keyvault secret set --vault-name "$VAULT_NAME" --name "$name" --value "ZMIEN_MNIE_PO_DEPLOYU" >/dev/null
        fi
      done
    '''
  }
  dependsOn: [
    kvSeedAssignment
  ]
}

// ── VM ───────────────────────────────────────────────────────────────────

// Bicep NIE interpoluje ${} wewnątrz stringów wielolinijkowych ('''...''') —
// zostają dosłownym tekstem. Stąd osobne tokeny podstawiane przez replace()
// zamiast normalnej interpolacji.
var cloudInitTemplate = '''#cloud-config
package_update: true
packages:
  - ca-certificates
  - curl
  - gnupg
  - git
  - jq
write_files:
  - path: /opt/govai-azure.env
    content: |
      AZURE_CLIENT_ID=@@CLIENT_ID@@
      AZURE_KEY_VAULT_NAME=@@KV_NAME@@
      SECRETS_BACKEND=azure-keyvault
      DOMAIN_NAME=@@DOMAIN_NAME@@
runcmd:
  - install -m 0755 -d /etc/apt/keyrings
  - curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  - chmod a+r /etc/apt/keyrings/docker.asc
  - echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" > /etc/apt/sources.list.d/docker.list
  - apt-get update
  - apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
  - usermod -aG docker govaiadmin
  - mkdir -p /opt/govai
  - git clone --branch @@GIT_BRANCH@@ @@GIT_REPO_URL@@ /opt/govai || (cd /opt/govai && git fetch && git checkout @@GIT_BRANCH@@ && git pull)
  - chown -R govaiadmin:govaiadmin /opt/govai /opt/govai-azure.env
'''

var cloudInit = replace(replace(replace(replace(replace(
  cloudInitTemplate,
  '@@CLIENT_ID@@', identity.properties.clientId),
  '@@KV_NAME@@', keyVault.name),
  '@@DOMAIN_NAME@@', domainName),
  '@@GIT_BRANCH@@', gitBranch),
  '@@GIT_REPO_URL@@', gitRepoUrl)

resource vm 'Microsoft.Compute/virtualMachines@2024-03-01' = {
  name: 'vm-${namePrefix}'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identity.id}': {}
    }
  }
  properties: {
    hardwareProfile: { vmSize: vmSize }
    osProfile: {
      computerName: take('govai-${instanceName}', 15)
      adminUsername: 'govaiadmin'
      linuxConfiguration: {
        disablePasswordAuthentication: true
        ssh: {
          publicKeys: [
            {
              path: '/home/govaiadmin/.ssh/authorized_keys'
              keyData: adminSshPublicKey
            }
          ]
        }
      }
      customData: base64(cloudInit)
    }
    storageProfile: {
      imageReference: {
        publisher: 'Canonical'
        offer: '0001-com-ubuntu-server-jammy'
        sku: '22_04-lts-gen2'
        version: 'latest'
      }
      osDisk: {
        createOption: 'FromImage'
        managedDisk: { storageAccountType: 'StandardSSD_LRS' }
      }
    }
    networkProfile: {
      networkInterfaces: [
        { id: nic.id }
      ]
    }
  }
}

resource autoShutdown 'Microsoft.DevTestLab/schedules@2018-09-15' = if (enableAutoShutdown) {
  name: 'shutdown-computevm-${vm.name}'
  location: location
  properties: {
    status: 'Enabled'
    taskType: 'ComputeVmShutdownTask'
    dailyRecurrence: { time: autoShutdownTime }
    timeZoneId: 'Central European Standard Time'
    targetResourceId: vm.id
    notificationSettings: { status: 'Disabled' }
  }
}

output vmPublicIp string = publicIp.properties.ipAddress
output keyVaultName string = keyVault.name
output managedIdentityClientId string = identity.properties.clientId
