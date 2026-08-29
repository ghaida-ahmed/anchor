import { ButtonLink } from '@/components/ui/Button';
import { Logo } from '@/components/ui/Logo';
import { paths } from '@/routes/paths';

export function NotFoundPage() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center px-6 text-center">
      <Logo />
      <h1 className="mt-8 font-serif text-3xl text-ink-900">Page not found</h1>
      <p className="mt-2 max-w-sm text-ink-600">
        That route does not exist. It may have been a course that is no longer in your
        library.
      </p>
      <ButtonLink to={paths.dashboard} className="mt-8">
        Back to dashboard
      </ButtonLink>
    </div>
  );
}
