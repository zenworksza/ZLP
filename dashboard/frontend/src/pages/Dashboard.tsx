import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, formatDate, type Anomaly, type Stats } from '../api';

type StatCardProps = {
  label: string;
  value: number;
  color: string;
};

function StatCard({ label, value, color }: StatCardProps) {
  return (
    <div className={`bg-white border rounded p-5 flex flex-col gap-1 ${color}`}>
      <span className="text-3xl font-bold">{value}</span>
      <span className="text-sm text-gray-500">{label}</span>
    </div>
  );
}

export default function Dashboard() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [anomalies, setAnomalies] = useState<Anomaly[]>([]);
  const [statsError, setStatsError] = useState('');
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    setLoading(true);
    Promise.all([
      api.getStats().then(setStats).catch((e: Error) => setStatsError(e.message)),
      api.getAnomalies(false).then((a) => setAnomalies(a.slice(0, 5))).catch(() => {}),
    ]).finally(() => setLoading(false));
  }, []);

  if (loading) {
    return <div className="p-8 text-gray-500">Loading...</div>;
  }

  return (
    <div className="p-8">
      <h1 className="text-xl font-semibold text-gray-800 mb-6">Overview</h1>

      {statsError && (
        <p className="text-red-600 text-sm mb-4">Failed to load stats: {statsError}</p>
      )}

      {stats && (
        <div className="grid grid-cols-3 gap-4 mb-8">
          <StatCard label="Total Installs" value={stats.total_installs} color="border-gray-200" />
          <StatCard label="Active" value={stats.active} color="border-green-200 text-green-700" />
          <StatCard label="Blocked" value={stats.blocked} color="border-red-200 text-red-700" />
          <StatCard label="Anomalous" value={stats.anomalous} color="border-amber-200 text-amber-700" />
          <StatCard label="Total Keys" value={stats.total_keys} color="border-blue-200 text-blue-700" />
          <StatCard label="Unresolved Alerts" value={stats.unresolved_alerts} color="border-red-200 text-red-700" />
        </div>
      )}

      {anomalies.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold text-gray-600 uppercase tracking-wide mb-3">
            Recent Anomaly Events
          </h2>
          <div className="border border-gray-200 rounded overflow-hidden">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="bg-gray-100 text-xs font-semibold text-gray-500 uppercase">
                  <th className="px-3 py-2 text-left">Install ID</th>
                  <th className="px-3 py-2 text-left">Score</th>
                  <th className="px-3 py-2 text-left">Reason</th>
                  <th className="px-3 py-2 text-left">Triggered</th>
                </tr>
              </thead>
              <tbody>
                {anomalies.map((a, i) => (
                  <tr
                    key={a.id}
                    className={`${i % 2 === 0 ? 'bg-white' : 'bg-gray-50'} border-t border-gray-100 cursor-pointer hover:bg-blue-50`}
                    onClick={() => navigate(`/installs/${a.install_id}`)}
                  >
                    <td className="px-3 py-2 font-mono text-xs text-blue-700">{a.install_id}</td>
                    <td className="px-3 py-2">
                      <ScoreBadge score={a.score} />
                    </td>
                    <td className="px-3 py-2 text-gray-600">{a.reason}</td>
                    <td className="px-3 py-2 text-gray-500 text-xs">{formatDate(a.triggered_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {anomalies.length === 0 && stats && stats.unresolved_alerts === 0 && (
        <p className="text-sm text-gray-400">No unresolved anomalies.</p>
      )}
    </div>
  );
}

function ScoreBadge({ score }: { score: number }) {
  const color =
    score > 0.85
      ? 'bg-red-100 text-red-800'
      : score > 0.6
        ? 'bg-amber-100 text-amber-800'
        : 'bg-green-100 text-green-800';
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${color}`}>
      {score.toFixed(2)}
    </span>
  );
}
