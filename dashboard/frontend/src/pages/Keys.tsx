import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, formatDate, type Key, type Product, type PlanTier } from '../api';
import { StatusBadge } from '../components/StatusBadge';
import { Table } from '../components/Table';

export default function Keys() {
  const [keys, setKeys] = useState<Key[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [plans, setPlans] = useState<PlanTier[]>([]);
  const [filterProduct, setFilterProduct] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showForm, setShowForm] = useState(false);
  const [formError, setFormError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [form, setForm] = useState({
    product_id: '',
    plan: '',
    seats: '1',
    customer_ref: '',
    customer_email: '',
    renewal_period_days: '30',
    expires_at: '',
  });
  const navigate = useNavigate();

  const selectedPlan = plans.find((p) => p.slug === form.plan) ?? null;

  const loadKeys = (productId?: string) => {
    setLoading(true);
    api
      .getKeys(productId || undefined)
      .then(setKeys)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    api.getProducts().then(setProducts).catch(() => {});
    loadKeys();
  }, []);

  const handleProductChange = (productId: string) => {
    setForm((f) => ({ ...f, product_id: productId, plan: '', seats: '1' }));
    setPlans([]);
    if (!productId) return;
    const product = products.find((p) => p.id === productId);
    if (!product) return;
    api.getPlansBySlug(product.slug).then((tiers) => {
      setPlans(tiers);
      if (tiers.length > 0) {
        setForm((f) => ({ ...f, plan: tiers[0].slug, seats: String(tiers[0].default_seats) }));
      }
    }).catch(() => {});
  };

  const handlePlanChange = (planSlug: string) => {
    const tier = plans.find((p) => p.slug === planSlug);
    setForm((f) => ({
      ...f,
      plan: planSlug,
      seats: tier ? String(tier.default_seats) : f.seats,
    }));
  };

  const handleFilterChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    setFilterProduct(e.target.value);
    loadKeys(e.target.value || undefined);
  };

  const handleRevoke = (k: Key, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm(`Revoke key ${k.key}? This cannot be undone.`)) return;
    api
      .revokeKey(k.id)
      .then(() => {
        setKeys((prev) => prev.map((item) => (item.id === k.id ? { ...item, status: 'revoked' } : item)));
      })
      .catch((err: Error) => alert(`Failed to revoke: ${err.message}`));
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.product_id) {
      setFormError('Select a product.');
      return;
    }
    setSubmitting(true);
    setFormError('');
    const renewal = form.renewal_period_days ? parseInt(form.renewal_period_days, 10) : null;
    api
      .createKey({
        product_id: form.product_id,
        plan: form.plan,
        seats: parseInt(form.seats, 10) || 1,
        customer_ref: form.customer_ref || undefined,
        customer_email: form.customer_email || undefined,
        renewal_period_days: renewal,
        expires_at: form.expires_at || undefined,
      })
      .then((k) => {
        setKeys((prev) => [k, ...prev]);
        setShowForm(false);
        setPlans([]);
        setForm({ product_id: '', plan: '', seats: '1', customer_ref: '', customer_email: '', renewal_period_days: '30', expires_at: '' });
      })
      .catch((err: Error) => setFormError(err.message))
      .finally(() => setSubmitting(false));
  };

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-semibold text-gray-800">License Keys</h1>
        <button
          onClick={() => {
            setShowForm((v) => !v);
            setFormError('');
          }}
          className="px-3 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-700"
        >
          {showForm ? 'Cancel' : 'Generate Key'}
        </button>
      </div>

      {showForm && (
        <form onSubmit={handleSubmit} className="mb-6 bg-gray-50 border border-gray-200 rounded p-4 space-y-3">
          <div className="grid grid-cols-3 gap-3">
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-gray-600">Product</label>
              <select
                value={form.product_id}
                onChange={(e) => handleProductChange(e.target.value)}
                className="border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:border-blue-500"
              >
                <option value="">Select product</option>
                {products.map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-gray-600">Plan</label>
              <select
                value={form.plan}
                onChange={(e) => handlePlanChange(e.target.value)}
                disabled={plans.length === 0}
                className="border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:border-blue-500 disabled:bg-gray-100 disabled:text-gray-400"
              >
                {plans.length === 0 && <option value="">Select product first</option>}
                {plans.map((t) => (
                  <option key={t.slug} value={t.slug}>{t.display_name}</option>
                ))}
              </select>
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-gray-600">
                Seats
                {selectedPlan?.max_seats != null && (
                  <span className="ml-1 font-normal text-gray-400">(max {selectedPlan.max_seats})</span>
                )}
              </label>
              <input
                type="number"
                min="1"
                max={selectedPlan?.max_seats ?? undefined}
                value={form.seats}
                onChange={(e) => setForm((f) => ({ ...f, seats: e.target.value }))}
                className="border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:border-blue-500"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-gray-600">Renewal cycle</label>
              <select
                value={form.renewal_period_days}
                onChange={(e) => setForm((f) => ({ ...f, renewal_period_days: e.target.value }))}
                className="border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:border-blue-500"
              >
                <option value="">None (manual expiry)</option>
                <option value="30">Monthly (30 days)</option>
                <option value="90">Quarterly (90 days)</option>
                <option value="180">Semi-annual (180 days)</option>
              </select>
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-gray-600">Customer email <span className="text-gray-400 font-normal">(for invoices)</span></label>
              <input
                type="email"
                value={form.customer_email}
                onChange={(e) => setForm((f) => ({ ...f, customer_email: e.target.value }))}
                className="border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:border-blue-500"
                placeholder="client@example.com"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-gray-600">Customer ref <span className="text-gray-400 font-normal">(optional)</span></label>
              <input
                type="text"
                value={form.customer_ref}
                onChange={(e) => setForm((f) => ({ ...f, customer_ref: e.target.value }))}
                className="border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:border-blue-500"
                placeholder="Acme Corp"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-gray-600">Override expiry <span className="text-gray-400 font-normal">(leave blank to auto-calculate)</span></label>
              <input
                type="date"
                value={form.expires_at}
                onChange={(e) => setForm((f) => ({ ...f, expires_at: e.target.value }))}
                className="border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:border-blue-500"
              />
            </div>
            <div className="flex items-end gap-2">
              <button
                type="submit"
                disabled={submitting || !form.plan}
                className="px-3 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50"
              >
                {submitting ? 'Creating...' : 'Create Key'}
              </button>
              {formError && <p className="text-red-600 text-xs">{formError}</p>}
            </div>
          </div>
          {selectedPlan && selectedPlan.features.length > 0 && (
            <div className="pt-2 border-t border-gray-200">
              <span className="text-xs font-medium text-gray-500 mr-2">Features included:</span>
              {selectedPlan.features.map((f) => (
                <span key={f} className="inline-block mr-1 mb-1 px-1.5 py-0.5 bg-blue-50 text-blue-700 text-xs rounded font-mono">
                  {f}
                </span>
              ))}
            </div>
          )}
        </form>
      )}

      <div className="mb-4 flex items-center gap-3">
        <label className="text-xs font-medium text-gray-600">Filter by product:</label>
        <select
          value={filterProduct}
          onChange={handleFilterChange}
          className="border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:border-blue-500"
        >
          <option value="">All products</option>
          {products.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
      </div>

      {error && <p className="text-red-600 text-sm mb-4">Error: {error}</p>}
      {loading ? (
        <p className="text-gray-500 text-sm">Loading...</p>
      ) : (
        <Table
          columns={[
            {
              key: 'key',
              header: 'Key',
              render: (k) => <code className="text-xs font-mono">{k.key}</code>,
            },
            { key: 'plan', header: 'Plan', render: (k) => <span className="capitalize">{k.plan}</span> },
            { key: 'seats', header: 'Seats', render: (k) => k.seats },
            { key: 'customer_ref', header: 'Customer', render: (k) => k.customer_ref ?? <span className="text-gray-400">—</span> },
            { key: 'status', header: 'Status', render: (k) => <StatusBadge status={k.status} /> },
            { key: 'install_count', header: 'Installs', render: (k) => k.install_count },
            {
              key: 'renewal_period_days',
              header: 'Renewal',
              render: (k) => {
                const label: Record<number, string> = { 30: '30d', 90: '90d', 180: '180d' };
                return k.renewal_period_days
                  ? <span className="text-xs text-blue-600">{label[k.renewal_period_days] ?? `${k.renewal_period_days}d`}</span>
                  : <span className="text-gray-400 text-xs">—</span>;
              },
            },
            {
              key: 'expires_at',
              header: 'Expires',
              render: (k) => {
                if (!k.expires_at) return <span className="text-gray-400 text-xs">Never</span>;
                const daysLeft = Math.ceil((new Date(k.expires_at).getTime() - Date.now()) / 86400000);
                const color = daysLeft <= 14 ? 'text-red-600' : daysLeft <= 30 ? 'text-amber-600' : 'text-gray-500';
                return <span className={`text-xs ${color}`}>{formatDate(k.expires_at)}</span>;
              },
            },
            {
              key: 'created_at',
              header: 'Created',
              render: (k) => <span className="text-xs text-gray-500">{formatDate(k.created_at)}</span>,
            },
            {
              key: 'actions',
              header: '',
              render: (k) =>
                k.status !== 'revoked' ? (
                  <button
                    onClick={(e) => handleRevoke(k, e)}
                    className="text-xs text-red-600 hover:underline"
                  >
                    Revoke
                  </button>
                ) : null,
            },
          ]}
          rows={keys}
          onRowClick={(k) => navigate(`/installs?key_id=${k.id}`)}
        />
      )}
    </div>
  );
}
