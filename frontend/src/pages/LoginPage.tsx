import { useState, type FormEvent } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';

import { Button } from '@/components/ui/Button';
import { FormError } from '@/components/ui/ErrorState';
import { Spinner } from '@/components/ui/Spinner';
import { TextField } from '@/components/ui/TextField';
import { AuthCard } from '@/features/auth/AuthCard';
import { useAuth } from '@/features/auth/useAuth';
import { toErrorMessage } from '@/services/api/client';
import { paths } from '@/routes/paths';

interface LocationState {
  from?: string;
}

export function LoginPage() {
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Return the user to whatever they were trying to reach before the redirect.
  const destination = (location.state as LocationState | null)?.from ?? paths.dashboard;

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);

    try {
      await signIn(email.trim(), password);
      navigate(destination, { replace: true });
    } catch (caught) {
      setError(toErrorMessage(caught));
      setIsSubmitting(false);
    }
  }

  return (
    <AuthCard
      title="Sign in"
      subtitle="Pick up where you left off."
      footer={
        <>
          New to ANCHOR?{' '}
          <Link to={paths.register} className="font-medium text-ink-800 underline underline-offset-4">
            Create an account
          </Link>
        </>
      }
    >
      <form onSubmit={handleSubmit} className="space-y-4" noValidate>
        {error ? <FormError message={error} /> : null}

        <TextField
          label="Email"
          type="email"
          autoComplete="email"
          required
          value={email}
          placeholder="you@university.edu"
          disabled={isSubmitting}
          onChange={(event) => setEmail(event.target.value)}
        />

        <TextField
          label="Password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          disabled={isSubmitting}
          onChange={(event) => setPassword(event.target.value)}
        />

        <Button type="submit" className="w-full" disabled={isSubmitting}>
          {isSubmitting ? <Spinner label="Signing in" /> : null}
          {isSubmitting ? 'Signing in…' : 'Sign in'}
        </Button>
      </form>
    </AuthCard>
  );
}
