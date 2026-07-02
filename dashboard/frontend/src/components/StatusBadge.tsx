const colorMap: Record<string, string> = {
  active: 'bg-green-100 text-green-800',
  valid: 'bg-green-100 text-green-800',
  blocked: 'bg-red-100 text-red-800',
  revoked: 'bg-red-100 text-red-800',
  invalid: 'bg-red-100 text-red-800',
  anomalous: 'bg-amber-100 text-amber-800',
  suspended: 'bg-amber-100 text-amber-800',
  expired: 'bg-amber-100 text-amber-800',
  pending: 'bg-gray-100 text-gray-700',
  fingerprint_mismatch: 'bg-red-100 text-red-800',
  error: 'bg-red-100 text-red-800',
};

export function StatusBadge({ status }: { status: string }) {
  const classes = colorMap[status.toLowerCase()] ?? 'bg-gray-100 text-gray-700';
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${classes}`}>
      {status}
    </span>
  );
}
