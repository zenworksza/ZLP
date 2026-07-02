import { useEffect, useState } from 'react';
import { api, type PlanTier, type Product } from '../api';

type PlanForm = {
  slug: string;
  display_name: string;
  default_seats: string;
  max_seats: string;
  features: string;
  sort_order: string;
  price_cents: string;
};

const emptyForm = (): PlanForm => ({
  slug: '',
  display_name: '',
  default_seats: '1',
  max_seats: '',
  features: '',
  sort_order: '0',
  price_cents: '',
});

function parseFeaturesInput(raw: string): string[] {
  return raw
    .split(/[\s,]+/)
    .map((f) => f.trim())
    .filter(Boolean);
}

export default function Plans() {
  const [products, setProducts] = useState<Product[]>([]);
  const [selectedProductId, setSelectedProductId] = useState('');
  const [plans, setPlans] = useState<PlanTier[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<PlanForm>(emptyForm());
  const [formError, setFormError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const selectedProduct = products.find((p) => p.id === selectedProductId) ?? null;

  useEffect(() => {
    api.getProducts().then((ps) => {
      setProducts(ps);
      if (ps.length > 0) setSelectedProductId(ps[0].id);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (!selectedProductId) return;
    setLoading(true);
    setError('');
    api.getPlans(selectedProductId)
      .then(setPlans)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [selectedProductId]);

  const openCreate = () => {
    setEditingId(null);
    setForm(emptyForm());
    setFormError('');
    setShowForm(true);
  };

  const openEdit = (plan: PlanTier) => {
    setEditingId(plan.id);
    setForm({
      slug: plan.slug,
      display_name: plan.display_name,
      default_seats: String(plan.default_seats),
      max_seats: plan.max_seats != null ? String(plan.max_seats) : '',
      features: plan.features.join(', '),
      sort_order: String(plan.sort_order),
      price_cents: plan.price_cents != null ? String(plan.price_cents) : '',
    });
    setFormError('');
    setShowForm(true);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedProductId) return;
    const payload = {
      product_id: selectedProductId,
      slug: form.slug.trim(),
      display_name: form.display_name.trim(),
      default_seats: parseInt(form.default_seats, 10) || 1,
      max_seats: form.max_seats.trim() ? parseInt(form.max_seats, 10) : null,
      features: parseFeaturesInput(form.features),
      sort_order: parseInt(form.sort_order, 10) || 0,
      price_cents: form.price_cents.trim() ? parseInt(form.price_cents, 10) : null,
    };
    if (!payload.slug || !payload.display_name) {
      setFormError('Slug and display name are required.');
      return;
    }
    setSubmitting(true);
    setFormError('');
    const op = editingId
      ? api.updatePlan(editingId, payload)
      : api.createPlan(payload);
    op
      .then((saved) => {
        setPlans((prev) =>
          editingId
            ? prev.map((p) => (p.id === editingId ? saved : p)).sort((a, b) => a.sort_order - b.sort_order)
            : [...prev, saved].sort((a, b) => a.sort_order - b.sort_order),
        );
        setShowForm(false);
        setEditingId(null);
      })
      .catch((err: Error) => setFormError(err.message))
      .finally(() => setSubmitting(false));
  };

  const handleDelete = (plan: PlanTier) => {
    if (!confirm(`Delete plan "${plan.display_name}"? Keys with this plan will keep their existing JWTs until next heartbeat, but features will fall back to seed defaults.`)) return;
    api.deletePlan(plan.id)
      .then(() => setPlans((prev) => prev.filter((p) => p.id !== plan.id)))
      .catch((err: Error) => alert(`Failed: ${err.message}`));
  };

  const handleSeed = () => {
    if (!selectedProduct) return;
    if (!confirm(`Seed default plans for "${selectedProduct.name}"? Existing plans with the same slug will be skipped.`)) return;
    api.seedPlans(selectedProduct.slug)
      .then((res) => {
        if (res.seeded.length === 0) {
          alert('All default plans already exist — nothing seeded.');
          return;
        }
        return api.getPlans(selectedProductId).then(setPlans);
      })
      .catch((err: Error) => alert(`Seed failed: ${err.message}`));
  };

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-semibold text-gray-800">Plan Configuration</h1>
        <div className="flex items-center gap-2">
          {selectedProduct && (
            <button
              onClick={handleSeed}
              className="px-3 py-1.5 border border-gray-300 text-gray-600 text-sm rounded hover:bg-gray-50"
            >
              Seed defaults
            </button>
          )}
          <button
            onClick={openCreate}
            disabled={!selectedProductId}
            className="px-3 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50"
          >
            Add plan
          </button>
        </div>
      </div>

      {/* Product selector */}
      <div className="mb-6 flex items-center gap-3">
        <label className="text-xs font-medium text-gray-600">Product</label>
        <select
          value={selectedProductId}
          onChange={(e) => setSelectedProductId(e.target.value)}
          className="border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:border-blue-500"
        >
          {products.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
      </div>

      {/* Create / edit form */}
      {showForm && (
        <form
          onSubmit={handleSubmit}
          className="mb-6 bg-gray-50 border border-gray-200 rounded p-4 space-y-3"
        >
          <h2 className="text-sm font-semibold text-gray-700">{editingId ? 'Edit plan' : 'New plan'}</h2>
          <div className="grid grid-cols-3 gap-3">
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-gray-600">Slug</label>
              <input
                value={form.slug}
                onChange={(e) => setForm((f) => ({ ...f, slug: e.target.value }))}
                disabled={!!editingId}
                placeholder="professional"
                className="border border-gray-300 rounded px-2 py-1.5 text-sm font-mono focus:outline-none focus:border-blue-500 disabled:bg-gray-100 disabled:text-gray-400"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-gray-600">Display name</label>
              <input
                value={form.display_name}
                onChange={(e) => setForm((f) => ({ ...f, display_name: e.target.value }))}
                placeholder="Professional"
                className="border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:border-blue-500"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-gray-600">Sort order</label>
              <input
                type="number"
                min="0"
                value={form.sort_order}
                onChange={(e) => setForm((f) => ({ ...f, sort_order: e.target.value }))}
                className="border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:border-blue-500"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-gray-600">Default seats</label>
              <input
                type="number"
                min="1"
                value={form.default_seats}
                onChange={(e) => setForm((f) => ({ ...f, default_seats: e.target.value }))}
                className="border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:border-blue-500"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-gray-600">Max seats <span className="text-gray-400 font-normal">(blank = unlimited)</span></label>
              <input
                type="number"
                min="1"
                value={form.max_seats}
                onChange={(e) => setForm((f) => ({ ...f, max_seats: e.target.value }))}
                placeholder="unlimited"
                className="border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:border-blue-500"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-gray-600">Price per 30 days <span className="text-gray-400 font-normal">(cents, blank = unset)</span></label>
              <input
                type="number"
                min="0"
                value={form.price_cents}
                onChange={(e) => setForm((f) => ({ ...f, price_cents: e.target.value }))}
                placeholder="e.g. 49900 = R499.00"
                className="border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:border-blue-500"
              />
            </div>
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-gray-600">
              Features <span className="text-gray-400 font-normal">(comma or space separated)</span>
            </label>
            <input
              value={form.features}
              onChange={(e) => setForm((f) => ({ ...f, features: e.target.value }))}
              placeholder="basic, ms365, contracts, multi_currency"
              className="border border-gray-300 rounded px-2 py-1.5 text-sm font-mono focus:outline-none focus:border-blue-500"
            />
            {/* Preview */}
            {parseFeaturesInput(form.features).length > 0 && (
              <div className="flex flex-wrap gap-1 mt-1">
                {parseFeaturesInput(form.features).map((f) => (
                  <span key={f} className="px-1.5 py-0.5 bg-blue-50 text-blue-700 text-xs rounded font-mono">{f}</span>
                ))}
              </div>
            )}
          </div>
          <div className="flex items-center gap-2 pt-1">
            <button
              type="submit"
              disabled={submitting}
              className="px-3 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50"
            >
              {submitting ? 'Saving…' : editingId ? 'Save changes' : 'Create plan'}
            </button>
            <button
              type="button"
              onClick={() => { setShowForm(false); setEditingId(null); }}
              className="px-3 py-1.5 text-gray-600 text-sm rounded border border-gray-300 hover:bg-gray-50"
            >
              Cancel
            </button>
            {formError && <p className="text-red-600 text-xs">{formError}</p>}
          </div>
        </form>
      )}

      {error && <p className="text-red-600 text-sm mb-4">{error}</p>}

      {loading ? (
        <p className="text-gray-500 text-sm">Loading…</p>
      ) : plans.length === 0 ? (
        <div className="text-center py-12 text-gray-400 text-sm">
          No plans configured for this product.{' '}
          <button onClick={handleSeed} className="text-blue-600 hover:underline">Seed defaults</button>
          {' '}or{' '}
          <button onClick={openCreate} className="text-blue-600 hover:underline">add one manually</button>.
        </div>
      ) : (
        <div className="space-y-3">
          {plans.map((plan) => (
            <div key={plan.id} className="border border-gray-200 rounded p-4 bg-white">
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <div>
                    <span className="font-semibold text-sm text-gray-800">{plan.display_name}</span>
                    <code className="ml-2 text-xs text-gray-400 font-mono">{plan.slug}</code>
                  </div>
                  <div className="text-xs text-gray-500">
                    {plan.default_seats} seat{plan.default_seats !== 1 ? 's' : ''} default
                    {plan.max_seats != null ? ` · max ${plan.max_seats}` : ' · unlimited'}
                    {plan.price_cents != null && ` · ${(plan.price_cents / 100).toFixed(2)}/30d`}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => openEdit(plan)}
                    className="text-xs text-blue-600 hover:underline"
                  >
                    Edit
                  </button>
                  <button
                    onClick={() => handleDelete(plan)}
                    className="text-xs text-red-600 hover:underline"
                  >
                    Delete
                  </button>
                </div>
              </div>
              <div className="mt-2 flex flex-wrap gap-1">
                {plan.features.length === 0 ? (
                  <span className="text-xs text-gray-400 italic">no features</span>
                ) : (
                  plan.features.map((f) => (
                    <span key={f} className="px-1.5 py-0.5 bg-blue-50 text-blue-700 text-xs rounded font-mono">{f}</span>
                  ))
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
