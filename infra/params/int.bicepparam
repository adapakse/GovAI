using '../instance.bicep'

param instanceName = 'int'
param location = 'polandcentral'
// Standard_B2s ma zatwierdzoną quotę 0 na tej subskrypcji (i cała rodzina
// B-series/D*sv5) — patrz opis parametru vmSize w instance.bicep. Do zmiany
// po zaakceptowaniu wniosku o quotę.
param vmSize = 'Standard_D2s_v3'
param gitBranch = 'develop'
// Microsoft.DevTestLab/schedules (auto-shutdown) nie jest dostępne w
// polandcentral — brak taniej opcji auto-shutdown dopóki VM tu zostaje.
param enableAutoShutdown = false
param autoShutdownTime = '2000'

// Per-operator, nie commitowane wprost — patrz infra/README.md.
param adminIpRange = readEnvironmentVariable('GOVAI_ADMIN_IP_RANGE')
param adminSshPublicKey = readEnvironmentVariable('GOVAI_ADMIN_SSH_PUBLIC_KEY')
