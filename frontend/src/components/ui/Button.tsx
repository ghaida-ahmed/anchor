import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { Link } from 'react-router-dom';

import { cn } from '@/lib/cn';

type ButtonVariant = 'primary' | 'secondary' | 'ghost';
type ButtonSize = 'sm' | 'md' | 'lg';

const BASE =
  'inline-flex items-center justify-center gap-2 rounded-lg font-medium whitespace-nowrap transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-50';

const VARIANTS: Record<ButtonVariant, string> = {
  primary: 'bg-ink-900 text-paper-50 hover:bg-ink-800',
  secondary:
    'bg-white text-ink-900 border border-paper-400 hover:border-ink-300 hover:bg-paper-50',
  ghost: 'text-ink-600 hover:bg-paper-200 hover:text-ink-900',
};

const SIZES: Record<ButtonSize, string> = {
  sm: 'h-8 px-3 text-sm',
  md: 'h-10 px-4 text-sm',
  lg: 'h-12 px-6 text-base',
};

function buttonStyles(
  variant: ButtonVariant = 'primary',
  size: ButtonSize = 'md',
  className?: string,
): string {
  return cn(BASE, VARIANTS[variant], SIZES[size], className);
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  children: ReactNode;
}

export function Button({
  variant = 'primary',
  size = 'md',
  className,
  children,
  ...props
}: ButtonProps) {
  return (
    <button className={buttonStyles(variant, size, className)} {...props}>
      {children}
    </button>
  );
}

interface ButtonLinkProps {
  to: string;
  variant?: ButtonVariant;
  size?: ButtonSize;
  className?: string;
  children: ReactNode;
}

/** Same visual treatment as `Button`, but navigates instead of firing a handler. */
export function ButtonLink({
  to,
  variant = 'primary',
  size = 'md',
  className,
  children,
}: ButtonLinkProps) {
  return (
    <Link to={to} className={buttonStyles(variant, size, className)}>
      {children}
    </Link>
  );
}
