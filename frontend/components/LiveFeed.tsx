'use client';

import { useEffect, useState } from 'react';
import { WS } from '@/lib/api';
import { formatDistanceToNow } from 'date-fns';
import { pl } from 'date-fns/locale';

interface FeedEvent {
  type: string;
  payload: Record<string, unknown>;
  ts?: string;
  receivedAt: number;
}

const TYPE_STYLE: Record<string, { label: string; dot: string }> = {
  'audit:blocked':            { label: 'BLOKADA',  dot: 'bg-red-500' },
  'audit:error':              { label: 'BŁĄD',     dot: 'bg-purple-500' },
  'oversight:pending':        { label: 'NADZÓR',   dot: 'bg-orange-400' },
  'oversight:escalated':      { label: 'ESKALACJA',dot: 'bg-red-700' },
  'audit:new_call':           { label: 'WYWOŁANIE',dot: 'bg-green-500' },
};

export default function LiveFeed() {
  const [events, setEvents] = useState<FeedEvent[]>([]);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    let ws: WebSocket;
    let retry: ReturnType<typeof setTimeout>;
    // React 18 StrictMode (dev) montuje efekt dwukrotnie (mount → cleanup → mount).
    // Bez tej flagi pierwszy WebSocket potrafi jeszcze dostarczyć wiadomość (onmessage)
    // między cleanupem a faktycznym zamknięciem połączenia — każde zdarzenie z Redis
    // renderowało się wtedy dwa razy. `cancelled` gwarantuje, że "martwe" połączenie
    // z pierwszego mountu nic już nie dopisze do stanu.
    let cancelled = false;

    function connect() {
      if (cancelled) return;
      ws = new WebSocket(`${WS}/ws/live-feed`);
      ws.onopen  = () => { if (!cancelled) setConnected(true); };
      ws.onclose = () => { if (!cancelled) { setConnected(false); retry = setTimeout(connect, 3000); } };
      ws.onerror = () => ws.close();
      ws.onmessage = (e) => {
        if (cancelled) return;
        try {
          const evt = JSON.parse(e.data) as Omit<FeedEvent, 'receivedAt'>;
          setEvents(prev => {
            // Deduplikacja po (type, call_id) — druga warstwa obok `cancelled`, na
            // wypadek gdyby przeglądarka nie zamknęła "martwego" WS wystarczająco
            // szybko (StrictMode dev mount) i oba połączenia zdążyły dostarczyć tę
            // samą wiadomość z Redis.
            const callId = (evt.payload as Record<string, unknown>)?.call_id;
            if (callId && prev.some(p => p.type === evt.type && (p.payload as Record<string, unknown>)?.call_id === callId)) {
              return prev;
            }
            return [{ ...evt, receivedAt: Date.now() }, ...prev].slice(0, 60);
          });
        } catch {}
      };
    }
    connect();
    return () => { cancelled = true; clearTimeout(retry); ws?.close(); };
  }, []);

  return (
    <div className="bg-navy rounded-lg border border-blue/30 flex flex-col h-full">
      <div className="px-4 py-3 border-b border-blue/30 flex items-center justify-between">
        <span className="text-sm font-semibold text-white">Zdarzenia real-time</span>
        <span className={`flex items-center gap-1.5 text-xs ${connected ? 'text-green-400' : 'text-red-400'}`}>
          <span className={`w-2 h-2 rounded-full ${connected ? 'bg-green-400 animate-pulse' : 'bg-red-400'}`} />
          {connected ? 'Połączono' : 'Rozłączono'}
        </span>
      </div>

      <div className="flex-1 overflow-y-auto divide-y divide-blue/20">
        {events.length === 0 && (
          <div className="px-4 py-6 text-center text-mgray/50 text-sm">
            Oczekiwanie na zdarzenia...
          </div>
        )}
        {events.map((ev, i) => {
          const style = TYPE_STYLE[ev.type] ?? { label: ev.type, dot: 'bg-blue-400' };
          const agentName = String((ev.payload as Record<string, unknown>)?.agent_name ?? '');
          const reason = String((ev.payload as Record<string, unknown>)?.block_reason ?? '');
          return (
            <div key={i} className="px-4 py-2.5 hover:bg-blue/10 transition-colors">
              <div className="flex items-center gap-2">
                <span className={`w-2 h-2 rounded-full flex-shrink-0 ${style.dot}`} />
                <span className="text-xs font-semibold text-mgray">{style.label}</span>
                <span className="ml-auto text-xs text-mgray/50">
                  {formatDistanceToNow(ev.receivedAt, { addSuffix: true, locale: pl })}
                </span>
              </div>
              {agentName && <div className="text-xs text-white mt-0.5 pl-4">{agentName}</div>}
              {reason && <div className="text-xs text-red-300 mt-0.5 pl-4 truncate">{reason}</div>}
            </div>
          );
        })}
      </div>
    </div>
  );
}
