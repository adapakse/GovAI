import { useTranslations } from 'next-intl';
import type { PolicyResult } from '@/lib/api';

const CLS: Record<PolicyResult, string> = {
  allowed:            'bg-green-900/60 text-green-300 border-green-700',
  blocked:            'bg-red-900/60 text-red-300 border-red-700',
  oversight_required: 'bg-orange-900/60 text-orange-300 border-orange-700',
  error:              'bg-purple-900/60 text-purple-300 border-purple-700',
};

export default function PolicyBadge({ result }: { result: string }) {
  const t = useTranslations('common.policyResult.short');
  const known = Object.prototype.hasOwnProperty.call(CLS, result);
  const label = known ? t(result as PolicyResult) : result;
  const cls = known ? CLS[result as PolicyResult] : 'bg-gray-700 text-gray-300 border-gray-600';
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-semibold border ${cls}`}>
      {label}
    </span>
  );
}
