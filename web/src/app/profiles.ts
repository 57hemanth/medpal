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
  Pill,
  ShieldCheck,
  Stethoscope,
  Gauge,
  Package,
  ClipboardPlus,
  Users,
  type LucideIcon,
} from 'lucide-react';
import type { Role } from '../api/client';

/** How each role is labelled in the workspace. The signed-in person's own name comes from /api/me. */
export const profiles: {
  role: Role;
  title: string;
  icon: LucideIcon;
}[] = [
  {
    role: 'patient',
    title: 'Patient',
    icon: HeartPulse,
  },
  {
    role: 'caregiver',
    title: 'Caregiver',
    icon: Users,
  },
  {
    role: 'doctor',
    title: 'Doctor',
    icon: Stethoscope,
  },
  {
    role: 'desk',
    title: 'Front desk',
    icon: LayoutList,
  },
  {
    role: 'pharmacist',
    title: 'Pharmacist',
    icon: Pill,
  },
  {
    role: 'compliance',
    title: 'Compliance',
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
        { to: '/notes', label: 'Visit notes', icon: NotebookPen },
        { to: '/prescriptions', label: 'Prescriptions', icon: Pill },
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
        { to: '/notes', label: 'Visit notes', icon: NotebookPen },
        { to: '/prescriptions', label: 'Prescriptions', icon: Pill },
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
        { to: '/consultations', label: 'Consultations', icon: ClipboardPlus },
        { to: '/notes', label: 'Signed notes', icon: NotebookPen },
        { to: '/records', label: 'Patient records', icon: FileText },
        { to: '/medicines', label: 'Medicines', icon: Pill },
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
  pharmacist: [
    {
      label: 'Overview',
      items: [{ to: '/', label: 'Dispensing', icon: LayoutDashboard }],
    },
    {
      label: 'Pharmacy',
      items: [
        { to: '/stock', label: 'Stock & restock', icon: Package },
        { to: '/medicines', label: 'Medicines', icon: Pill },
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
        { to: '/quality', label: 'Quality', icon: Gauge },
        { to: '/audit', label: 'Audit log', icon: ScrollText },
        { to: '/records', label: 'Records access', icon: FileText },
      ],
    },
  ],
};

export const profileFor = (role: Role) =>
  profiles.find((profile) => profile.role === role) ?? profiles[0];
