import { useEffect, useRef, useState } from 'react';
import {
  BookOpen,
  Check,
  ChevronsUpDown,
  Menu,
  ShieldCheck,
  X,
} from 'lucide-react';
import {
  NavLink,
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from 'react-router-dom';
import { useSession } from '../auth/AuthProvider';
import { Badge, Brand } from '../components/ui';
import { AppointmentsPage } from '../features/appointments/AppointmentsPage';
import { AuditPage } from '../features/compliance/AuditPage';
import { OperationsPage } from '../features/compliance/OperationsPage';
import { ConsentPage } from '../features/consent/ConsentPage';
import { FrontDeskPage } from '../features/frontdesk/FrontDeskPage';
import { DeskHome } from '../features/home/DeskHome';
import { DoctorHome } from '../features/home/DoctorHome';
import { PatientHome } from '../features/home/PatientHome';
import { RecordsPage } from '../features/records/RecordsPage';
import { ScribePage } from '../features/scribe/ScribePage';
import { TriagePage } from '../features/triage/TriagePage';
import type { Role } from '../api/client';
import { navigation, profileFor, profiles } from './profiles';
import '../styles/app.css';

function ProfileSwitcher({ onSwitch }: { onSwitch?: () => void }) {
  const { auth, switchTo } = useSession();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const current = profileFor(auth.role);
  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent | KeyboardEvent) => {
      if (
        event instanceof KeyboardEvent
          ? event.key === 'Escape'
          : !ref.current?.contains(event.target as Node)
      )
        setOpen(false);
    };
    document.addEventListener('mousedown', close);
    document.addEventListener('keydown', close);
    return () => {
      document.removeEventListener('mousedown', close);
      document.removeEventListener('keydown', close);
    };
  }, [open]);
  const choose = (role: Role) => {
    setOpen(false);
    switchTo(role);
    navigate('/');
    onSwitch?.();
  };
  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((value) => !value)}
        aria-haspopup="menu"
        aria-expanded={open}
        className="flex w-full items-center gap-2.5 rounded-lg border border-line bg-white p-2 text-left hover:bg-canvas"
      >
        <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-brand-50 text-[11px] font-bold text-brand-800">
          {current.initials}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13px] font-semibold">
            {current.name}
          </span>
          <span className="block truncate text-[11px] text-muted">
            {current.title}
          </span>
        </span>
        <ChevronsUpDown size={14} className="text-subtle" aria-hidden="true" />
      </button>
      {open && (
        <div
          role="menu"
          aria-label="Switch profile"
          className="absolute bottom-full left-0 z-40 mb-2 w-full min-w-60 rounded-xl border border-line bg-white p-1.5"
          style={{ boxShadow: 'var(--shadow-pop)' }}
        >
          <p className="eyebrow px-2.5 pb-1.5 pt-1">Switch profile</p>
          {profiles.map((profile) => (
            <button
              key={profile.role}
              role="menuitemradio"
              aria-checked={profile.role === auth.role}
              onClick={() => choose(profile.role)}
              className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left hover:bg-canvas"
            >
              <profile.icon
                size={15}
                className="text-muted"
                aria-hidden="true"
              />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[13px] font-medium">
                  {profile.name}
                </span>
                <span className="block truncate text-[11px] text-muted">
                  {profile.title}
                </span>
              </span>
              {profile.role === auth.role && (
                <Check
                  size={14}
                  className="text-brand-700"
                  aria-hidden="true"
                />
              )}
            </button>
          ))}
          <p className="border-t border-line px-2.5 pb-1 pt-2 text-[11px] leading-relaxed text-muted">
            Profiles use synthetic data. Sign-in is added at deployment.
          </p>
        </div>
      )}
    </div>
  );
}

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { auth } = useSession();
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between px-4 pb-4 pt-5">
        <Brand />
      </div>
      <div className="mx-3 mb-4 rounded-lg border border-line bg-canvas px-3 py-2">
        <p className="text-[12px] font-semibold">MedPal Clinics</p>
        <p className="text-[11px] text-muted">Pune · Hyderabad · 22 clinics</p>
      </div>
      <nav
        aria-label="Main navigation"
        className="flex-1 space-y-5 overflow-y-auto px-3"
      >
        {navigation[auth.role]?.map((group) => (
          <div key={group.label}>
            <p className="eyebrow mb-1.5 px-2.5">{group.label}</p>
            <div className="space-y-0.5">
              {group.items.map(({ to, label, icon: Icon }) => (
                <NavLink
                  key={to}
                  to={to}
                  end={to === '/'}
                  onClick={onNavigate}
                  className={({ isActive }) =>
                    `nav-link ${isActive ? 'active' : ''}`
                  }
                >
                  <Icon size={16} strokeWidth={1.8} aria-hidden="true" />
                  {label}
                </NavLink>
              ))}
            </div>
          </div>
        ))}
      </nav>
      <div className="space-y-3 p-3">
        <div className="flex items-start gap-2 rounded-lg px-1 text-[11px] leading-relaxed text-muted">
          <ShieldCheck
            size={14}
            className="mt-0.5 shrink-0 text-brand-600"
            aria-hidden="true"
          />
          Identified data stays in the clinic&apos;s boundary. Every access is
          audited.
        </div>
        <ProfileSwitcher onSwitch={onNavigate} />
      </div>
    </div>
  );
}

function pageTitle(role: Role, pathname: string) {
  for (const group of navigation[role] ?? [])
    for (const item of group.items) if (item.to === pathname) return item.label;
  return 'MedPal';
}

const HOME: Record<string, React.ReactNode> = {
  patient: <PatientHome />,
  caregiver: <PatientHome />,
  doctor: <DoctorHome />,
  desk: <DeskHome />,
  compliance: <OperationsPage />,
};

const ROUTES: Record<string, Record<string, React.ReactNode>> = {
  patient: {
    '/care': <TriagePage />,
    '/appointments': <AppointmentsPage />,
    '/records': <RecordsPage />,
    '/sharing': <ConsentPage />,
  },
  caregiver: { '/records': <RecordsPage />, '/sharing': <ConsentPage /> },
  doctor: { '/consultations': <ScribePage />, '/records': <RecordsPage /> },
  desk: { '/queue': <FrontDeskPage />, '/appointments': <AppointmentsPage /> },
  compliance: { '/audit': <AuditPage />, '/records': <RecordsPage /> },
};

export function App() {
  const { auth } = useSession();
  const { pathname } = useLocation();
  const mainRef = useRef<HTMLElement>(null);
  const [drawer, setDrawer] = useState(false);
  useEffect(() => {
    mainRef.current?.focus({ preventScroll: true });
    window.scrollTo({ top: 0 });
    setDrawer(false);
  }, [pathname, auth.role]);
  const title = pageTitle(auth.role, pathname);
  useEffect(() => {
    document.title = `${title} · MedPal`;
  }, [title]);

  return (
    <div className="min-h-dvh lg:pl-64">
      <a
        href="#main-content"
        className="sr-only fixed left-4 top-4 z-50 rounded-lg bg-brand-700 p-3 text-white focus:not-sr-only"
      >
        Skip to content
      </a>
      <aside className="hidden border-r border-line bg-white lg:fixed lg:inset-y-0 lg:left-0 lg:z-20 lg:block lg:w-64">
        <Sidebar />
      </aside>
      {drawer && (
        <div
          className="fixed inset-0 z-40 lg:hidden"
          role="dialog"
          aria-modal="true"
          aria-label="Menu"
        >
          <button
            className="absolute inset-0 bg-ink/30"
            aria-label="Close menu"
            onClick={() => setDrawer(false)}
          />
          <aside
            className="absolute inset-y-0 left-0 w-72 max-w-[85vw] bg-white"
            style={{ boxShadow: 'var(--shadow-pop)' }}
          >
            <button
              onClick={() => setDrawer(false)}
              aria-label="Close menu"
              className="btn btn-ghost absolute right-2 top-3 px-2"
            >
              <X size={18} />
            </button>
            <Sidebar onNavigate={() => setDrawer(false)} />
          </aside>
        </div>
      )}
      <header className="sticky top-0 z-10 flex min-h-14 items-center justify-between gap-3 border-b border-line bg-white/85 px-4 backdrop-blur sm:px-8">
        <div className="flex min-w-0 items-center gap-2">
          <button
            onClick={() => setDrawer(true)}
            aria-label="Open menu"
            className="btn btn-ghost -ml-2 px-2 lg:hidden"
          >
            <Menu size={18} />
          </button>
          <span className="lg:hidden">
            <Brand />
          </span>
          <nav
            aria-label="Breadcrumb"
            className="hidden items-center gap-2 text-[13px] lg:flex"
          >
            <span className="text-muted">{profileFor(auth.role).title}</span>
            <span className="text-line-strong">/</span>
            <span className="font-medium">{title}</span>
          </nav>
        </div>
        <div className="flex items-center gap-2">
          <Badge tone="amber">Synthetic data</Badge>
          <a
            href="/docs"
            target="_blank"
            rel="noreferrer"
            className="btn btn-ghost hidden px-2.5 sm:inline-flex"
          >
            <BookOpen size={15} aria-hidden="true" />
            API
          </a>
        </div>
      </header>
      <main
        ref={mainRef}
        tabIndex={-1}
        id="main-content"
        className="mx-auto w-full max-w-[1280px] px-4 py-6 outline-none sm:px-8 sm:py-8"
      >
        <Routes>
          <Route path="/" element={HOME[auth.role]} />
          {Object.entries(ROUTES[auth.role] ?? {}).map(([path, element]) => (
            <Route key={path} path={path} element={element} />
          ))}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
        <footer className="mt-10 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-5 text-[11px] text-muted">
          <span>© MedPal · Outpatient care platform</span>
          <span>All people and clinics shown are synthetic.</span>
        </footer>
      </main>
    </div>
  );
}
