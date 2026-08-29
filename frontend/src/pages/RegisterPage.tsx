import { useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { Button } from '@/components/ui/Button';
import { FormError } from '@/components/ui/ErrorState';
import { Spinner } from '@/components/ui/Spinner';
import { TextField } from '@/components/ui/TextField';
import { AuthCard } from '@/features/auth/AuthCard';
import { useAuth } from '@/features/auth/useAuth';
import { toErrorMessage } from '@/services/api/client';
import { paths } from '@/routes/paths';

/** Mirrors MIN_PASSWORD_LENGTH in backend/app/schemas/auth.py. */
const MIN_PASSWORD_LENGTH = 8;

export function RegisterPage() {
  const { signUp } = useAuth();
  const navigate = useNavigate();

  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const passwordTooShort = password.length > 0 && password.length < MIN_PASSWORD_LENGTH;

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (passwordTooShort) return;

    setError(null);
    setIsSubmitting(true);

    try {
      await signUp(name.trim(), email.trim(), password);
      navigate(paths.dashboard, { replace: true });
    } catch (caught) {
      setError(toErrorMessage(caught));
      setIsSubmitting(false);
    }
  }

  return (
    <AuthCard
      title="Create your account"
      subtitle="Start with one course and add your materials."
      footer={
        <>
          Already have an account?{' '}
          <Link to={paths.login} className="font-medium text-ink-800 underline underline-offset-4">
            Sign in
          </Link>
        </>
      }
    >
      <form onSubmit={handleSubmit} className="space-y-4" noValidate>
        {error ? <FormError message={error} /> : null}

        <TextField
          label="Name"
          autoComplete="name"
          required
          maxLength={120}
          value={name}
          placeholder="Ghaida Ahmed"
          disabled={isSubmitting}
          onChange={(event) => setName(event.target.value)}
        />

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
          autoComplete="new-password"
          required
          value={password}
          disabled={isSubmitting}
          hint={`At least ${MIN_PASSWORD_LENGTH} characters.`}
          {...(passwordTooShort
            ? { error: `Use at least ${MIN_PASSWORD_LENGTH} characters.` }
            : {})}
          onChange={(event) => setPassword(event.target.value)}
        />

        <Button
          type="submit"
          className="w-full"
          disabled={isSubmitting || passwordTooShort}
        >
          {isSubmitting ? <Spinner label="Creating account" /> : null}
          {isSubmitting ? 'Creating account…' : 'Create account'}
        </Button>
      </form>
    </AuthCard>
  );
}
