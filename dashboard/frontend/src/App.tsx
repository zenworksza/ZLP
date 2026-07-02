import { useState } from 'react';
import { createBrowserRouter, RouterProvider } from 'react-router-dom';
import { Layout } from './components/Layout';
import Dashboard from './pages/Dashboard';
import Products from './pages/Products';
import Keys from './pages/Keys';
import Installs from './pages/Installs';
import InstallDetail from './pages/InstallDetail';
import Anomalies from './pages/Anomalies';
import AuditLog from './pages/AuditLog';
import Plans from './pages/Plans';
import Invoices from './pages/Invoices';
import Login from './pages/Login';
import { getStoredToken } from './api';

const router = createBrowserRouter([
  {
    path: '/',
    element: <Layout />,
    children: [
      { index: true, element: <Dashboard /> },
      { path: 'products', element: <Products /> },
      { path: 'plans', element: <Plans /> },
      { path: 'keys', element: <Keys /> },
      { path: 'installs', element: <Installs /> },
      { path: 'installs/:installId', element: <InstallDetail /> },
      { path: 'anomalies', element: <Anomalies /> },
      { path: 'audit', element: <AuditLog /> },
      { path: 'invoices', element: <Invoices /> },
    ],
  },
]);

export function App() {
  const [authenticated, setAuthenticated] = useState(() => !!getStoredToken());

  if (!authenticated) {
    return <Login onLogin={() => setAuthenticated(true)} />;
  }

  return <RouterProvider router={router} />;
}
