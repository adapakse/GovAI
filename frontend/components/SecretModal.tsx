'use client';

import { useState } from 'react';
import { useTranslations } from 'next-intl';

// Okno z sekretem pokazywanym jednorazowo (hasło tymczasowe, klucz API):
// wartość do skopiowania + ostrzeżenie, że po zamknięciu nie da się jej odczytać.
export default function SecretModal({
  title, description, label, secret, onClose,
}: {
  title: string;
  description?: React.ReactNode;
  label: string;
  secret: string;
  onClose: () => void;
}) {
  const t = useTranslations('common.secretModal');
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(secret);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }

  return (
    <Modal title={title} onClose={onClose} closeOnBackdrop={false}>
      <div className="space-y-4">
        {description && <div className="text-sm text-mgray">{description}</div>}
        <div>
          <div className="text-xs text-mgray mb-1.5 uppercase tracking-wider font-semibold">{label}</div>
          <div className="flex gap-2">
            <code className="flex-1 min-w-0 break-all bg-navy border border-teal/40 rounded-lg px-3 py-2 text-teal font-mono text-sm select-all">
              {secret}
            </code>
            <button
              onClick={copy}
              className="px-3 py-2 text-sm font-semibold rounded-lg border border-teal/50 text-teal hover:bg-teal/10 flex-shrink-0"
            >
              {copied ? t('copied') : t('copy')}
            </button>
          </div>
        </div>
        <div className="px-4 py-3 rounded-lg bg-orange-900/20 border border-orange-700/50 text-orange-200 text-sm">
          {t('warning')}
        </div>
        <div className="flex justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 bg-teal text-dark text-sm font-semibold rounded-lg hover:bg-teal/90"
          >
            {t('done')}
          </button>
        </div>
      </div>
    </Modal>
  );
}

/** Potwierdzenie akcji (zamiast window.confirm). */
export function ConfirmModal({
  title, message, confirmLabel, danger = false, busy = false, onConfirm, onCancel,
}: {
  title: string;
  message: React.ReactNode;
  confirmLabel: string;
  danger?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const t = useTranslations('common.secretModal');
  return (
    <Modal title={title} onClose={onCancel}>
      <div className="space-y-5">
        <div className="text-sm text-mgray">{message}</div>
        <div className="flex justify-end gap-3">
          <button
            onClick={onCancel}
            className="px-4 py-2 text-mgray text-sm border border-blue/30 rounded-lg hover:bg-blue/10"
          >
            {t('cancel')}
          </button>
          <button
            onClick={onConfirm}
            disabled={busy}
            className={`px-4 py-2 text-sm font-semibold rounded-lg disabled:opacity-40 ${
              danger ? 'bg-govred text-white hover:bg-govred/80' : 'bg-teal text-dark hover:bg-teal/90'
            }`}
          >
            {busy ? '...' : confirmLabel}
          </button>
        </div>
      </div>
    </Modal>
  );
}

/** Prosty modal w stylu aplikacji. closeOnBackdrop=false — tylko jawne zamknięcie. */
export function Modal({
  title, onClose, children, closeOnBackdrop = true, wide = false,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  closeOnBackdrop?: boolean;
  wide?: boolean;
}) {
  const t = useTranslations('common.secretModal');
  return (
    <div
      className="fixed inset-0 bg-black/70 z-50 flex items-center justify-center p-4"
      onClick={closeOnBackdrop ? onClose : undefined}
    >
      <div
        className={`bg-dark border border-blue/40 rounded-xl w-full ${wide ? 'max-w-3xl' : 'max-w-lg'} max-h-[90vh] overflow-y-auto shadow-2xl`}
        onClick={e => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <div className="px-6 py-4 border-b border-blue/30 flex items-start justify-between gap-4">
          <h2 className="font-semibold text-white">{title}</h2>
          <button onClick={onClose} className="text-mgray hover:text-white text-lg leading-none" aria-label={t('close')}>
            ✕
          </button>
        </div>
        <div className="px-6 py-5">{children}</div>
      </div>
    </div>
  );
}
