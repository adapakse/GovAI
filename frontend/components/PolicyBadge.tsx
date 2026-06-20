import type { PolicyResult } from '@/lib/api';

const MAP: Record<string, { label: string; cls: string }> = {
  allowed:            { label: 'OK',       cls: 'bg-green-900/60 text-green-300 border-green-700' },
  blocked:            { label: 'BLOKADA', cls: 'bg-red-900/60 text-red-300 border-red-700' },
  oversight_required: { label: 'NADZÓR',  cls: 'bg-orange-900/60 text-orange-300 border-orange-700' },
};

export default function PolicyBadge({ result }: { result: string }) {
  const { label, cls } = MAP[result] ?? { label: result, cls: 'bg-gray-700 text-gray-300 border-gray-600' };
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-semibold border ${cls}`}>
      {label}
    </span>
  );
}
