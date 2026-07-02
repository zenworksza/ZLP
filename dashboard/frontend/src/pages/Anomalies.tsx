import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, formatDate, type Anomaly } from '../api';
import { Table } from '../components/Table';

function ScoreBadge({ score }: { score: number }) {
  const color =
    score > 0.85
      ? 'bg-red-100 text-red-800'
      : score > 0.6
        ? 'bg-amber-100 text-amber-800'
        : 'bg-green-100 text-green-800';
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${color}`}>
      {score.toFixed(4)}
    </span>
  );
}

export default function Anomalies() {
  const [anomalies, setAnomalies] = useState<Anomaly[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showResolved, setShowResolved] = useState(false);

  const load = (resolved: boolean) => {
    setLoading(true);
    api
      .getAnomalies(resolved ? undefined : false)
      .then(setAnomalies)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load(showResolved);
  }, [showResolved]);

  const handleResolve = (a: Anomaly, e: React.MouseEvent) => {
    e.stopPropagation();
    api
      .resolveAnomaly(a.id)
      .then(() => {
        setAnomalies((prev) =>
          prev.map((item) =>
            item.id === a.id ? { ...item, resolved_at: new Date().toISOString() } : item,
          ),
        );
      })
      .catch((err: Error) => alert(`Failed to resolve: ${err.message}`));
  };

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-semibold text-gray-800">Anomaly Alerts</h1>
        <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={showResolved}
            onChange={(e) => setShowResolved(e.target.checked)}
            className="rounded border-gray-300"
          />
          Show resolved
        </label>
      </div>

      {error && <p className="text-red-600 text-sm mb-4">Error: {error}</p>}
      {loading ? (
        <p className="text-gray-500 text-sm">Loading...</p>
      ) : (
        <Table
          columns={[
            {
              key: 'install_id',
              header: 'Install ID',
              render: (a) => (
                <Link
                  to={`/installs/${a.install_id}`}
                  onClick={(e) => e.stopPropagation()}
                  className="font-mono text-xs text-blue-700 hover:underline"
                >
                  {a.install_id}
                </Link>
              ),
            },
            {
              key: 'score',
              header: 'Score',
              render: (a) => <ScoreBadge score={a.score} />,
            },
            {
              key: 'reason',
              header: 'Reason',
              render: (a) => <span className="text-gray-700">{a.reason}</span>,
            },
            {
              key: 'triggered_at',
              header: 'Triggered',
              render: (a) => <span className="text-xs text-gray-500">{formatDate(a.triggered_at)}</span>,
            },
            {
              key: 'resolved_at',
              header: 'Resolved',
              render: (a) =>
                a.resolved_at ? (
                  <span className="text-xs text-gray-500">{formatDate(a.resolved_at)}</span>
                ) : (
                  <span className="text-amber-600 text-xs">Unresolved</span>
                ),
            },
            {
              key: 'actions',
              header: '',
              render: (a) =>
                !a.resolved_at ? (
                  <button
                    onClick={(e) => handleResolve(a, e)}
                    className="text-xs text-blue-600 hover:underline"
                  >
                    Resolve
                  </button>
                ) : null,
            },
          ]}
          rows={anomalies}
          emptyMessage={showResolved ? 'No anomaly records.' : 'No unresolved anomalies.'}
        />
      )}
    </div>
  );
}
