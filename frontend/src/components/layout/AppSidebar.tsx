import {
  BookMarked,
  LayoutDashboard,
  LogOut,
  type LucideIcon,
} from 'lucide-react';
import { NavLink } from 'react-router-dom';

import { ApiStatusIndicator } from '@/components/layout/ApiStatusIndicator';
import { Logo } from '@/components/ui/Logo';
import { useAuth } from '@/features/auth/useAuth';
import { cn } from '@/lib/cn';
import { paths } from '@/routes/paths';

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
}

const PRIMARY_NAV: NavItem[] = [
  { to: paths.dashboard, label: 'Dashboard', icon: LayoutDashboard },
  { to: paths.courses, label: 'Courses', icon: BookMarked },
];

export function AppSidebar() {
  const { user, signOut } = useAuth();

  return (
    <aside className="hidden w-60 shrink-0 flex-col border-r border-paper-300 bg-paper-200 lg:flex">
      <div className="flex h-16 items-center px-5">
        <NavLink to={paths.landing} aria-label="ANCHOR home">
          <Logo />
        </NavLink>
      </div>

      <nav className="flex-1 space-y-1 px-3 py-4">
        {PRIMARY_NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                isActive
                  ? 'bg-white text-ink-900 shadow-raise'
                  : 'text-ink-600 hover:bg-paper-300/60 hover:text-ink-900',
              )
            }
          >
            <item.icon className="size-4" strokeWidth={1.75} aria-hidden />
            {item.label}
          </NavLink>
        ))}
      </nav>

      <div className="border-t border-paper-300 px-3 py-3">
        <ApiStatusIndicator />
        <div className="mt-3 flex items-center gap-3 px-2">
          <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-ink-900 text-xs font-medium text-paper-50">
            {user?.name.charAt(0).toUpperCase() ?? '?'}
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-ink-900">{user?.name}</p>
            <p className="truncate text-xs text-ink-400">{user?.email}</p>
          </div>
          <button
            type="button"
            onClick={signOut}
            aria-label="Sign out"
            title="Sign out"
            className="rounded p-1.5 text-ink-400 transition-colors hover:bg-paper-300/60 hover:text-ink-900"
          >
            <LogOut className="size-4" strokeWidth={1.75} aria-hidden />
          </button>
        </div>
      </div>
    </aside>
  );
}
