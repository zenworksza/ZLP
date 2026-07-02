import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { api, formatDate, formatRelative, type Install } from '../api';
import { StatusBadge } from '../components/StatusBadge';
import { Table } from '../components/Table';

function AnomalyBar({ score }: { score: number | null | undefined }) {
  if (score == null) return <span className="text-gray-400 text-xs">—</span>;
  const pct = Math.round(score * 100);
  const color = score > 0.6 ? 'bg-red-500' : score > 0.3 ? 'bg-amber-400' : 'bg-green-500';
  return (
    <div className="flex items-center gap-1.5">
      <div className="w-16 h-2 bg-gray-200 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className={`text-xs ${score > 0.6 ? 'text-red-700' : 'text-gray-600'}`}>
        {score.toFixed(2)}
      </span>
    </div>
  );
}

function isStale(hb: string | null, status: string): boolean {
  if (!hb || status !== 'active') return false;
  return Date.now() - new Date(hb).getTime() > 35 * 60 * 1000;
}

export default function Installs() {
  const [installs, setInstalls] = useState<Install[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const keyId = searchParams.get('key_id') ?? undefined;

  const load = (status?: string) => {
    setLoading(true);
    api
      .getInstalls({ key_id: keyId, status: status || undefined })
      .then(setInstalls)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load(statusFilter || undefined);
  }, [keyId, statusFilter]);

  const handleBlock = (inst: Install, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm(`Block install ${inst.install_id}?`)) return;
    api
      .blockInstall(inst.install_id)
      .then(() => {
        setInstalls((prev) =>
          prev.map((i) => (i.install_id === inst.install_id ? { ...i, status: 'blocked' } : i)),
        );
      })
      .catch((err: Error) => alert(`Failed to block: ${err.message}`));
  };

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-semibold text-gray-800">
          Installs {keyId && <span className="text-sm text-gray-400 font-normal ml-2">filtered by key</span>}
        </h1>
      </div>

      <div className="mb-4 flex items-center gap-3">
        <label className="text-xs font-medium text-gray-600">Status:</label>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:border-blue-500"
        >
          <option value="">All</option>
          <option value="active">Active</option>
          <option value="blocked">Blocked</option>
          <option value="anomalous">Anomalous</option>
        </select>
      </div>

      {error && <p className="text-red-600 text-sm mb-4">Error: {error}</p>}
      {loading ? (
        <p className="text-gray-500 text-sm">Loading...</p>
      ) : (
        <Table
          columns={[
            {
              key: 'domain',
              header: 'Domain',
              render: (i) => <span className="font-medium text-gray-800">{i.domain}</span>,
            },
            {
              key: 'license_key',
              header: 'Key',
              render: (i) => <code className="text-xs font-mono">{i.license_key}</code>,
            },
            { key: 'product', header: 'Product', render: (i) => i.product },
            { key: 'plan', header: 'Plan', render: (i) => <span className="capitalize">{i.plan}</span> },
            { key: 'status', header: 'Status', render: (i) => <StatusBadge status={i.status} /> },
            {
              key: 'last_heartbeat',
              header: 'Last Heartbeat',
              render: (i) => (
                <span className={isStale(i.last_heartbeat, i.status) ? 'text-amber-700 font-medium' : 'text-gray-500'}>
                  {formatRelative(i.last_heartbeat)}
                </span>
              ),
            },
            {
              key: 'anomaly_score',
              header: 'Anomaly Score',
              render: (i) => <AnomalyBar score={i.anomaly_score} />,
            },
            {
              key: 'first_seen',
              header: 'First Seen',
              render: (i) => <span className="text-xs text-gray-500">{formatDate(i.first_seen)}</span>,
            },
            {
              key: 'actions',
              header: '',
              render: (i) =>
                i.status !== 'blocked' ? (
                  <button
                    onClick={(e) => handleBlock(i, e)}
                    className="text-xs text-red-600 hover:underline"
                  >
                    Block
                  </button>
                ) : null,
            },
          ]}
          rows={installs}
          onRowClick={(i) => navigate(`/installs/${i.install_id}`)}
          rowClassName={(i) =>
            isStale(i.last_heartbeat, i.status) ? 'bg-amber-50' : ''
          }
        />
      )}
    </div>
  );
}
