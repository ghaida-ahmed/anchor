import { X } from 'lucide-react';
import { useEffect, useId, useRef, type ReactNode } from 'react';

interface DialogProps {
  open: boolean;
  title: string;
  description?: string;
  onClose: () => void;
  children: ReactNode;
}

/**
 * Modal built on the native `<dialog>` element, which gives focus trapping, the
 * top layer and Escape handling without a dependency or a portal.
 */
export function Dialog({ open, title, description, onClose, children }: DialogProps) {
  const ref = useRef<HTMLDialogElement>(null);
  // Generated, not hardcoded: two dialogs mounted at once would otherwise share
  // an id and the label association would point at whichever rendered first.
  const titleId = useId();
  const descriptionId = useId();

  useEffect(() => {
    const element = ref.current;
    if (!element) return;

    if (open && !element.open) element.showModal();
    if (!open && element.open) element.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      {...(description ? { "aria-describedby": descriptionId } : {})}
      onClose={onClose}
      // Escape fires `cancel` then `close`; both funnel into onClose above.
      onClick={(event) => {
        // Clicks land on the backdrop only when the target is the dialog itself.
        if (event.target === ref.current) onClose();
      }}
      className="m-auto w-[min(30rem,calc(100vw-2rem))] rounded-card border border-paper-300 bg-white p-0 text-ink-900 shadow-lift backdrop:bg-ink-950/40"
    >
      <div className="flex items-start justify-between gap-4 border-b border-paper-200 px-6 py-4">
        <div>
          <h2 id={titleId} className="font-serif text-lg text-ink-900">
            {title}
          </h2>
          {description ? (
            <p id={descriptionId} className="mt-0.5 text-sm text-ink-500">
              {description}
            </p>
          ) : null}
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="-mr-1 rounded p-1 text-ink-400 transition-colors hover:bg-paper-200 hover:text-ink-800"
        >
          <X className="size-4" strokeWidth={2} aria-hidden />
        </button>
      </div>

      <div className="px-6 py-5">{children}</div>
    </dialog>
  );
}
