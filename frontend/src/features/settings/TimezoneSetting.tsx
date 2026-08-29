import { Check, Globe } from 'lucide-react';
import { useMemo, useState } from 'react';

import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { FormError } from '@/components/ui/ErrorState';
import { Spinner } from '@/components/ui/Spinner';
import { useAuth } from '@/features/auth/useAuth';
import { cn } from '@/lib/cn';
import * as authApi from '@/services/api/auth';
import { toErrorMessage } from '@/services/api/client';

/**
 * Which timezone the student's days are counted in.
 *
 * Everything ANCHOR stores is UTC. This setting decides one thing: where a day
 * starts and ends. That matters for the review queue ("due today"), the activity
 * chart, and the countdown to an exam — all of which would land on the wrong day
 * for anyone whose evening falls after midnight UTC.
 *
 * The list comes from the browser's own tz database, so it is complete and stays
 * current without shipping a list of our own. The suggestion is what the browser
 * already reports; nothing is inferred from an IP address, and a timezone is not
 * a location.
 */
export function TimezoneSetting() {
  const { user, setUser } = useAuth();
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const zones = useMemo(() => supportedTimezones(), []);
  const detected = useMemo(() => authApi.detectTimezone(), []);

  if (!user) return null;

  const isDefault = user.timezone === 'UTC';
  const suggestion = detected !== user.timezone ? detected : null;

  async function save(timezone: string) {
    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      setUser(await authApi.updateTimezone(timezone));
      setSaved(true);
    } catch (caught) {
      setError(toErrorMessage(caught));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card>
      <CardHeader
        title="Your timezone"
        description="Decides when your study day starts and ends."
      />
      <CardBody className="space-y-3">
        {error ? <FormError message={error} /> : null}

        <div className="flex flex-wrap items-center gap-3">
          <Globe className="size-4 shrink-0 text-ink-400" strokeWidth={1.75} aria-hidden />
          <label htmlFor="timezone" className="sr-only">
            Timezone
          </label>
          <select
            id="timezone"
            value={user.timezone}
            disabled={saving}
            onChange={(event) => void save(event.target.value)}
            className={cn(
              'min-w-56 flex-1 rounded-lg border border-paper-400 bg-paper-50 px-3 py-2 text-sm text-ink-900',
              'focus:border-ink-500 focus:outline-none focus:ring-2 focus:ring-ink-900/10',
              saving && 'cursor-wait opacity-60',
            )}
          >
            {zones.map((zone) => (
              <option key={zone} value={zone}>
                {zone.replace(/_/g, ' ')}
              </option>
            ))}
          </select>
          {saving ? <Spinner label="Saving" className="text-ink-400" /> : null}
          {saved && !saving ? (
            <span className="flex items-center gap-1.5 text-xs text-signal-success">
              <Check className="size-3.5" strokeWidth={2.5} aria-hidden />
              Saved
            </span>
          ) : null}
        </div>

        {suggestion && isDefault ? (
          <div className="flex flex-wrap items-center gap-2 rounded-lg border border-paper-300 bg-paper-50 px-3.5 py-2.5">
            <p className="flex-1 text-sm text-ink-600">
              Your browser is set to <strong className="font-medium">{suggestion}</strong>.
              Use that instead of UTC?
            </p>
            <Button size="sm" variant="secondary" onClick={() => void save(suggestion)}>
              Use {suggestion.split('/').pop()?.replace(/_/g, ' ')}
            </Button>
          </div>
        ) : null}

        <p className="text-xs leading-relaxed text-ink-400">
          Only day boundaries use this — every date and time ANCHOR stores stays in
          UTC. Daylight saving is handled from the zone name, which is why the list
          holds names rather than offsets like “UTC+1”.
        </p>
      </CardBody>
    </Card>
  );
}

/**
 * The tz database as the browser knows it, with a small fallback for engines that
 * do not expose `supportedValuesOf`.
 */
function supportedTimezones(): string[] {
  try {
    const values = Intl.supportedValuesOf?.('timeZone');
    if (values && values.length > 0) return [...values];
  } catch {
    // Fall through to the short list below.
  }
  const detected = authApi.detectTimezone();
  return [
    ...new Set(
      [
        'UTC',
        detected,
        'Europe/London',
        'Europe/Berlin',
        'Asia/Riyadh',
        'Asia/Dubai',
        'Asia/Tokyo',
        'America/New_York',
        'America/Los_Angeles',
      ].filter(Boolean),
    ),
  ].sort();
}
