import { useEffect, useRef, useState } from 'react';
import {
  BookOpen,
  Check,
  ChevronsUpDown,
  LoaderCircle,
  LogOut,
  Menu,
  ShieldCheck,
  UserRound,
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
import { useAuth, useAuthState } from '../auth/AuthProvider';
import { SignInPage } from '../features/auth/SignInPage';
import { Badge, Brand } from '../components/ui';
import { AppointmentsPage } from '../features/appointments/AppointmentsPage';
import { AuditPage } from '../features/compliance/AuditPage';
import { QualityPage } from '../features/compliance/QualityPage';
import { NotesPage } from '../features/notes/NotesPage';
import { PrescriptionsPage } from '../features/notes/PrescriptionsPage';
import { MessagesPage } from '../features/messages/MessagesPage';
import { SettingsPage } from '../features/messages/SettingsPage';
import { MedicinesPage } from '../features/pharmacy/MedicinesPage';
import { PharmacyHome } from '../features/pharmacy/PharmacyHome';
import { StockPage } from '../features/pharmacy/StockPage';
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
import { navigation, profileFor } from './profiles';
import '../styles/app.css';

function AccountMenu({ onSwitch }: { onSwitch?: () => void }) {
  const { me, auth, switchTo, signOut } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const current = profileFor(auth.role);
  const name = me.name ?? me.phone ?? current.title;
  const initials = name
    .split(/\s+/)
    .filter((part) => /^[A-Za-z]/.test(part))
    .slice(0, 2)
    .map((part) => part[0]!.toUpperCase())
    .join('');
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
  const choose = async (role: Role) => {
    setOpen(false);
    if (role !== auth.role) await switchTo(role);
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
          {initials || <UserRound size={15} aria-hidden="true" />}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13px] font-semibold">
            {name}
          </span>
          <span className="block truncate text-[11px] text-muted">
            {current.title}
            {me.phone ? ` · ${me.phone}` : ''}
          </span>
        </span>
        <ChevronsUpDown size={14} className="text-subtle" aria-hidden="true" />
      </button>
      {open && (
        <div
          role="menu"
          aria-label="Account"
          className="absolute bottom-full left-0 z-40 mb-2 w-full min-w-60 rounded-xl border border-line bg-white p-1.5"
          style={{ boxShadow: 'var(--shadow-pop)' }}
        >
          {me.roles.length > 1 && (
            <>
              <p className="eyebrow px-2.5 pb-1.5 pt-1">Switch role</p>
              {me.roles.map((role) => {
                const profile = profileFor(role);
                return (
                  <button
                    key={role}
                    role="menuitemradio"
                    aria-checked={role === auth.role}
                    onClick={() => void choose(role)}
                    className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left hover:bg-canvas"
                  >
                    <profile.icon
                      size={15}
                      className="text-muted"
                      aria-hidden="true"
                    />
                    <span className="min-w-0 flex-1 truncate text-[13px] font-medium">
                      {profile.title}
                    </span>
                    {role === auth.role && (
                      <Check
                        size={14}
                        className="text-brand-700"
                        aria-hidden="true"
                      />
                    )}
                  </button>
                );
              })}
              <div className="my-1 border-t border-line" />
            </>
          )}
          <button
            role="menuitem"
            onClick={() => void signOut().then(() => navigate('/'))}
            className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-[13px] font-medium hover:bg-canvas"
          >
            <LogOut size={15} className="text-muted" aria-hidden="true" />
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { auth } = useAuth();
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
        <AccountMenu onSwitch={onNavigate} />
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
  pharmacist: <PharmacyHome />,
  compliance: <OperationsPage />,
};

const ROUTES: Record<string, Record<string, React.ReactNode>> = {
  patient: {
    '/care': <TriagePage />,
    '/appointments': <AppointmentsPage />,
    '/records': <RecordsPage />,
    '/sharing': <ConsentPage />,
    '/notes': <NotesPage />,
    '/prescriptions': <PrescriptionsPage />,
    '/settings': <SettingsPage />,
  },
  caregiver: {
    '/records': <RecordsPage />,
    '/sharing': <ConsentPage />,
    '/notes': <NotesPage />,
    '/prescriptions': <PrescriptionsPage />,
  },
  doctor: {
    '/consultations': <ScribePage />,
    '/notes': <NotesPage />,
    '/records': <RecordsPage />,
    '/medicines': <MedicinesPage />,
  },
  pharmacist: { '/stock': <StockPage />, '/medicines': <MedicinesPage /> },
  desk: {
    '/queue': <FrontDeskPage />,
    '/appointments': <AppointmentsPage />,
    '/messages': <MessagesPage />,
  },
  compliance: {
    '/quality': <QualityPage />,
    '/audit': <AuditPage />,
    '/messages': <MessagesPage />,
    '/records': <RecordsPage />,
  },
};

export function App() {
  const state = useAuthState();
  if (state.status === 'loading')
    return (
      <div className="flex min-h-dvh items-center justify-center text-muted">
        <LoaderCircle size={20} className="animate-spin" aria-label="Loading" />
      </div>
    );
  if (state.status === 'signed_out') return <SignInPage />;
  return <Workspace />;
}

function Workspace() {
  const { auth } = useAuth();
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
