export type User = { username: string; role: string; display_name: string };
export type EngineId = "qoder" | "cursor";

export type QuotaBucket = {
  used?: number | null;
  total?: number | null;
  remaining?: number | null;
  percentage?: number | null;
  unit?: string;
  exceeded?: boolean;
  text?: string;
  note?: string;
};

export type EngineStatus = {
  ok: boolean;
  engine?: EngineId;
  installed: boolean;
  auth: string;
  auth_label: string;
  fallback_reason?: string | null;
  login_help?: string;
  account?: { id?: string; type?: string; label: string };
  quota?: {
    exceeded: boolean;
    text: string;
    lines?: string[];
    plan?: QuotaBucket | null;
    other?: QuotaBucket | null;
    add_on?: QuotaBucket | null;
    shared?: QuotaBucket | null;
  } | null;
  expires_at?: string;
  hint?: string;
  loading?: boolean;
  error?: string | null;
};

export type EnginesPayload = {
  ok: boolean;
  active: EngineId;
  defaults: { engine: EngineId; models: Record<EngineId, string> };
  qoder: EngineStatus;
  cursor: EngineStatus;
};

export type SettingsPayload = {
  engine: EngineId;
  models: Record<EngineId, string>;
  workspace: string;
  timeout_sec: number;
  max_concurrency: number;
  max_turns: number;
  listen: string;
  base_url: string;
  proxy_key_hint: string;
  cursor_key_hint?: string;
  qoder_key_hint?: string;
  restart_hint: string;
};

export type HermesField = { id: string; label: string; value: string; hint?: string; secret?: boolean };

export type HermesConnect = {
  choice: string;
  choice_label: string;
  also_ok: string;
  howto: string;
  fields: HermesField[];
  snippet: string;
};

export type SecretHints = {
  ok?: boolean;
  proxy_key_hint: string;
  cursor_key_hint: string;
  qoder_key_hint: string;
};

export type ModelItem = { id: string; label: string };

export type ParseStats = {
  ok: boolean;
  last: { kind: string; label: string; tools: string[]; preview: string };
  counts: { fence_ok: number; text: number; degraded: number };
};

async function parseError(response: Response): Promise<string> {
  const text = await response.text();
  try {
    const data = JSON.parse(text) as { detail?: string; error?: { message?: string } };
    return data.detail || data.error?.message || text || `HTTP ${response.status}`;
  } catch {
    return text || `HTTP ${response.status}`;
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return (await response.json()) as T;
}
