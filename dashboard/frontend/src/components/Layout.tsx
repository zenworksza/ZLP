import { useEffect, useState } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { api, clearStoredToken } from '../api';

type NavItem = {
  to: string;
  label: string;
};

const navItems: NavItem[] = [
  { to: '/', label: 'Dashboard' },
  { to: '/products', label: 'Products' },
  { to: '/plans', label: 'Plans' },
  { to: '/keys', label: 'Keys' },
  { to: '/installs', label: 'Installs' },
  { to: '/anomalies', label: 'Anomalies' },
  { to: '/invoices', label: 'Invoices' },
  { to: '/audit', label: 'Audit Log' },
];

export function Layout() {
  const [unresolvedAlerts, setUnresolvedAlerts] = useState(0);

  useEffect(() => {
    const load = () => {
      api.getStats().then((s) => setUnresolvedAlerts(s.unresolved_alerts)).catch(() => {});
    };
    load();
    const id = setInterval(load, 60_000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="flex h-screen bg-white text-gray-800">
      <aside className="w-52 flex-shrink-0 bg-gray-100 border-r border-gray-200 flex flex-col">
        <div className="px-4 py-5 border-b border-gray-200">
          <span className="text-base font-bold text-blue-700 tracking-tight">ZLP Dashboard</span>
        </div>
        <nav className="flex-1 py-3">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              className={({ isActive }) =>
                `flex items-center justify-between px-4 py-2 text-sm ${
                  isActive
                    ? 'bg-blue-600 text-white font-medium'
                    : 'text-gray-700 hover:bg-gray-200'
                }`
              }
            >
              <span>{item.label}</span>
              {item.label === 'Anomalies' && unresolvedAlerts > 0 && (
                <span className="bg-red-500 text-white text-xs font-bold px-1.5 py-0.5 rounded-full min-w-[1.25rem] text-center">
                  {unresolvedAlerts}
                </span>
              )}
            </NavLink>
          ))}
        </nav>
        <div className="px-4 py-3 border-t border-gray-200 flex items-center justify-between">
          <span className="text-xs text-gray-400">Zen License Platform</span>
          <button
            onClick={() => { clearStoredToken(); window.location.reload(); }}
            className="text-xs text-gray-400 hover:text-gray-600"
            title="Sign out"
          >
            Sign out
          </button>
        </div>
      </aside>
      <main className="flex-1 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  );
}
