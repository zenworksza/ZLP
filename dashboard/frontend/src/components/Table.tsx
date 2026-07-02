import { ReactNode } from 'react';

type Column<T> = {
  header: string;
  key: string;
  render: (row: T) => ReactNode;
  className?: string;
};

type TableProps<T> = {
  columns: Column<T>[];
  rows: T[];
  onRowClick?: (row: T) => void;
  rowClassName?: (row: T) => string;
  emptyMessage?: string;
};

export function Table<T>({
  columns,
  rows,
  onRowClick,
  rowClassName,
  emptyMessage = 'No records found.',
}: TableProps<T>) {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm border-collapse">
        <thead>
          <tr className="bg-gray-100 text-left text-xs font-semibold text-gray-600 uppercase tracking-wide">
            {columns.map((col) => (
              <th key={col.key} className={`px-3 py-2 border-b border-gray-200 ${col.className ?? ''}`}>
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="px-3 py-4 text-center text-gray-400">
                {emptyMessage}
              </td>
            </tr>
          ) : (
            rows.map((row, i) => {
              const extra = rowClassName ? rowClassName(row) : '';
              const base = i % 2 === 0 ? 'bg-white' : 'bg-gray-50';
              const clickable = onRowClick ? 'cursor-pointer hover:bg-blue-50' : '';
              return (
                <tr
                  key={i}
                  className={`${base} ${extra} ${clickable} border-b border-gray-100`}
                  onClick={() => onRowClick?.(row)}
                >
                  {columns.map((col) => (
                    <td key={col.key} className={`px-3 py-2 ${col.className ?? ''}`}>
                      {col.render(row)}
                    </td>
                  ))}
                </tr>
              );
            })
          )}
        </tbody>
      </table>
    </div>
  );
}
