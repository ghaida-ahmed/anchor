import { Logo } from '@/components/ui/Logo';

export function SiteFooter() {
  return (
    <footer className="border-t border-paper-300 bg-paper-200">
      <div className="mx-auto flex max-w-6xl flex-col gap-6 px-6 py-10 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <Logo />
          <p className="mt-3 max-w-sm text-sm text-ink-500">
            A study workspace built around your own course materials.
          </p>
        </div>
      </div>
    </footer>
  );
}
