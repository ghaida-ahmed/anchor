import { useApiHealth } from '@/hooks/useApiHealth';

/**
 * Surfaces a backend that cannot be reached.
 *
 * Nothing is rendered while the API is healthy or still being checked. A student
 * does not need a connectivity badge during normal use — it is engineering status,
 * not product information. The unreachable case is different: without it the app
 * looks broken for no stated reason, so that one line stays.
 */
export function ApiStatusIndicator() {
  const status = useApiHealth();

  if (status !== 'unreachable') return null;

  return (
    <div className="flex items-center gap-2 px-2 py-1.5 text-xs text-signal-danger">
      <span className="size-1.5 rounded-full bg-signal-danger" aria-hidden />
      API offline
    </div>
  );
}
