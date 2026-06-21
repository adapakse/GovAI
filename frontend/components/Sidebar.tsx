'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useState } from 'react';
import { useAuth } from '@/components/AuthProvider';

const NAV = [
  { href: '/dashboard', label: 'Pulpit',     icon: <DashIcon /> },
  { href: '/agents',    label: 'Agenci',     icon: <AgentsIcon /> },
  { href: '/oversight', label: 'Nadzór',     icon: <OversightIcon /> },
  { href: '/audit',     label: 'Dziennik',   icon: <AuditIcon /> },
  { href: '/policies',  label: 'Polityki',   icon: <PoliciesIcon /> },
  { href: '/providers', label: 'Providerzy', icon: <ProvidersIcon /> },
  { href: '/reports',   label: 'Raporty',    icon: <ReportsIcon /> },
  { href: '/demo',      label: 'Symulator',  icon: <DemoIcon /> },
  { href: '/settings',  label: 'Parametry',  icon: <SettingsIcon /> },
];

export default function Sidebar() {
  const path = usePathname();
  const [pendingCount, setPendingCount] = useState(0);
  const { user, logout } = useAuth();

  useEffect(() => {
    if (path === '/login') return;
    const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

    async function fetchCount() {
      try {
        const { getAccessToken } = await import('@/lib/auth');
        const token = getAccessToken();
        if (!token) return;
        const r = await fetch(`${API}/oversight/pending`, {
          cache: 'no-store',
          headers: { Authorization: `Bearer ${token}` },
        });
        if (r.ok) {
          const data = await r.json();
          setPendingCount(Array.isArray(data) ? data.length : 0);
        }
      } catch {}
    }

    fetchCount();
    const id = setInterval(fetchCount, 30_000);
    return () => clearInterval(id);
  }, [path]);

  if (path === '/login') return null;

  return (
    <aside className="w-52 bg-navy flex flex-col flex-shrink-0 border-r border-blue/30">
      {/* Logo */}
      <div className="px-5 py-5 border-b border-blue/30 flex items-center gap-3">
        {/* SVG logo-mark inline */}
        <svg width="28" height="28" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
          <defs>
            <linearGradient id="sbRingGrad" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#00B4D8"/>
              <stop offset="100%" stopColor="#1E6FBF"/>
            </linearGradient>
            <mask id="sbGapMask">
              <rect x="0" y="0" width="100" height="100" fill="white"/>
              <rect x="58" y="10" width="32" height="32" fill="black"/>
            </mask>
          </defs>
          <circle cx="50" cy="50" r="30" fill="none" stroke="url(#sbRingGrad)" strokeWidth="13" mask="url(#sbGapMask)"/>
          <line x1="74" y1="27" x2="56" y2="27" stroke="url(#sbRingGrad)" strokeWidth="13" strokeLinecap="round"/>
          <circle cx="56" cy="27" r="8.5" fill="#F0F4F8"/>
        </svg>
        <div>
          <div className="text-white font-bold text-xl tracking-wide leading-none">
            Gov<span className="text-teal">AI</span>
          </div>
          <div className="text-mgray text-[11px] mt-0.5 tracking-wide">EU AI Act Compliance</div>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 py-3">
        {NAV.map(({ href, icon, label }) => {
          const active = path === href || path.startsWith(href + '/');
          const showBadge = href === '/oversight' && pendingCount > 0;
          return (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-3 px-4 py-2.5 text-sm transition-colors ${
                active
                  ? 'bg-blue/30 text-teal border-r-2 border-teal'
                  : 'text-mgray hover:bg-blue/20 hover:text-white'
              }`}
            >
              <span className={`w-4 h-4 flex-shrink-0 ${active ? 'text-teal' : 'text-mgray/70'}`}>
                {icon}
              </span>
              <span className="flex-1 font-medium">{label}</span>
              {showBadge && (
                <span className="text-xs font-bold bg-orange-500 text-white rounded-full w-5 h-5 flex items-center justify-center">
                  {pendingCount > 9 ? '9+' : pendingCount}
                </span>
              )}
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="px-4 py-4 border-t border-blue/30 text-xs text-mgray/60">
        {user && (
          <div className="mb-2.5">
            <div className="text-white/80 font-medium truncate">{user.full_name}</div>
            <div className="text-mgray/50 truncate uppercase tracking-wider text-[10px] mt-0.5">{user.role}</div>
          </div>
        )}
        <button
          onClick={logout}
          className="text-mgray/50 hover:text-govred transition-colors"
        >
          Wyloguj
        </button>
        <div className="mt-1 text-[10px] text-mgray/30">EU AI Act 2024/1689</div>
      </div>
    </aside>
  );
}

/* ── Ikony SVG ──────────────────────────────────────────────────────────────── */

function DashIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="currentColor">
      <rect x="1" y="1" width="6" height="6" rx="1"/>
      <rect x="9" y="1" width="6" height="6" rx="1"/>
      <rect x="1" y="9" width="6" height="6" rx="1"/>
      <rect x="9" y="9" width="6" height="6" rx="1"/>
    </svg>
  );
}

function AgentsIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="8" cy="5" r="3"/>
      <path d="M2 14c0-3.3 2.7-6 6-6s6 2.7 6 6" strokeLinecap="round"/>
    </svg>
  );
}

function OversightIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="8" cy="8" r="6"/>
      <circle cx="8" cy="8" r="2" fill="currentColor" stroke="none"/>
    </svg>
  );
}

function AuditIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
      <rect x="2" y="2" width="12" height="12" rx="1.5"/>
      <line x1="5" y1="6" x2="11" y2="6" strokeLinecap="round"/>
      <line x1="5" y1="9" x2="11" y2="9" strokeLinecap="round"/>
      <line x1="5" y1="12" x2="8" y2="12" strokeLinecap="round"/>
    </svg>
  );
}

function PoliciesIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M8 1L2 4v4c0 3.3 2.5 6 6 7 3.5-1 6-3.7 6-7V4L8 1z" strokeLinejoin="round"/>
    </svg>
  );
}

function ProvidersIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
      <rect x="1" y="1" width="6" height="6" rx="1"/>
      <rect x="9" y="1" width="6" height="6" rx="1"/>
      <rect x="1" y="9" width="6" height="6" rx="1"/>
      <path d="M9 12h6M12 9v6" strokeLinecap="round"/>
    </svg>
  );
}

function ReportsIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
      <rect x="2" y="2" width="12" height="12" rx="1.5"/>
      <polyline points="5,10 7,7 9,9 11,5" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  );
}

function DemoIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="currentColor">
      <path d="M5 3l8 5-8 5V3z"/>
    </svg>
  );
}

function SettingsIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="8" cy="8" r="2.5"/>
      <path d="M8 1v2M8 13v2M1 8h2M13 8h2M3 3l1.5 1.5M11.5 11.5L13 13M13 3l-1.5 1.5M4.5 11.5L3 13" strokeLinecap="round"/>
    </svg>
  );
}
