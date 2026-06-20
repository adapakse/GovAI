import { clearSession, ensureFreshToken } from './auth';

const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';
export const WS  = process.env.NEXT_PUBLIC_WS_URL  ?? 'ws://localhost:8000';

async function authHeaders(): Promise<Record<string, string>> {
  const token = await ensureFreshToken();
  if (!token) return { 'Content-Type': 'application/json' };
  return { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` };
}

function handle401() {
  clearSession();
  if (typeof window !== 'undefined') window.location.href = '/login';
}

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${API}${path}`, {
    cache: 'no-store',
    headers: await authHeaders(),
  });
  if (r.status === 401) { handle401(); throw new Error('Sesja wygasła'); }
  if (!r.ok) throw new Error(`GET ${path} → ${r.status}`);
  return r.json();
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(`${API}${path}`, {
    method: 'POST',
    headers: await authHeaders(),
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (r.status === 401) { handle401(); throw new Error('Sesja wygasła'); }
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(err?.detail ?? `POST ${path} → ${r.status}`);
  }
  return r.json();
}

async function patch<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`${API}${path}`, {
    method: 'PATCH',
    headers: await authHeaders(),
    body: JSON.stringify(body),
  });
  if (r.status === 401) { handle401(); throw new Error('Sesja wygasła'); }
  if (!r.ok) throw new Error(`PATCH ${path} → ${r.status}`);
  return r.json();
}

async function put<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`${API}${path}`, {
    method: 'PUT',
    headers: await authHeaders(),
    body: JSON.stringify(body),
  });
  if (r.status === 401) { handle401(); throw new Error('Sesja wygasła'); }
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(err?.detail ?? `PUT ${path} → ${r.status}`);
  }
  return r.json();
}

async function del<T>(path: string): Promise<T> {
  const r = await fetch(`${API}${path}`, {
    method: 'DELETE',
    headers: await authHeaders(),
  });
  if (r.status === 401) { handle401(); throw new Error('Sesja wygasła'); }
  if (!r.ok) throw new Error(`DELETE ${path} → ${r.status}`);
  return r.json();
}

// ── Typy ────────────────────────────────────────────────────────────────────

export type RiskLevel = 'minimal' | 'limited' | 'high' | 'unacceptable';
export type AgentStatus = 'active' | 'suspended' | 'quarantined' | 'retired';
export type PolicyResult = 'allowed' | 'blocked' | 'oversight_required';
export type OversightStatus = 'pending' | 'approved' | 'rejected' | 'escalated';

export type DeclStatus = 'yes' | 'no' | 'partial' | 'na' | '';

export interface ComplianceDecl {
  [key: string]: { status: DeclStatus; notes: string };
}

export interface Agent {
  id: string;
  name: string;
  description: string;
  owner_name: string;
  owner_email: string;
  team: string;
  risk_level: RiskLevel;
  annex_iii_cat: string | null;
  legal_basis: string | null;
  status: AgentStatus;
  requires_oversight: boolean;
  model_id: string;
  monthly_budget_eur: number;
  allowed_data_cats: string[];
  created_at: string;
  updated_at: string;
  // v3 registry fields
  version: string | null;
  last_reviewed_at: string | null;
  next_review_date: string | null;
  compliance_decl: ComplianceDecl | null;
  processes_personal_data: boolean;
  gdpr_legal_basis: string | null;
  data_retention_days: number | null;
  intended_purpose: string | null;
  intended_users: string | null;
  geographic_scope: string | null;
  input_modalities: string[];
  output_modalities: string[];
  integration_points: string[];
  model_version: string | null;
  technical_contact_email: string | null;
  compliance_officer_email: string | null;
  cost_alert_threshold_eur: number | null;
}

export interface OversightTask {
  id: string;
  agent_id: string;
  agent_name: string;
  risk_level: RiskLevel;
  task_id: string;
  decision_type: string;
  agent_decision: string;
  confidence: number | null;
  status: OversightStatus;
  ttl_expires_at: string;
  created_at: string;
}

export interface AuditEntry {
  time: string;
  id: string;
  agent_id: string;
  agent_name: string;
  task_id: string;
  call_id: string;
  event_type: string;
  policy_result: PolicyResult;
  pii_categories: string[];
  pii_count: number;
  latency_ms: number | null;
  cost_eur: number | null;
  block_reason: string | null;
  input_hash: string | null;
}

export interface DashboardSummary {
  period_days: number;
  agents: { total: number; active: number; suspended: number; high_risk: number };
  calls: {
    total_calls: number; blocked: number; oversight_required: number;
    pii_calls: number; total_cost_eur: number; avg_latency_ms: number | null;
  };
  pending_oversight: number;
  top_agents: { agent_name: string; calls: number; blocked: number; cost_eur: number }[];
  recent_alerts: { time: string; agent_name: string; event_type: string; policy_result: string; block_reason: string | null }[];
}

export interface Policy {
  id: string;
  name: string;
  policy_code: string | null;
  level: 'org' | 'team' | 'agent';
  rule_type: 'allow' | 'deny' | 'require_oversight';
  condition_json: { keywords?: string[]; [key: string]: unknown };
  action_json: { reason?: string; [key: string]: unknown };
  priority: number;
  active: boolean;
  version: number;
  created_by: string | null;
  created_at: string;
}

export interface AiActRequirement {
  id: string;
  risk_level: RiskLevel;
  article_ref: string;
  requirement_title: string;
  requirement_text: string;
  active: boolean;
  sort_order: number;
  created_at: string;
}

export type DataSensitivityLevel = 'public' | 'internal' | 'confidential' | 'privileged';
export type ProviderType = 'openai' | 'anthropic' | 'deepseek' | 'google' | 'bielik' | 'ollama' | 'vllm' | 'custom';

export interface Provider {
  id: string;
  name: string;
  provider_type: ProviderType;
  model_ids: string[];
  base_url: string | null;
  api_key_env: string | null;
  max_data_sensitivity: DataSensitivityLevel;
  active: boolean;
  priority: number;
  is_healthy: boolean;
  last_health_check_at: string | null;
  notes: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface ComplianceReport {
  agent_id: string;
  agent_name: string;
  risk_level: RiskLevel;
  status: 'compliant' | 'gaps_found' | 'critical';
  gaps_count: number;
  gaps: { article: string; title: string; description: string; severity: string; action: string; deadline_days: number }[];
  obligations: string[];
  summary: string;
}

// ── API calls ────────────────────────────────────────────────────────────────

export const api = {
  dashboard: {
    summary: (days = 7) => get<DashboardSummary>(`/dashboard/summary?days=${days}`),
    timeline: (hours = 24) =>
      get<{ hour: string; total: number; blocked: number; oversight: number }[]>(
        `/dashboard/timeline?hours=${hours}`
      ),
  },
  agents: {
    list: (params?: Record<string, string>) => {
      const q = params ? '?' + new URLSearchParams(params).toString() : '';
      return get<Agent[]>(`/agents${q}`);
    },
    get: (id: string) => get<Agent>(`/agents/${id}`),
    create: (body: unknown) => post<Agent>('/agents', body),
    updateStatus: (id: string, status: AgentStatus) => patch(`/agents/${id}/status`, { status }),
    updateRegistry: (id: string, body: unknown) => patch(`/agents/${id}/registry`, body),
    compliance: (id: string) => get<ComplianceReport>(`/agents/${id}/compliance`),
    stats: (id: string, days = 30) => get(`/agents/${id}/stats?days=${days}`),
  },
  oversight: {
    pending: () => get<OversightTask[]>('/oversight/pending'),
    startReview: (id: string) => post(`/oversight/${id}/start-review`),
    review: (id: string, action: string, comment?: string) =>
      post(`/oversight/${id}/review`, { action, comment }),
    history: (days = 30) => get(`/oversight/history?days=${days}`),
  },
  audit: {
    list: (params?: Record<string, string>) => {
      const q = params ? '?' + new URLSearchParams(params).toString() : '';
      return get<AuditEntry[]>(`/audit${q}`);
    },
    summary: (days = 7) => get(`/audit/summary?days=${days}`),
  },
  reports: {
    agentPdfUrl: (id: string) => `${API}/agents/${id}/report/pdf`,
  },
  policies: {
    list: () => get<Policy[]>('/policies?active_only=false'),
    toggle: (id: string) => patch<Policy>(`/policies/${id}/toggle`, {}),
    updateKeywords: (id: string, keywords: string[]) =>
      patch<Policy>(`/policies/${id}/keywords`, { keywords }),
    create: (body: unknown) => post<Policy>('/policies', body),
  },
  compliance: {
    list: () => get<AiActRequirement[]>('/compliance'),
    create: (body: unknown) => post<AiActRequirement>('/compliance', body),
    update: (id: string, body: unknown) => put<AiActRequirement>(`/compliance/${id}`, body),
    delete: (id: string) => del<{ deleted: string }>(`/compliance/${id}`),
  },
  providers: {
    list: (activeOnly = false) => get<Provider[]>(`/providers${activeOnly ? '?active_only=true' : ''}`),
    get: (id: string) => get<Provider>(`/providers/${id}`),
    create: (body: unknown) => post<Provider>('/providers', body),
    update: (id: string, body: unknown) => patch<Provider>(`/providers/${id}`, body),
    delete: (id: string) => del<{ deleted: string; name: string }>(`/providers/${id}`),
    setHealth: (id: string, healthy: boolean) =>
      patch<Provider>(`/providers/${id}/health?healthy=${healthy}`, {}),
  },
  demo: {
    scenarios: () =>
      get<Record<string, Record<string, { label: string; description: string; expected: string }>>>(
        '/demo/scenarios'
      ),
    seedStatus: () =>
      get<{ seeded: boolean; audit_entries: number; oversight_items: number }>('/demo/seed/status'),
    seed: () =>
      post<{ message?: string; seeded_audit_entries?: number }>('/demo/seed'),
    reset: () =>
      del<{ deleted_audit_entries: number; deleted_oversight_entries: number }>('/demo/seed'),
    run: (agent_id: string, scenario: string) =>
      post<Record<string, unknown>>('/demo/run', { agent_id, scenario }),
  },
};
