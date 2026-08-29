type ClassValue = string | false | null | undefined;

/** Joins conditional class names. Falsy entries are dropped. */
export function cn(...values: ClassValue[]): string {
  return values.filter(Boolean).join(' ');
}
