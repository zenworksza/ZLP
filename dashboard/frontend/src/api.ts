const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://localhost:8000';

export const TOKEN_KEY = 'zlp_dashboard_token';

export function getStoredToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setStoredToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearStoredToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export type Product = {
  id: string;
  name: string;
  slug: string;
  created_at: string;
  key_count: number;
};

export type Key = {
  id: string;
  key: string;
  plan: string;
  seats: number;
  status: string;
  customer_ref: string | null;
  customer_email: string | null;
  renewal_period_days: number | null;
  expires_at: string | null;
  product_slug: string;
  product_name: string;
  install_count: number;
  created_at: string;
};

export type Invoice = {
  id: string;
  license_key_id: string;
  invoice_number: string;
  period_days: number;
  period_start: string;
  period_end: string;
  amount_cents: number;
  currency: string;
  status: string;
  due_date: string;
  sent_at: string | null;
  paid_at: string | null;
  created_at: string;
  license_key?: string;
  customer_email?: string | null;
  product_name?: string;
  plan?: string;
};

export type Install = {
  install_id: string;
  domain: string;
  status: string;
  last_heartbeat: string | null;
  first_seen: string;
  license_key: string;
  product: string;
  plan: string;
  anomaly_score?: number | null;
};

export type HeartbeatEntry = {
  id: string;
  install_id: string;
  timestamp: string;
  latency_ms: number | null;
  response_status: string;
};

export type Anomaly = {
  id: string;
  install_id: string;
  score: number;
  reason: string;
  triggered_at: string;
  resolved_at: string | null;
};

export type AuditEntry = {
  id: string;
  actor: string;
  action: string;
  target_type: string | null;
  target_id: string | null;
  timestamp: string;
};

export type PlanTier = {
  id: string;
  product_id: string;
  slug: string;
  display_name: string;
  default_seats: number;
  max_seats: number | null;
  features: string[];
  sort_order: number;
  price_cents: number | null;
  created_at: string;
};

export type Stats = {
  total_installs: number;
  active: number;
  blocked: number;
  anomalous: number;
  total_keys: number;
  unresolved_alerts: number;
};

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const token = getStoredToken();
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const res = await fetch(`${BASE}${path}`, {
    headers: { ...headers, ...(options?.headers ?? {}) },
    ...options,
  });
  if (res.status === 401 || res.status === 403) {
    clearStoredToken();
    window.location.reload();
  }
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  getStats(): Promise<Stats> {
    return request<Stats>('/dashboard/stats');
  },

  getPlans(productId?: string): Promise<PlanTier[]> {
    const qs = productId ? `?product_id=${encodeURIComponent(productId)}` : '';
    return request<PlanTier[]>(`/dashboard/plans${qs}`);
  },

  getPlansBySlug(productSlug: string): Promise<PlanTier[]> {
    return request<PlanTier[]>(`/dashboard/plans/by-product-slug/${encodeURIComponent(productSlug)}`);
  },

  createPlan(body: {
    product_id: string;
    slug: string;
    display_name: string;
    default_seats: number;
    max_seats?: number | null;
    features: string[];
    sort_order?: number;
  }): Promise<PlanTier> {
    return request<PlanTier>('/dashboard/plans', { method: 'POST', body: JSON.stringify(body) });
  },

  updatePlan(id: string, body: Partial<Omit<PlanTier, 'id' | 'product_id' | 'slug' | 'created_at'>> & { price_cents?: number | null }): Promise<PlanTier> {
    return request<PlanTier>(`/dashboard/plans/${id}`, { method: 'PATCH', body: JSON.stringify(body) });
  },

  deletePlan(id: string): Promise<{ deleted: boolean }> {
    return request<{ deleted: boolean }>(`/dashboard/plans/${id}`, { method: 'DELETE' });
  },

  seedPlans(productSlug: string): Promise<{ seeded: string[]; product_slug: string }> {
    return request(`/dashboard/plans/seed/${encodeURIComponent(productSlug)}`, { method: 'POST' });
  },

  getProducts(): Promise<Product[]> {
    return request<Product[]>('/dashboard/products');
  },

  createProduct(body: { name: string; slug: string }): Promise<Product> {
    return request<Product>('/dashboard/products', {
      method: 'POST',
      body: JSON.stringify(body),
    });
  },

  deleteProduct(id: string): Promise<{ deleted: boolean }> {
    return request<{ deleted: boolean }>(`/dashboard/products/${id}`, { method: 'DELETE' });
  },

  getKeys(productId?: string): Promise<Key[]> {
    const qs = productId ? `?product_id=${encodeURIComponent(productId)}` : '';
    return request<Key[]>(`/dashboard/keys${qs}`);
  },

  createKey(body: {
    product_id: string;
    plan: string;
    seats: number;
    expires_at?: string;
    customer_ref?: string;
    renewal_period_days?: number | null;
    customer_email?: string;
  }): Promise<Key> {
    return request<Key>('/dashboard/keys', {
      method: 'POST',
      body: JSON.stringify(body),
    });
  },

  updateKey(id: string, body: Partial<Pick<Key, 'status' | 'customer_ref' | 'customer_email' | 'renewal_period_days' | 'seats' | 'expires_at'>>): Promise<Key> {
    return request<Key>(`/dashboard/keys/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    });
  },

  revokeKey(id: string): Promise<{ revoked: boolean }> {
    return request<{ revoked: boolean }>(`/dashboard/keys/${id}/revoke`, {
      method: 'POST',
    });
  },

  getInstalls(params?: { key_id?: string; status?: string }): Promise<Install[]> {
    const qs = new URLSearchParams();
    if (params?.key_id) qs.set('key_id', params.key_id);
    if (params?.status) qs.set('status', params.status);
    const q = qs.toString();
    return request<Install[]>(`/dashboard/installs${q ? `?${q}` : ''}`);
  },

  getInstall(installId: string): Promise<Install> {
    return request<Install>(`/dashboard/installs/${installId}`);
  },

  blockInstall(installId: string): Promise<{ blocked: boolean }> {
    return request<{ blocked: boolean }>(`/dashboard/installs/${installId}/block`, {
      method: 'POST',
    });
  },

  getHeartbeats(installId: string, limit = 50): Promise<HeartbeatEntry[]> {
    return request<HeartbeatEntry[]>(
      `/dashboard/installs/${installId}/heartbeats?limit=${limit}`,
    );
  },

  getAnomalies(resolved?: boolean): Promise<Anomaly[]> {
    const qs = resolved !== undefined ? `?resolved=${resolved}` : '';
    return request<Anomaly[]>(`/dashboard/anomalies${qs}`);
  },

  resolveAnomaly(id: string): Promise<{ resolved: boolean }> {
    return request<{ resolved: boolean }>(`/dashboard/anomalies/${id}/resolve`, {
      method: 'POST',
    });
  },

  getAudit(limit = 100, offset = 0): Promise<AuditEntry[]> {
    return request<AuditEntry[]>(`/dashboard/audit?limit=${limit}&offset=${offset}`);
  },

  getInvoices(params?: { key_id?: string; status?: string }): Promise<Invoice[]> {
    const qs = new URLSearchParams();
    if (params?.key_id) qs.set('key_id', params.key_id);
    if (params?.status) qs.set('status', params.status);
    const q = qs.toString();
    return request<Invoice[]>(`/dashboard/invoices${q ? `?${q}` : ''}`);
  },

  markInvoicePaid(id: string): Promise<Invoice & { new_expires_at: string | null }> {
    return request(`/dashboard/invoices/${id}/mark-paid`, { method: 'POST' });
  },

  resendInvoice(id: string): Promise<Invoice & { emailed: boolean }> {
    return request(`/dashboard/invoices/${id}/resend`, { method: 'POST' });
  },

  voidInvoice(id: string): Promise<Invoice> {
    return request(`/dashboard/invoices/${id}/void`, { method: 'POST' });
  },
};

export function formatRelative(dateStr: string | null | undefined): string {
  if (!dateStr) return 'never';
  const diff = Date.now() - new Date(dateStr).getTime();
  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} hr ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '—';
  return new Date(dateStr).toLocaleString('en-GB', {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}
