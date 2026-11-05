import {
  Activity,
  CalendarDays,
  ClipboardList,
  FileText,
  HeartPulse,
  LayoutDashboard,
  LayoutList,
  MessageCircle,
  NotebookPen,
  ScrollText,
  ShieldCheck,
  Stethoscope,
  Users,
  type LucideIcon,
} from 'lucide-react';
import type { Role } from '../api/client';

/** The workspace profiles available until sign-in is added. Each maps to a seeded synthetic identity. */
export const profiles: {
  role: Role;
  name: string;
  initials: string;
  title: string;
  icon: LucideIcon;
}[] = [
  {
    role: 'patient',
    name: 'Asha Verma',
    initials: 'AV',
    title: 'Patient',
    icon: HeartPulse,
  },
  {
    role: 'caregiver',
    name: 'Asha Verma',
    initials: 'AV',
    title: 'Caregiver for Lata Verma',
    icon: Users,
  },
  {
    role: 'doctor',
    name: 'Dr. General Medicine',
    initials: 'DR',
    title: 'Doctor',
    icon: Stethoscope,
  },
  {
    role: 'desk',
    name: 'Front desk',
    initials: 'FD',
    title: 'Clinic operations',
    icon: LayoutList,
  },
  {
    role: 'compliance',
    name: 'Compliance',
    initials: 'CO',
    title: 'Privacy & quality',
    icon: ShieldCheck,
  },
];

export type NavItem = { to: string; label: string; icon: LucideIcon };
export type NavGroup = { label: string; items: NavItem[] };

export const navigation: Record<string, NavGroup[]> = {
  patient: [
    {
      label: 'Overview',
      items: [{ to: '/', label: 'Home', icon: LayoutDashboard }],
    },
    {
      label: 'Care',
      items: [
        { to: '/care', label: 'Care assistant', icon: MessageCircle },
        { to: '/appointments', label: 'Appointments', icon: CalendarDays },
        { to: '/records', label: 'Health records', icon: FileText },
      ],
    },
    {
      label: 'Privacy',
      items: [
        { to: '/sharing', label: 'Sharing & consent', icon: ShieldCheck },
      ],
    },
  ],
  caregiver: [
    {
      label: 'Overview',
      items: [{ to: '/', label: 'Home', icon: LayoutDashboard }],
    },
    {
      label: 'Family care',
      items: [
        { to: '/records', label: 'Shared records', icon: FileText },
        { to: '/sharing', label: 'Access granted to me', icon: ShieldCheck },
      ],
    },
  ],
  doctor: [
    {
      label: 'Overview',
      items: [{ to: '/', label: 'Today', icon: LayoutDashboard }],
    },
    {
      label: 'Clinical',
      items: [
        { to: '/consultations', label: 'Consultations', icon: NotebookPen },
        { to: '/records', label: 'Patient records', icon: FileText },
      ],
    },
  ],
  desk: [
    {
      label: 'Overview',
      items: [{ to: '/', label: 'Overview', icon: LayoutDashboard }],
    },
    {
      label: 'Operations',
      items: [
        { to: '/queue', label: 'Handoff queue', icon: ClipboardList },
        { to: '/appointments', label: 'Appointments', icon: CalendarDays },
      ],
    },
  ],
  compliance: [
    {
      label: 'Overview',
      items: [{ to: '/', label: 'Operations', icon: Activity }],
    },
    {
      label: 'Governance',
      items: [
        { to: '/audit', label: 'Audit log', icon: ScrollText },
        { to: '/records', label: 'Records access', icon: FileText },
      ],
    },
  ],
};

export const profileFor = (role: Role) =>
  profiles.find((profile) => profile.role === role) ?? profiles[0];
