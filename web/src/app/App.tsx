import { NavLink, Route, Routes } from 'react-router-dom';
import { useAuth } from '../auth/AuthProvider';
import { ConsentPage } from '../features/consent/ConsentPage';
import { FrontDeskPage } from '../features/frontdesk/FrontDeskPage';
import { RecordsPage } from '../features/records/RecordsPage';
import { ScribePage } from '../features/scribe/ScribePage';
import { TriagePage } from '../features/triage/TriagePage';
import { Role } from '../api/client';
import '../styles/app.css';

const roles: Role[] = ['patient', 'caregiver', 'doctor', 'desk', 'pharmacist', 'compliance'];

export function App() {
  const { auth, setRole } = useAuth();
  return (
    <div className="shell">
      <aside>
        <h1>MedPal</h1>
        <label>Dev identity<select value={auth.role} onChange={(e) => setRole(e.target.value as Role)}>{roles.map((r) => <option key={r}>{r}</option>)}</select></label>
        <nav>
          <NavLink to="/">Triage</NavLink>
          <NavLink to="/records">Records</NavLink>
          <NavLink to="/consent">Consent</NavLink>
          <NavLink to="/scribe">Scribe</NavLink>
          <NavLink to="/front-desk">Front desk</NavLink>
        </nav>
      </aside>
      <main><Routes><Route path="/" element={<TriagePage />} /><Route path="/records" element={<RecordsPage />} /><Route path="/consent" element={<ConsentPage />} /><Route path="/scribe" element={<ScribePage />} /><Route path="/front-desk" element={<FrontDeskPage />} /></Routes></main>
    </div>
  );
}
