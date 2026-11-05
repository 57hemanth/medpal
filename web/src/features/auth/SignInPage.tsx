import { useEffect, useState } from 'react';
import { ArrowRight, KeyRound, ShieldCheck, Smartphone } from 'lucide-react';
import { api } from '../../api/client';
import { useAuthState } from '../../auth/AuthProvider';
import { Brand, Button, ErrorNotice, humanError } from '../../components/ui';

type Step = 'phone' | 'code' | 'register' | 'invited';
type DemoAccount = { phone: string; role: string; name: string | null };
type VerifyOut = {
  signed_in: boolean;
  role?: string;
  registration_token?: string | null;
};

const ROLE_LABEL: Record<string, string> = {
  patient: 'Patient',
  caregiver: 'Caregiver',
  doctor: 'Doctor',
  desk: 'Front desk',
  pharmacist: 'Pharmacist',
  compliance: 'Compliance',
};

/** Sign in with a mobile number and a one-time code. New numbers register a patient record. */
export function SignInPage() {
  const state = useAuthState();
  const refresh =
    state.status === 'signed_out' ? state.refresh : async () => {};
  const [step, setStep] = useState<Step>('phone');
  const [phone, setPhone] = useState('');
  const [masked, setMasked] = useState('');
  const [code, setCode] = useState('');
  const [devCode, setDevCode] = useState<string | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [dob, setDob] = useState('');
  const [city, setCity] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [demo, setDemo] = useState<DemoAccount[]>([]);

  useEffect(() => {
    api<DemoAccount[]>('/api/auth/demo-accounts')
      .then(setDemo)
      .catch(() => setDemo([])); // not offered outside development
  }, []);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError('');
    try {
      await action();
    } catch (cause) {
      setError(humanError(cause));
    } finally {
      setBusy(false);
    }
  }

  const sendCode = (number = phone) =>
    run(async () => {
      const out = await api<{ phone: string; dev_code?: string }>(
        '/api/auth/otp/start',
        { method: 'POST', body: JSON.stringify({ phone: number }) },
      );
      setPhone(number);
      setMasked(out.phone);
      setDevCode(out.dev_code ?? null);
      setCode('');
      setStep('code');
    });

  const verify = () =>
    run(async () => {
      const out = await api<VerifyOut>('/api/auth/otp/verify', {
        method: 'POST',
        body: JSON.stringify({ phone, code }),
      });
      if (out.signed_in && out.registration_token) {
        setToken(out.registration_token);
        setStep('invited');
      } else if (out.signed_in) {
        await refresh();
      } else {
        setToken(out.registration_token ?? null);
        setStep('register');
      }
    });

  const register = () =>
    run(async () => {
      await api('/api/auth/register', {
        method: 'POST',
        body: JSON.stringify({
          registration_token: token,
          name,
          dob: dob || null,
          city: city || null,
        }),
      });
      await refresh();
    });

  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[0.9fr_1.1fr]">
      <section className="relative overflow-hidden bg-brand-900 p-7 text-white sm:p-12 lg:flex lg:min-h-dvh lg:flex-col lg:justify-between lg:p-14">
        <Brand light />
        <div className="relative z-10 my-8 max-w-md sm:my-14">
          <h1 className="text-[34px] font-medium leading-[1.15] tracking-[-0.04em] sm:text-5xl">
            Care, connected
            <br />
            across your clinics.
          </h1>
          <p className="mt-6 max-w-sm text-base leading-relaxed text-brand-100">
            Find the right doctor, keep your reports in one place, and decide
            who in your family can see them.
          </p>
          <p className="mt-8 flex items-center gap-3 text-sm text-brand-100">
            <ShieldCheck size={18} aria-hidden="true" />
            Your health data stays in India, and every access is logged.
          </p>
        </div>
        <p className="relative z-10 hidden text-xs text-brand-200 lg:block">
          Patients, families, doctors, front desk and pharmacy: one sign-in.
        </p>
      </section>

      <main className="mx-auto flex w-full max-w-md flex-col justify-center px-6 py-10 sm:px-10">
        <div className="card p-6 sm:p-8">
          {step === 'phone' && (
            <form
              onSubmit={(event) => {
                event.preventDefault();
                void sendCode();
              }}
            >
              <Smartphone
                size={22}
                className="mb-4 text-brand-700"
                aria-hidden="true"
              />
              <h2 className="text-xl font-semibold tracking-tight">Sign in</h2>
              <p className="mt-1 text-sm text-muted">
                Enter your mobile number. We'll send a one-time code.
              </p>
              <label className="field-label mt-6" htmlFor="phone">
                Mobile number
              </label>
              <input
                id="phone"
                className="field"
                inputMode="tel"
                autoComplete="tel"
                placeholder="98200 00001"
                value={phone}
                onChange={(event) => setPhone(event.target.value)}
              />
              <div className="mt-4">
                <ErrorNotice message={error} />
              </div>
              <Button
                className="mt-4 w-full"
                busy={busy}
                disabled={phone.trim().length < 10}
              >
                Send code
                <ArrowRight size={15} aria-hidden="true" />
              </Button>
            </form>
          )}

          {step === 'code' && (
            <form
              onSubmit={(event) => {
                event.preventDefault();
                void verify();
              }}
            >
              <KeyRound
                size={22}
                className="mb-4 text-brand-700"
                aria-hidden="true"
              />
              <h2 className="text-xl font-semibold tracking-tight">
                Enter the code
              </h2>
              <p className="mt-1 text-sm text-muted">
                Sent to {masked}. It expires in 5 minutes.
              </p>
              {devCode && (
                <p className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[13px] text-amber-900">
                  Development: no SMS gateway is configured. Your code is{' '}
                  <span className="font-mono font-semibold">{devCode}</span>.
                </p>
              )}
              <label className="field-label mt-5" htmlFor="code">
                6-digit code
              </label>
              <input
                id="code"
                className="field font-mono tracking-[0.3em]"
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={6}
                value={code}
                onChange={(event) =>
                  setCode(event.target.value.replace(/\D/g, ''))
                }
              />
              <div className="mt-4">
                <ErrorNotice message={error} />
              </div>
              <Button
                className="mt-4 w-full"
                busy={busy}
                disabled={code.length !== 6}
              >
                Verify and continue
              </Button>
              <button
                type="button"
                className="mt-3 w-full text-center text-[13px] text-muted hover:text-ink"
                onClick={() => setStep('phone')}
              >
                Use a different number
              </button>
            </form>
          )}

          {step === 'register' && (
            <form
              onSubmit={(event) => {
                event.preventDefault();
                void register();
              }}
            >
              <h2 className="text-xl font-semibold tracking-tight">
                Create your record
              </h2>
              <p className="mt-1 text-sm text-muted">
                {masked} is new to MedPal. A few details so clinics can find
                your record.
              </p>
              <label className="field-label mt-5" htmlFor="name">
                Full name
              </label>
              <input
                id="name"
                className="field"
                autoComplete="name"
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
              <div className="mt-4 grid grid-cols-2 gap-3">
                <label>
                  <span className="field-label">Date of birth</span>
                  <input
                    type="date"
                    className="field"
                    value={dob}
                    onChange={(event) => setDob(event.target.value)}
                  />
                </label>
                <label>
                  <span className="field-label">City</span>
                  <input
                    className="field"
                    value={city}
                    placeholder="Pune"
                    onChange={(event) => setCity(event.target.value)}
                  />
                </label>
              </div>
              <div className="mt-4">
                <ErrorNotice message={error} />
              </div>
              <Button
                className="mt-4 w-full"
                busy={busy}
                disabled={name.trim().length < 2}
              >
                Create record and sign in
              </Button>
            </form>
          )}

          {step === 'invited' && (
            <div>
              <h2 className="text-xl font-semibold tracking-tight">
                Welcome to MedPal
              </h2>
              <p className="mt-2 text-sm leading-relaxed text-muted">
                Someone in your family has shared their health records with you.
                You can view them now, or also create a record of your own.
              </p>
              <Button className="mt-5 w-full" onClick={() => void refresh()}>
                View shared records
              </Button>
              <Button
                variant="secondary"
                className="mt-2 w-full"
                onClick={() => setStep('register')}
              >
                Also create my own record
              </Button>
            </div>
          )}
        </div>

        {demo.length > 0 && step === 'phone' && (
          <div className="mt-6">
            <p className="eyebrow mb-2">
              Demo accounts (synthetic data, development only)
            </p>
            <ul className="space-y-1.5">
              {demo.map((account) => (
                <li key={account.phone}>
                  <button
                    className="flex w-full items-center justify-between rounded-lg border border-line bg-white px-3 py-2 text-left text-[13px] hover:bg-canvas"
                    onClick={() => void sendCode(account.phone)}
                    disabled={busy}
                  >
                    <span>
                      <span className="font-medium">
                        {account.name ?? ROLE_LABEL[account.role]}
                      </span>
                      <span className="ml-2 text-muted">
                        {ROLE_LABEL[account.role] ?? account.role}
                      </span>
                    </span>
                    <span className="font-mono text-[12px] text-muted">
                      {account.phone}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </main>
    </div>
  );
}
