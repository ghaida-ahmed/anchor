import { Link } from 'react-router-dom';

import { ButtonLink } from '@/components/ui/Button';
import { Logo } from '@/components/ui/Logo';
import { useAuth } from '@/features/auth/useAuth';
import { paths } from '@/routes/paths';

const SECTIONS = [
  { href: '#how-it-works', label: 'How it works' },
  { href: '#features', label: 'Features' },
  { href: '#roadmap', label: 'Roadmap' },
];

export function MarketingNav() {
  const { status } = useAuth();
  const isSignedIn = status === 'authenticated';

  return (
    <header className="sticky top-0 z-20 border-b border-paper-300 bg-paper-100">
      <nav className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
        <Link to={paths.landing} aria-label="ANCHOR home">
          <Logo />
        </Link>

        <div className="hidden items-center gap-8 md:flex">
          {SECTIONS.map((section) => (
            <a
              key={section.href}
              href={section.href}
              className="text-sm text-ink-600 transition-colors hover:text-ink-900"
            >
              {section.label}
            </a>
          ))}
        </div>

        <div className="flex items-center gap-2">
          {isSignedIn ? null : (
            <ButtonLink to={paths.login} size="sm" variant="ghost">
              Sign in
            </ButtonLink>
          )}
          <ButtonLink to={isSignedIn ? paths.dashboard : paths.register} size="sm">
            {isSignedIn ? 'Open dashboard' : 'Get started'}
          </ButtonLink>
        </div>
      </nav>
    </header>
  );
}
