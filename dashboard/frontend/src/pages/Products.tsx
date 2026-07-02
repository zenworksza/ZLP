import { useEffect, useState } from 'react';
import { api, formatDate, type Product } from '../api';
import { Table } from '../components/Table';

export default function Products() {
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showForm, setShowForm] = useState(false);
  const [formName, setFormName] = useState('');
  const [formSlug, setFormSlug] = useState('');
  const [formError, setFormError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    api
      .getProducts()
      .then(setProducts)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
  }, []);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!formName.trim() || !formSlug.trim()) {
      setFormError('Name and slug are required.');
      return;
    }
    setSubmitting(true);
    setFormError('');
    api
      .createProduct({ name: formName.trim(), slug: formSlug.trim() })
      .then((p) => {
        setProducts((prev) => [...prev, p]);
        setFormName('');
        setFormSlug('');
        setShowForm(false);
      })
      .catch((e: Error) => setFormError(e.message))
      .finally(() => setSubmitting(false));
  };

  const handleDelete = async (p: Product) => {
    if (p.key_count > 0) {
      alert(`Cannot delete "${p.name}" — it has ${p.key_count} license key${p.key_count !== 1 ? 's' : ''}. Delete all keys first.`);
      return;
    }
    if (!confirm(`Delete product "${p.name}" (${p.slug})? This cannot be undone.`)) return;
    setDeleting(p.id);
    try {
      await api.deleteProduct(p.id);
      setProducts((prev) => prev.filter((x) => x.id !== p.id));
    } catch (e: unknown) {
      alert(`Failed to delete: ${(e as Error).message}`);
    } finally {
      setDeleting(null);
    }
  };

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-semibold text-gray-800">Products</h1>
        <button
          onClick={() => {
            setShowForm((v) => !v);
            setFormError('');
          }}
          className="px-3 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-700"
        >
          {showForm ? 'Cancel' : 'Add Product'}
        </button>
      </div>

      {showForm && (
        <form onSubmit={handleSubmit} className="mb-6 bg-gray-50 border border-gray-200 rounded p-4 flex gap-3 items-end">
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-gray-600">Name</label>
            <input
              type="text"
              value={formName}
              onChange={(e) => setFormName(e.target.value)}
              className="border border-gray-300 rounded px-2 py-1.5 text-sm w-48 focus:outline-none focus:border-blue-500"
              placeholder="ZenMSP"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-gray-600">Slug</label>
            <input
              type="text"
              value={formSlug}
              onChange={(e) => setFormSlug(e.target.value)}
              className="border border-gray-300 rounded px-2 py-1.5 text-sm w-40 focus:outline-none focus:border-blue-500"
              placeholder="zenmsp"
            />
          </div>
          <button
            type="submit"
            disabled={submitting}
            className="px-3 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50"
          >
            {submitting ? 'Creating...' : 'Create'}
          </button>
          {formError && <p className="text-red-600 text-sm">{formError}</p>}
        </form>
      )}

      {error && <p className="text-red-600 text-sm mb-4">Error: {error}</p>}
      {loading ? (
        <p className="text-gray-500 text-sm">Loading...</p>
      ) : (
        <Table
          columns={[
            { key: 'name', header: 'Name', render: (p) => <span className="font-medium">{p.name}</span> },
            { key: 'slug', header: 'Slug', render: (p) => <code className="text-xs bg-gray-100 px-1 py-0.5 rounded">{p.slug}</code> },
            { key: 'key_count', header: 'Keys', render: (p) => p.key_count },
            { key: 'created_at', header: 'Created', render: (p) => <span className="text-gray-500 text-xs">{formatDate(p.created_at)}</span> },
            {
              key: 'actions',
              header: '',
              render: (p) => (
                <button
                  onClick={() => handleDelete(p)}
                  disabled={deleting === p.id}
                  className="text-xs text-red-500 hover:underline disabled:opacity-40"
                >
                  {deleting === p.id ? 'Deleting…' : 'Delete'}
                </button>
              ),
            },
          ]}
          rows={products}
        />
      )}
    </div>
  );
}
