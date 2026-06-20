import type { RiskLevel } from '@/lib/api';

const MAP: Record<RiskLevel, { label: string; cls: string }> = {
  minimal:      { label: 'MINIMALNE',      cls: 'bg-green-900/60 text-green-300 border-green-700' },
  limited:      { label: 'OGRANICZONE',    cls: 'bg-blue-900/60 text-blue-300 border-blue-700' },
  high:         { label: 'WYSOKIE',        cls: 'bg-orange-900/60 text-orange-300 border-orange-700' },
  unacceptable: { label: 'NIEDOPUSZCZALNE',cls: 'bg-red-900/60 text-red-300 border-red-700' },
};

export default function RiskBadge({ level }: { level: RiskLevel }) {
  const { label, cls } = MAP[level] ?? MAP.minimal;
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-semibold border ${cls}`}>
      {label}
    </span>
  );
}
