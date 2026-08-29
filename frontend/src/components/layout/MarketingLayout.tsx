import { Outlet } from 'react-router-dom';

import { MarketingNav } from '@/components/layout/MarketingNav';
import { SiteFooter } from '@/components/layout/SiteFooter';

/** Shell for public, unauthenticated pages. */
export function MarketingLayout() {
  return (
    <div className="flex min-h-screen flex-col">
      <MarketingNav />
      <main className="flex-1">
        <Outlet />
      </main>
      <SiteFooter />
    </div>
  );
}
