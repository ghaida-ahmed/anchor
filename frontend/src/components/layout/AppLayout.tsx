import { Outlet } from 'react-router-dom';

import { AppSidebar } from '@/components/layout/AppSidebar';
import { MobileAppBar } from '@/components/layout/MobileAppBar';

/** Shell for the signed-in product surface. */
export function AppLayout() {
  return (
    <div className="flex min-h-screen">
      <AppSidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <MobileAppBar />
        <main className="flex-1 px-6 py-8 lg:px-10">
          <div className="mx-auto max-w-5xl">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
