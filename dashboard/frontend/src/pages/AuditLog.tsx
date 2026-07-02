import { useEffect, useState } from 'react';
import { api, formatDate, type AuditEntry } from '../api';
import { Table } from '../components/Table';

const PAGE_SIZE = 100;

export default function AuditLog() {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState('');
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(true);

  const loadPage = (currentOffset: number, append: boolean) => {
    const setLoad = append ? setLoadingMore : setLoading;
    setLoad(true);
    api
      .getAudit(PAGE_SIZE, currentOffset)
      .then((data) => {
        setEntries((prev) => (append ? [...prev, ...data] : data));
        setHasMore(data.length === PAGE_SIZE);
        setOffset(currentOffset + data.length);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoad(false));
  };

  useEffect(() => {
    loadPage(0, false);
  }, []);

  const handleLoadMore = () => {
    loadPage(offset, true);
  };

  return (
    <div className="p-8">
      <h1 className="text-xl font-semibold text-gray-800 mb-6">Audit Log</h1>

      {error && <p className="text-red-600 text-sm mb-4">Error: {error}</p>}
      {loading ? (
        <p className="text-gray-500 text-sm">Loading...</p>
      ) : (
        <>
          <Table
            columns={[
              {
                key: 'timestamp',
                header: 'Timestamp',
                render: (e) => <span className="text-xs text-gray-600">{formatDate(e.timestamp)}</span>,
              },
              {
                key: 'actor',
                header: 'Actor',
                render: (e) => <span className="font-medium text-sm">{e.actor}</span>,
              },
              {
                key: 'action',
                header: 'Action',
                render: (e) => <code className="text-xs bg-gray-100 px-1 py-0.5 rounded">{e.action}</code>,
              },
              {
                key: 'target_type',
                header: 'Target Type',
                render: (e) =>
                  e.target_type ? (
                    <span className="text-xs text-gray-600">{e.target_type}</span>
                  ) : (
                    <span className="text-gray-400">—</span>
                  ),
              },
              {
                key: 'target_id',
                header: 'Target ID',
                render: (e) =>
                  e.target_id ? (
                    <code className="text-xs font-mono text-gray-700">{e.target_id}</code>
                  ) : (
                    <span className="text-gray-400">—</span>
                  ),
              },
            ]}
            rows={entries}
            emptyMessage="No audit records."
          />
          {hasMore && (
            <div className="mt-4 text-center">
              <button
                onClick={handleLoadMore}
                disabled={loadingMore}
                className="px-4 py-2 border border-gray-300 text-sm text-gray-700 rounded hover:bg-gray-50 disabled:opacity-50"
              >
                {loadingMore ? 'Loading...' : 'Load more'}
              </button>
            </div>
          )}
          {!hasMore && entries.length > 0 && (
            <p className="mt-4 text-center text-xs text-gray-400">All records loaded ({entries.length} total).</p>
          )}
        </>
      )}
    </div>
  );
}
