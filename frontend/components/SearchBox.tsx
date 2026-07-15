'use client';

// Reużywalne pole wyszukiwania dla długich list.
// Spójny wygląd (ikona lupy, przycisk czyszczenia, licznik wyników).

export default function SearchBox({
  value,
  onChange,
  placeholder = 'Szukaj...',
  count,
  total,
  className = '',
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  count?: number;   // liczba dopasowań (po filtrze)
  total?: number;   // liczba wszystkich pozycji
  className?: string;
}) {
  const showCount = count != null && value.trim().length > 0;
  return (
    <div className={`relative flex-1 min-w-[220px] ${className}`}>
      <span className="absolute left-3 top-1/2 -translate-y-1/2 text-mgray/50 pointer-events-none">
        <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6">
          <circle cx="7" cy="7" r="4.5" />
          <line x1="10.5" y1="10.5" x2="14" y2="14" strokeLinecap="round" />
        </svg>
      </span>
      <input
        type="text"
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full bg-navy border border-blue/40 rounded-lg pl-9 pr-20 py-2 text-sm text-white placeholder:text-mgray/50 focus:outline-none focus:border-teal"
      />
      <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-2">
        {showCount && (
          <span className="text-[11px] text-mgray/60 tabular-nums">
            {count}{total != null ? `/${total}` : ''}
          </span>
        )}
        {value && (
          <button
            onClick={() => onChange('')}
            aria-label="Wyczyść"
            className="text-mgray/50 hover:text-white w-5 h-5 flex items-center justify-center rounded"
          >
            ✕
          </button>
        )}
      </div>
    </div>
  );
}
