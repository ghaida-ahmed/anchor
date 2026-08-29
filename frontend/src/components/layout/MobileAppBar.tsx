import { BookMarked, LayoutDashboard } from 'lucide-react';
import { NavLink } from 'react-router-dom';

import { Logo } from '@/components/ui/Logo';
import { cn } from '@/lib/cn';
import { paths } from '@/routes/paths';

const ITEMS = [
  { to: paths.dashboard, label: 'Dashboard', icon: LayoutDashboard },
  { to: paths.courses, label: 'Courses', icon: BookMarked },
];

/** Compact navigation for viewports below the sidebar breakpoint. */
export function MobileAppBar() {
  return (
    <header className="flex items-center justify-between border-b border-paper-300 bg-paper-200 px-4 py-3 lg:hidden">
      <NavLink to={paths.landing} aria-label="ANCHOR home">
        <Logo />
      </NavLink>
      <nav className="flex gap-1">
        {ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm font-medium',
                isActive ? 'bg-white text-ink-900' : 'text-ink-500',
              )
            }
          >
            <item.icon className="size-4" strokeWidth={1.75} aria-hidden />
            {item.label}
          </NavLink>
        ))}
      </nav>
    </header>
  );
}
