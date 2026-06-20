'use client';

import { useState } from 'react';
import { api, OversightTask } from '@/lib/api';
import RiskBadge from './RiskBadge';

interface Props {
  task: OversightTask;
  onClose: () => void;
  onDone: () => void;
}

export default function OversightModal({ task, onClose, onDone }: Props) {
  const [action, setAction] = useState<'approved' | 'rejected' | 'escalated' | null>(null);
  const [comment, setComment] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<{ alert?: string; action?: string } | null>(null);
  const [error, setError] = useState('');

  async function submit() {
    if (!action) return;
    if ((action === 'rejected' || action === 'escalated') && !comment.trim()) {
      setError('Komentarz jest wymagany przy odrzuceniu lub eskalacji.');
      return;
    }
    setSubmitting(true);
    setError('');
    try {
      const res = await api.oversight.review(task.id, action, comment || undefined) as Record<string, string>;
      setResult(res);
      setTimeout(() => { onDone(); onClose(); }, 2500);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Błąd zapisu decyzji');
    } finally {
      setSubmitting(false);
    }
  }

  const ttlDate = new Date(task.ttl_expires_at);
  const remaining = Math.max(0, ttlDate.getTime() - Date.now());
  const mins = Math.floor(remaining / 60000);
  const secs = Math.floor((remaining % 60000) / 1000);
  const ttlColor = remaining > 30 * 60000 ? 'text-green-400' : remaining > 5 * 60000 ? 'text-yellow-400' : 'text-red-400';

  return (
    <div className="fixed inset-0 bg-black/70 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div
        className="bg-dark border border-blue/40 rounded-xl w-full max-w-2xl max-h-[90vh] overflow-y-auto shadow-2xl"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="px-6 py-4 border-b border-blue/30 flex items-start justify-between">
          <div>
            <div className="flex items-center gap-3">
              <span className="text-lg font-bold text-white">{task.agent_name}</span>
              <RiskBadge level={task.risk_level} />
            </div>
            <div className="text-xs text-mgray mt-1">Task ID: {task.task_id}</div>
          </div>
          <div className="text-right">
            <div className="text-xs text-mgray">Pozostały czas</div>
            <div className={`font-mono font-bold text-xl ${ttlColor}`}>
              {mins}m {secs}s
            </div>
          </div>
        </div>

        {/* Decyzja agenta */}
        <div className="px-6 py-4">
          <div className="text-xs uppercase text-mgray tracking-wider mb-2">Decyzja agenta</div>
          <div className="bg-navy/80 rounded-lg p-4 text-sm text-lgray leading-relaxed border border-blue/20">
            {task.agent_decision}
          </div>
        </div>

        {/* Info */}
        <div className="px-6 pb-4 grid grid-cols-2 gap-4 text-xs text-mgray">
          <div>
            <span className="text-mgray/60">Typ decyzji: </span>
            <span>{task.decision_type}</span>
          </div>
          <div>
            <span className="text-mgray/60">Zgłoszone: </span>
            <span>{new Date(task.created_at).toLocaleTimeString('pl-PL')}</span>
          </div>
        </div>

        {/* Alert o pozornym nadzorze */}
        <div className="px-6 pb-3">
          <div className="bg-yellow-900/30 border border-yellow-700/50 rounded-lg px-4 py-2 text-xs text-yellow-300">
            ⚠ Czas przeglądu jest mierzony od momentu otwarcia tego okna. Decyzja w czasie krótszym niż 10 sekund zostanie oznaczona jako pozorny nadzór.
          </div>
        </div>

        {/* Wynik zatwierdzenia */}
        {result && (
          <div className={`mx-6 mb-4 rounded-lg px-4 py-3 text-sm font-medium ${
            result.action === 'approved' ? 'bg-green-900/40 text-green-300 border border-green-700' :
            result.action === 'rejected' ? 'bg-red-900/40 text-red-300 border border-red-700' :
            'bg-orange-900/40 text-orange-300 border border-orange-700'
          }`}>
            Zapisano: {result.action?.toUpperCase()}
            {result.alert && <div className="mt-1 text-yellow-300 text-xs">{result.alert}</div>}
          </div>
        )}

        {/* Przyciski akcji */}
        {!result && (
          <div className="px-6 pb-4">
            <div className="text-xs uppercase text-mgray tracking-wider mb-3">Twoja decyzja</div>
            <div className="flex gap-2 mb-4">
              {(['approved', 'rejected', 'escalated'] as const).map(a => (
                <button
                  key={a}
                  onClick={() => setAction(a)}
                  className={`flex-1 py-2.5 rounded-lg text-sm font-semibold border transition-all ${
                    action === a
                      ? a === 'approved'   ? 'bg-green-600 border-green-500 text-white'
                      : a === 'rejected'   ? 'bg-red-600 border-red-500 text-white'
                      :                     'bg-orange-600 border-orange-500 text-white'
                      : 'bg-navy border-blue/40 text-mgray hover:border-blue/70'
                  }`}
                >
                  {a === 'approved' ? '✓ Zatwierdź' : a === 'rejected' ? '✕ Odrzuć' : '↑ Eskaluj'}
                </button>
              ))}
            </div>
            <textarea
              value={comment}
              onChange={e => setComment(e.target.value)}
              placeholder={action === 'approved' ? 'Opcjonalny komentarz...' : 'Uzasadnienie (wymagane)'}
              className="w-full bg-navy border border-blue/40 rounded-lg px-3 py-2.5 text-sm text-white placeholder-mgray/50 resize-none focus:outline-none focus:border-teal"
              rows={3}
            />
            {error && <div className="mt-2 text-xs text-red-400">{error}</div>}
          </div>
        )}

        {/* Footer */}
        {!result && (
          <div className="px-6 pb-5 flex justify-end gap-3">
            <button onClick={onClose} className="px-5 py-2 rounded-lg text-sm text-mgray border border-blue/30 hover:bg-blue/20 transition-colors">
              Anuluj
            </button>
            <button
              onClick={submit}
              disabled={!action || submitting}
              className="px-6 py-2 rounded-lg text-sm font-semibold bg-teal text-dark hover:bg-teal/90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {submitting ? 'Zapisywanie...' : 'Zapisz decyzję'}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
