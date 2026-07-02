import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api, formatDate, formatRelative, type HeartbeatEntry, type Install } from '../api';
import { StatusBadge } from '../components/StatusBadge';
import { Table } from '../components/Table';

export default function InstallDetail() {
  const { installId } = useParams<{ installId: string }>();
  const navigate = useNavigate();
  const [install, setInstall] = useState<Install | null>(null);
  const [heartbeats, setHeartbeats] = useState<HeartbeatEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [blocking, setBlocking] = useState(false);

  useEffect(() => {
    if (!installId) return;
    setLoading(true);
    Promise.all([
      api.getInstall(installId).then(setInstall),
      api.getHeartbeats(installId).then(setHeartbeats),
    ])
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [installId]);

  const handleBlock = () => {
    if (!installId || !confirm(`Block install ${installId}?`)) return;
    setBlocking(true);
    api
      .blockInstall(installId)
      .then(() => {
        setInstall((prev) => (prev ? { ...prev, status: 'blocked' } : prev));
      })
      .catch((e: Error) => alert(`Failed to block: ${e.message}`))
      .finally(() => setBlocking(false));
  };

  if (loading) return <div className="p-8 text-gray-500">Loading...</div>;
  if (error) return <div className="p-8 text-red-600">Error: {error}</div>;
  if (!install) return <div className="p-8 text-gray-400">Install not found.</div>;

  return (
    <div className="p-8">
      <button
        onClick={() => navigate(-1)}
        className="text-sm text-blue-600 hover:underline mb-4 inline-block"
      >
        ← Back
      </button>

      <div className="flex items-start justify-between mb-6">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <h1 className="text-xl font-semibold text-gray-800">{install.domain}</h1>
            <StatusBadge status={install.status} />
          </div>
          <code className="text-xs text-gray-500 font-mono">{install.install_id}</code>
        </div>
        {install.status !== 'blocked' && (
          <button
            onClick={handleBlock}
            disabled={blocking}
            className="px-3 py-1.5 bg-red-600 text-white text-sm rounded hover:bg-red-700 disabled:opacity-50"
          >
            {blocking ? 'Blocking...' : 'Block Install'}
          </button>
        )}
      </div>

      <div className="grid grid-cols-2 gap-x-8 gap-y-3 mb-8 bg-gray-50 border border-gray-200 rounded p-5 text-sm">
        <InfoRow label="License Key" value={<code className="font-mono text-xs">{install.license_key}</code>} />
        <InfoRow label="Product" value={install.product} />
        <InfoRow label="Plan" value={<span className="capitalize">{install.plan}</span>} />
        <InfoRow label="First Seen" value={formatDate(install.first_seen)} />
        <InfoRow
          label="Last Heartbeat"
          value={
            <span>
              {formatDate(install.last_heartbeat)}{' '}
              <span className="text-gray-400">({formatRelative(install.last_heartbeat)})</span>
            </span>
          }
        />
        {install.anomaly_score != null && (
          <InfoRow label="Anomaly Score" value={install.anomaly_score.toFixed(4)} />
        )}
      </div>

      <h2 className="text-sm font-semibold text-gray-600 uppercase tracking-wide mb-3">
        Heartbeat Log
      </h2>
      <Table
        columns={[
          {
            key: 'timestamp',
            header: 'Timestamp',
            render: (h) => <span className="text-xs text-gray-600">{formatDate(h.timestamp)}</span>,
          },
          {
            key: 'response_status',
            header: 'Status',
            render: (h) => <StatusBadge status={h.response_status} />,
          },
          {
            key: 'latency_ms',
            header: 'Latency',
            render: (h) =>
              h.latency_ms != null ? (
                <span className="text-xs">{h.latency_ms} ms</span>
              ) : (
                <span className="text-gray-400 text-xs">—</span>
              ),
          },
        ]}
        rows={heartbeats}
        emptyMessage="No heartbeat records."
      />
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs font-medium text-gray-500">{label}</span>
      <span className="text-gray-800">{value}</span>
    </div>
  );
}
