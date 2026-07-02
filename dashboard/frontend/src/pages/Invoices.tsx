import { useEffect, useState } from 'react';
import { api, formatDate, type Invoice } from '../api';

const STATUS_COLORS: Record<string, string> = {
  pending: 'bg-yellow-50 text-yellow-700 border-yellow-200',
  sent:    'bg-blue-50 text-blue-700 border-blue-200',
  paid:    'bg-green-50 text-green-700 border-green-200',
  void:    'bg-gray-100 text-gray-400 border-gray-200',
};

const PERIOD_LABEL: Record<number, string> = { 30: 'Monthly', 90: 'Quarterly', 180: 'Semi-annual' };

function formatAmount(cents: number, currency: string) {
  return `${currency} ${(cents / 100).toLocaleString('en-ZA', { minimumFractionDigits: 2 })}`;
}

function daysUntil(dateStr: string) {
  return Math.ceil((new Date(dateStr).getTime() - Date.now()) / 86400000);
}

export default function Invoices() {
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [statusFilter, setStatusFilter] = useState('');

  const load = (status?: string) => {
    setLoading(true);
    api.getInvoices(status ? { status } : undefined)
      .then(setInvoices)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const handleFilterChange = (s: string) => {
    setStatusFilter(s);
    load(s || undefined);
  };

  const handleMarkPaid = async (inv: Invoice) => {
    if (!confirm(`Mark invoice ${inv.invoice_number} as paid? This will extend the license expiry by ${inv.period_days} days.`)) return;
    try {
      const updated = await api.markInvoicePaid(inv.id);
      setInvoices((prev) => prev.map((i) => (i.id === inv.id ? updated : i)));
    } catch (e: unknown) {
      alert(`Failed: ${(e as Error).message}`);
    }
  };

  const handleResend = async (inv: Invoice) => {
    try {
      const updated = await api.resendInvoice(inv.id);
      setInvoices((prev) => prev.map((i) => (i.id === inv.id ? updated : i)));
      if (updated.emailed) {
        alert(`Invoice resent to ${inv.customer_email}`);
      } else {
        alert('SMTP not configured — invoice not sent. Check SMTP_HOST, SMTP_USER, SMTP_PASSWORD env vars.');
      }
    } catch (e: unknown) {
      alert(`Failed: ${(e as Error).message}`);
    }
  };

  const handleVoid = async (inv: Invoice) => {
    if (!confirm(`Void invoice ${inv.invoice_number}? This cannot be undone.`)) return;
    try {
      const updated = await api.voidInvoice(inv.id);
      setInvoices((prev) => prev.map((i) => (i.id === inv.id ? updated : i)));
    } catch (e: unknown) {
      alert(`Failed: ${(e as Error).message}`);
    }
  };

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-semibold text-gray-800">Invoices</h1>
        <div className="flex items-center gap-3">
          <label className="text-xs font-medium text-gray-600">Status</label>
          <select
            value={statusFilter}
            onChange={(e) => handleFilterChange(e.target.value)}
            className="border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:border-blue-500"
          >
            <option value="">All</option>
            <option value="pending">Pending</option>
            <option value="sent">Sent</option>
            <option value="paid">Paid</option>
            <option value="void">Void</option>
          </select>
        </div>
      </div>

      {error && <p className="text-red-600 text-sm mb-4">{error}</p>}

      {loading ? (
        <p className="text-gray-500 text-sm">Loading…</p>
      ) : invoices.length === 0 ? (
        <div className="text-center py-16 text-gray-400 text-sm">
          No invoices yet. Invoices are generated automatically 14 days before a key's expiry date.
        </div>
      ) : (
        <div className="space-y-3">
          {invoices.map((inv) => {
            const due = daysUntil(inv.due_date);
            const isOverdue = due < 0 && inv.status !== 'paid' && inv.status !== 'void';
            return (
              <div key={inv.id} className={`border rounded p-4 bg-white ${isOverdue ? 'border-red-300' : 'border-gray-200'}`}>
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-semibold text-sm text-gray-800">{inv.invoice_number}</span>
                      <span className={`text-xs px-1.5 py-0.5 rounded border font-medium capitalize ${STATUS_COLORS[inv.status] ?? 'bg-gray-100 text-gray-500 border-gray-200'}`}>
                        {inv.status}
                      </span>
                      {isOverdue && (
                        <span className="text-xs px-1.5 py-0.5 rounded border font-medium bg-red-50 text-red-700 border-red-200">
                          Overdue
                        </span>
                      )}
                    </div>
                    <div className="mt-1 text-xs text-gray-500 space-y-0.5">
                      <div>
                        <span className="font-mono text-gray-700">{inv.license_key}</span>
                        {inv.product_name && <span className="ml-2">— {inv.product_name} · {inv.plan && <span className="capitalize">{inv.plan}</span>}</span>}
                        {inv.customer_email && <span className="ml-2 text-gray-400">({inv.customer_email})</span>}
                      </div>
                      <div>
                        {PERIOD_LABEL[inv.period_days] ?? `${inv.period_days}-day`} renewal ·{' '}
                        {formatDate(inv.period_start)} – {formatDate(inv.period_end)}
                      </div>
                      <div>
                        Due {formatDate(inv.due_date)}
                        {inv.status !== 'paid' && inv.status !== 'void' && (
                          <span className={due < 0 ? ' text-red-600 font-medium' : due <= 7 ? ' text-amber-600' : ''}>
                            {due < 0 ? ` (${Math.abs(due)} days overdue)` : ` (${due} days)`}
                          </span>
                        )}
                        {inv.paid_at && <span className="ml-2 text-green-600">· Paid {formatDate(inv.paid_at)}</span>}
                        {inv.sent_at && !inv.paid_at && <span className="ml-2 text-gray-400">· Sent {formatDate(inv.sent_at)}</span>}
                      </div>
                    </div>
                  </div>

                  <div className="text-right shrink-0">
                    <div className="font-semibold text-gray-800">{formatAmount(inv.amount_cents, inv.currency)}</div>
                    {inv.amount_cents === 0 && <div className="text-xs text-gray-400">No price set on plan</div>}
                  </div>
                </div>

                {inv.status !== 'paid' && inv.status !== 'void' && (
                  <div className="mt-3 flex items-center gap-3 border-t border-gray-100 pt-3">
                    <button
                      onClick={() => handleMarkPaid(inv)}
                      className="text-xs px-2.5 py-1 bg-green-600 text-white rounded hover:bg-green-700"
                    >
                      Mark paid
                    </button>
                    {inv.customer_email && (
                      <button
                        onClick={() => handleResend(inv)}
                        className="text-xs px-2.5 py-1 border border-gray-300 text-gray-600 rounded hover:bg-gray-50"
                      >
                        Resend email
                      </button>
                    )}
                    {!inv.customer_email && (
                      <span className="text-xs text-gray-400">No customer email — set one on the key to enable email sending</span>
                    )}
                    <button
                      onClick={() => handleVoid(inv)}
                      className="text-xs text-red-500 hover:underline ml-auto"
                    >
                      Void
                    </button>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
