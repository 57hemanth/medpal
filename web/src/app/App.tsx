import { useEffect, useRef } from 'react';
import {
  ArrowRight,
  ArrowUpRight,
  ChevronDown,
  FileText,
  HeartPulse,
  LayoutList,
  LogOut,
  MessageCircle,
  NotebookPen,
  ShieldCheck,
  Stethoscope,
  Users,
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
import { Brand, Badge } from '../components/ui';
import { ConsentPage } from '../features/consent/ConsentPage';
import { FrontDeskPage } from '../features/frontdesk/FrontDeskPage';
import { RecordsPage } from '../features/records/RecordsPage';
import { ScribePage } from '../features/scribe/ScribePage';
import { TriagePage } from '../features/triage/TriagePage';
import type { Role } from '../api/client';
import '../styles/app.css';

const logins = [
  {
    role: 'patient' as Role,
    name: 'Asha Verma',
    initials: 'AV',
    description: 'Find care, book a visit, and understand your records',
    icon: HeartPulse,
  },
  {
    role: 'caregiver' as Role,
    name: 'Asha, caring for Lata',
    initials: 'AV',
    description: 'Support your family with shared health records',
    icon: Users,
  },
  {
    role: 'doctor' as Role,
    name: 'Test doctor',
    initials: 'DR',
    description: 'Turn consultation notes into a structured draft',
    icon: Stethoscope,
  },
  {
    role: 'desk' as Role,
    name: 'Front desk',
    initials: 'FD',
    description: 'Keep your clinic’s handoff queue moving',
    icon: LayoutList,
  },
  {
    role: 'compliance' as Role,
    name: 'Compliance reviewer',
    initials: 'CR',
    description: 'Explore the compliance role and record access',
    icon: ShieldCheck,
  },
];
const navigation = [
  { to: '/', label: 'Care assistant', icon: MessageCircle, roles: ['patient'] },
  {
    to: '/records',
    label: 'My records',
    icon: FileText,
    roles: ['patient', 'caregiver', 'doctor', 'compliance'],
  },
  {
    to: '/consent',
    label: 'Sharing & consent',
    icon: ShieldCheck,
    roles: ['patient', 'caregiver'],
  },
  {
    to: '/scribe',
    label: 'Consultation scribe',
    icon: NotebookPen,
    roles: ['doctor'],
  },
  { to: '/front-desk', label: 'Front desk', icon: LayoutList, roles: ['desk'] },
];
const homeFor = (role: Role) =>
  role === 'doctor'
    ? '/scribe'
    : role === 'desk'
      ? '/front-desk'
      : role === 'patient'
        ? '/'
        : '/records';

export function App() {
  const { auth, setRole, logout } = useSession();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const mainRef = useRef<HTMLElement>(null);
  useEffect(() => {
    if (auth) {
      mainRef.current?.focus({ preventScroll: true });
      window.scrollTo({ top: 0 });
    }
  }, [pathname, auth]);
  if (!auth)
    return (
      <div className="min-h-dvh lg:grid lg:grid-cols-[0.9fr_1.1fr]">
        <section className="relative overflow-hidden bg-brand-900 p-7 text-white sm:p-12 lg:flex lg:min-h-dvh lg:flex-col lg:justify-between lg:p-14">
          <Brand light />
          <div className="relative z-10 my-8 max-w-md sm:my-14 lg:my-20">
            <span className="mb-7 inline-flex items-center gap-2 rounded-full border border-white/20 px-3 py-1.5 text-xs text-brand-100">
              <span className="size-1.5 rounded-full bg-brand-200" />
              Your care, connected
            </span>
            <h1 className="text-[34px] font-medium leading-[1.15] tracking-[-0.05em] sm:text-5xl lg:text-[58px]">
              A little clarity.
              <br />A lot more care.
            </h1>
            <p className="mt-7 max-w-sm text-base leading-relaxed text-brand-100">
              Meet your everyday care assistant. Find the right doctor, make
              sense of your records, and take your next step with confidence.
            </p>
            <div className="mt-9 flex items-center gap-3 text-sm text-brand-100">
              <span className="flex size-9 items-center justify-center rounded-full border border-white/20">
                <ShieldCheck size={17} />
              </span>
              Private by design. Human at heart.
            </div>
          </div>
          <p className="relative z-10 hidden text-xs text-brand-200 lg:block">
            Thoughtful assistance, with your care team in control.
          </p>
          <div
            aria-hidden="true"
            className="pointer-events-none absolute -bottom-52 -right-52 size-[540px] rounded-full border border-white/10"
          >
            <div className="absolute inset-14 rounded-full border border-white/10" />
            <div className="absolute inset-28 rounded-full border border-white/10" />
          </div>
        </section>
        <main className="mx-auto flex w-full max-w-xl flex-col justify-center px-6 py-10 sm:px-12 lg:py-14">
          <div className="mb-7">
            <Badge>Demo workspace</Badge>
            <h2 className="mt-5 text-[30px] font-semibold tracking-[-0.04em]">
              Choose a test login
            </h2>
            <p className="mt-2 text-sm leading-relaxed text-muted">
              A real workflow, with synthetic data. Choose a perspective to
              explore MedPal.
            </p>
          </div>
          <div className="space-y-2.5">
            {logins.map(({ role, name, description, icon: Icon }) => (
              <button
                key={role}
                onClick={() => {
                  setRole(role);
                  navigate(homeFor(role));
                }}
                className="group flex min-h-22 w-full items-center gap-4 rounded-2xl border border-line bg-white p-4 text-left hover:border-brand-200 hover:bg-brand-50"
              >
                <span className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-canvas text-brand-700">
                  <Icon size={20} strokeWidth={1.7} aria-hidden="true" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-semibold">{name}</span>
                  <span className="mt-1 block text-xs leading-relaxed text-muted">
                    {description}
                  </span>
                </span>
                <ArrowRight
                  size={17}
                  className="text-slate-400 group-hover:text-brand-700"
                  aria-hidden="true"
                />
              </button>
            ))}
          </div>
          <p className="mt-6 text-center text-xs leading-relaxed text-muted">
            No password needed. All people and clinic data are synthetic.
          </p>
        </main>
      </div>
    );

  const identity = logins.find((login) => login.role === auth.role)!;
  const current = navigation.find((item) => item.to === pathname);
  const allowed = navigation.filter((item) => item.roles.includes(auth.role));
  const guard = (roles: string[], element: React.ReactNode) =>
    roles.includes(auth.role) ? (
      element
    ) : (
      <Navigate to={homeFor(auth.role)} replace />
    );
  return (
    <div className="min-h-dvh lg:pl-60">
      <a
        href="#main-content"
        className="sr-only fixed left-4 top-4 z-50 rounded-lg bg-brand-700 p-3 text-white focus:not-sr-only"
      >
        Skip to content
      </a>
      <aside className="border-b border-line bg-white lg:fixed lg:inset-y-0 lg:left-0 lg:z-20 lg:flex lg:w-60 lg:flex-col lg:border-b-0 lg:border-r">
        <div className="flex items-center justify-between px-5 py-5 lg:px-6 lg:pb-9 lg:pt-8">
          <Brand />
          <Badge>Test mode</Badge>
        </div>
        <p className="eyebrow hidden px-6 pb-3 lg:block">Your workspace</p>
        <nav
          aria-label="Main navigation"
          className="flex gap-1 overflow-x-auto px-3 pb-3 lg:flex-col lg:px-4"
        >
          {allowed.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end
              className={({ isActive }) =>
                `flex min-h-11 shrink-0 items-center gap-3 rounded-xl px-3.5 py-3 text-[13px] font-medium ${isActive ? 'bg-brand-50 text-brand-800' : 'text-muted hover:bg-canvas hover:text-ink'}`
              }
            >
              <Icon size={18} strokeWidth={1.7} aria-hidden="true" />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="hidden flex-1 lg:block" />
        <div className="mx-5 mb-5 hidden rounded-xl border border-line bg-canvas p-4 lg:block">
          <ShieldCheck size={20} className="mb-3 text-brand-600" />
          <p className="text-xs font-semibold">Your care. Your control.</p>
          <p className="mt-1.5 text-xs leading-relaxed text-muted">
            Your records are only shared with the people you allow.
          </p>
          {auth.role === 'patient' && (
            <NavLink
              to="/consent"
              className="mt-3 inline-flex min-h-11 items-center gap-1 text-xs font-semibold text-brand-700"
            >
              Manage access
              <ArrowUpRight size={13} />
            </NavLink>
          )}
        </div>
        <div className="hidden border-t border-line p-4 lg:block">
          <button
            onClick={logout}
            className="flex min-h-11 w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-xs text-muted hover:bg-canvas"
          >
            <LogOut size={15} />
            Change test login
          </button>
        </div>
      </aside>
      <header className="hidden min-h-[76px] sm:flex items-center justify-between gap-4 border-b border-line bg-white/80 px-5 sm:px-9">
        <div className="flex items-center gap-2 text-xs text-muted">
          <span className="hidden sm:inline">Workspace</span>
          <span className="hidden text-slate-300 sm:inline">/</span>
          <span className="font-medium text-ink">
            {current?.label ?? 'MedPal'}
          </span>
        </div>
        <button
          onClick={logout}
          aria-label="Change test login"
          className="flex min-h-11 items-center gap-3 rounded-xl px-2 text-left hover:bg-brand-50"
        >
          <span className="flex size-9 items-center justify-center rounded-full bg-[#ede8dd] text-xs font-semibold text-[#615843]">
            {identity.initials}
          </span>
          <span className="hidden sm:block">
            <span className="block text-xs font-semibold">{identity.name}</span>
            <span className="mt-0.5 block text-[11px] capitalize text-muted">
              {auth.role === 'desk' ? 'Clinic team' : auth.role}
            </span>
          </span>
          <ChevronDown size={14} className="text-muted" />
        </button>
      </header>
      <main
        ref={mainRef}
        tabIndex={-1}
        id="main-content"
        className="mx-auto w-full max-w-[1320px] px-5 py-8 outline-none sm:px-9 sm:py-10"
      >
        <Routes>
          <Route path="/" element={guard(['patient'], <TriagePage />)} />
          <Route
            path="/records"
            element={guard(
              ['patient', 'caregiver', 'doctor', 'compliance'],
              <RecordsPage />,
            )}
          />
          <Route
            path="/consent"
            element={guard(['patient', 'caregiver'], <ConsentPage />)}
          />
          <Route path="/scribe" element={guard(['doctor'], <ScribePage />)} />
          <Route
            path="/front-desk"
            element={guard(['desk'], <FrontDeskPage />)}
          />
          <Route
            path="*"
            element={<Navigate to={homeFor(auth.role)} replace />}
          />
        </Routes>
        <footer className="mt-9 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-5 text-[11px] text-muted">
          <span>MedPal · Thoughtful care, one conversation at a time.</span>
          <span className="flex items-center gap-1.5">
            <span className="size-1.5 rounded-full bg-brand-500" />
            Synthetic data workspace
          </span>
        </footer>
      </main>
    </div>
  );
}
