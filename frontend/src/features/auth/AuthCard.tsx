import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';

import { Logo } from '@/components/ui/Logo';
import { paths } from '@/routes/paths';

interface AuthCardProps {
  title: string;
  subtitle: string;
  children: ReactNode;
  footer: ReactNode;
}

/** Shared shell for sign-in and registration — same paper/ink language as the app. */
export function AuthCard({ title, subtitle, children, footer }: AuthCardProps) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center px-6 py-12">
      <Link to={paths.landing} aria-label="ANCHOR home">
        <Logo />
      </Link>

      <div className="mt-8 w-full max-w-sm rounded-card border border-paper-300 bg-white p-7 shadow-raise">
        <h1 className="font-serif text-2xl text-ink-900">{title}</h1>
        <p className="mt-1.5 text-sm text-ink-500">{subtitle}</p>

        <div className="mt-6">{children}</div>
      </div>

      <p className="mt-6 text-sm text-ink-500">{footer}</p>
    </div>
  );
}
