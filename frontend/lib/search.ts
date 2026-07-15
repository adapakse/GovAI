// Wspólna logika filtrowania tekstowego dla długich list.
//
// matchesQuery — dzieli zapytanie na tokeny (spacje) i wymaga, by KAŻDY token
// występował w połączonym tekście pól (AND). Dzięki temu "bielik high" znajdzie
// agenta pasującego jednocześnie do obu fraz. Puste zapytanie = wszystko.

export function matchesQuery(fields: Array<string | null | undefined>, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  const hay = fields.filter(Boolean).join(' ').toLowerCase();
  return q.split(/\s+/).every(term => hay.includes(term));
}

// providerFieldsForModel — zwraca nazwy i typy providerów obsługujących dany
// model_id, do włączenia w indeks wyszukiwania agenta (szukanie "po providerze").
export function providerFieldsForModel(
  model_id: string,
  providers: Array<{ name: string; provider_type: string; model_ids: string[] }>,
): string[] {
  const out: string[] = [];
  for (const p of providers) {
    if (p.model_ids?.includes(model_id)) {
      out.push(p.name, p.provider_type);
    }
  }
  return out;
}
