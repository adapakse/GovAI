'use client';

import { useTranslations } from 'next-intl';

// Plakietka wiersza platformy (tenant_id NULL) — zarządza nim GovAI,
// organizacja ma go tylko do odczytu.
export default function PlatformBadge({ label, hint }: { label?: string; hint?: string }) {
  const t = useTranslations('common.platform');
  return (
    <span
      title={hint ?? t('rowHint')}
      className="text-[10px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded border border-mgray/30 text-mgray/80 bg-mgray/10 cursor-help whitespace-nowrap"
    >
      {label ?? t('badge')}
    </span>
  );
}
