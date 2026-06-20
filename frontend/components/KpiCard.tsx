interface Props {
  label: string;
  value: string | number;
  sub?: string;
  accent?: 'teal' | 'red' | 'orange' | 'green';
}

const ACCENT = {
  teal:   'border-teal text-teal',
  red:    'border-red-500 text-red-400',
  orange: 'border-orange-500 text-orange-400',
  green:  'border-green-500 text-green-400',
};

export default function KpiCard({ label, value, sub, accent = 'teal' }: Props) {
  return (
    <div className={`bg-navy border-l-4 ${ACCENT[accent].split(' ')[0]} rounded-lg p-4 flex flex-col gap-1`}>
      <div className="text-xs text-mgray uppercase tracking-wider">{label}</div>
      <div className={`text-3xl font-bold ${ACCENT[accent].split(' ')[1]}`}>{value}</div>
      {sub && <div className="text-xs text-mgray/70">{sub}</div>}
    </div>
  );
}
