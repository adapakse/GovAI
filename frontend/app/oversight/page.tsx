'use client';

import { useCallback, useEffect, useState } from 'react';
import { api, OversightTask } from '@/lib/api';
import RiskBadge from '@/components/RiskBadge';
import OversightModal from '@/components/OversightModal';

function TTLTimer({ expiresAt }: { expiresAt: string }) {
  const [remaining, setRemaining] = useState(0);

  useEffect(() => {
    const calc = () => setRemaining(Math.max(0, new Date(expiresAt).getTime() - Date.now()));
    calc();
    const id = setInterval(calc, 1000);
    return () => clearInterval(id);
  }, [expiresAt]);

  const mins = Math.floor(remaining / 60000);
  const secs = Math.floor((remaining % 60000) / 1000);
  const color = remaining > 30 * 60000 ? 'text-green-400' : remaining > 5 * 60000 ? 'text-yellow-400' : 'text-red-400 animate-pulse';
  const pct = Math.min(100, (remaining / (60 * 60000)) * 100);
  const barColor = remaining > 30 * 60000 ? 'bg-green-500' : remaining > 5 * 60000 ? 'bg-yellow-500' : 'bg-red-500';

  return (
    <div>
      <div className={`font-mono font-bold text-lg ${color}`}>{mins}m {secs}s</div>
      <div className="mt-1 h-1 bg-blue/30 rounded-full overflow-hidden w-24">
        <div className={`h-full ${barColor} transition-all duration-1000`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export default function OversightPage() {
  const [tasks, setTasks] = useState<OversightTask[]>([]);
  const [selected, setSelected] = useState<OversightTask | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    api.oversight.pending()
      .then(setTasks)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 10_000);
    return () => clearInterval(id);
  }, [load]);

  async function openReview(task: OversightTask) {
    try {
      await api.oversight.startReview(task.id);
    } catch {}
    setSelected(task);
  }

  return (
    <div className="space-y-6">
      {/* Nagłówek */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Nadzór Człowieka</h1>
          <p className="text-mgray text-sm mt-0.5">
            Decyzje agentów wysokiego ryzyka wymagają zatwierdzenia · odświeżane co 10s
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className={`text-sm font-semibold px-4 py-2 rounded-lg ${
            tasks.length > 0 ? 'bg-orange-900/40 text-orange-300 border border-orange-700' : 'bg-green-900/40 text-green-300 border border-green-700'
          }`}>
            {tasks.length > 0 ? `${tasks.length} oczekuje` : 'Wszystko zatwierdzone'}
          </div>
          <button onClick={load} className="text-xs text-mgray border border-blue/30 px-3 py-2 rounded-lg hover:bg-blue/20">
            Odśwież
          </button>
        </div>
      </div>

      {/* Info o pomiarze czasu */}
      <div className="bg-navy border border-blue/30 rounded-lg px-5 py-3 flex items-start gap-3">
        <span className="text-teal text-lg">ⓘ</span>
        <div className="text-sm text-mgray">
          <span className="text-white font-medium">Ochrona przed pozornym nadzorem: </span>
          Czas przeglądu każdego zadania jest mierzony. Zatwierdzenie w mniej niż 10 sekund
          od otwarcia karty generuje alert i jest rejestrowane w dzienniku audytowym (art. 14 EU AI Act).
        </div>
      </div>

      {/* Stan pusty */}
      {loading && <div className="text-mgray animate-pulse py-8 text-center">Ładowanie zadań nadzoru...</div>}

      {!loading && tasks.length === 0 && (
        <div className="text-center py-20 text-mgray">
          <div className="text-4xl mb-4">✓</div>
          <div className="text-xl font-semibold text-white">Brak oczekujących zadań</div>
          <div className="text-sm mt-2">Wszystkie decyzje zostały rozpatrzone.</div>
        </div>
      )}

      {/* Siatka kart */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {tasks.map(task => (
          <div key={task.id} className="bg-navy border border-blue/30 rounded-xl flex flex-col hover:border-teal/50 transition-colors">
            {/* Header karty */}
            <div className="px-4 py-3 border-b border-blue/20 flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="font-semibold text-white text-sm truncate">{task.agent_name}</div>
                <div className="mt-1">
                  <RiskBadge level={task.risk_level} />
                </div>
              </div>
              <TTLTimer expiresAt={task.ttl_expires_at} />
            </div>

            {/* Treść */}
            <div className="px-4 py-3 flex-1">
              <div className="text-xs text-mgray mb-1.5">{task.decision_type}</div>
              <p className="text-sm text-lgray leading-relaxed line-clamp-4">
                {task.agent_decision}
              </p>
            </div>

            {/* Footer */}
            <div className="px-4 py-3 border-t border-blue/20 flex items-center justify-between">
              <div className="text-xs text-mgray">
                {new Date(task.created_at).toLocaleTimeString('pl-PL')}
              </div>
              <button
                onClick={() => openReview(task)}
                className="px-4 py-1.5 bg-teal text-dark text-sm font-semibold rounded-lg hover:bg-teal/90 transition-colors"
              >
                Przejrzyj
              </button>
            </div>
          </div>
        ))}
      </div>

      {/* Modal */}
      {selected && (
        <OversightModal
          task={selected}
          onClose={() => setSelected(null)}
          onDone={load}
        />
      )}
    </div>
  );
}
