import { useTranslations } from 'next-intl';
import type { RiskLevel } from '@/lib/api';

const CLS: Record<RiskLevel, string> = {
  minimal:      'bg-green-900/60 text-green-300 border-green-700',
  limited:      'bg-blue-900/60 text-blue-300 border-blue-700',
  high:         'bg-orange-900/60 text-orange-300 border-orange-700',
  unacceptable: 'bg-red-900/60 text-red-300 border-red-700',
};

export default function RiskBadge({ level }: { level: RiskLevel }) {
  const t = useTranslations('common.risk.short');
  const key: RiskLevel = Object.prototype.hasOwnProperty.call(CLS, level) ? level : 'minimal';
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-semibold border ${CLS[key]}`}>
      {t(key)}
    </span>
  );
}
