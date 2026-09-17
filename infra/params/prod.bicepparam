using '../instance.bicep'

param instanceName = 'prod'
param location = 'polandcentral'
// Standard_B2s ma zatwierdzoną quotę 0 na tej subskrypcji (i cała rodzina
// B-series/D*sv5) — patrz opis parametru vmSize w instance.bicep. Do zmiany
// po zaakceptowaniu wniosku o quotę.
param vmSize = 'Standard_D2s_v3'
param gitBranch = 'main'
// Domena publiczna — po weryfikacji PROD, DNS dla govai.pl zostaje
// przełączony tu z INT (patrz ENVIRONMENTS.md — INT wraca do roli czysto
// wewnętrznej, bez własnej domeny).
param domainName = 'govai.pl'
// Wymóg 24/7 dla instancji produkcyjnej — nigdy auto-shutdown (patrz opis
// parametru w instance.bicep).
param enableAutoShutdown = false
param autoShutdownTime = '2000'

// Per-operator, nie commitowane wprost — patrz infra/README.md.
param adminIpRange = readEnvironmentVariable('GOVAI_ADMIN_IP_RANGE')
param adminSshPublicKey = readEnvironmentVariable('GOVAI_ADMIN_SSH_PUBLIC_KEY')
