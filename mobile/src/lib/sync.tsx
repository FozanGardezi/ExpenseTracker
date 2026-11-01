/**
 * Syncing Gmail: start a sync, watch its progress while it runs on the server, and refresh
 * everything when it's done. The app also asks for a sync when it opens; the server only
 * does one if the last was more than 6 hours ago.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type PropsWithChildren } from 'react';
import { AppState } from 'react-native';

import { useToast } from '@/components/toast';
import { api, messageOf } from '@/lib/api';
import { queryClient } from '@/lib/query';
import type { SyncJob } from '@/lib/types';

type StartResult = { started: boolean; reason: string; job: SyncJob | null; searching?: string };
type SyncState = {
  job: SyncJob | null;
  running: boolean;
  start: (body: object, path?: string) => Promise<StartResult | null>;
};

const SyncContext = createContext<SyncState | null>(null);

export function SyncProvider({ children }: PropsWithChildren) {
  const toast = useToast();
  const [job, setJob] = useState<SyncJob | null>(null);
  const watching = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopWatching = useCallback(() => {
    if (watching.current) clearInterval(watching.current);
    watching.current = null;
  }, []);

  const watch = useCallback(() => {
    if (watching.current) return;
    watching.current = setInterval(async () => {
      try {
        const { job: now } = await api.get<{ job: SyncJob | null }>('/api/sync');
        setJob(now);
        if (!now?.running) {
          stopWatching();
          if (now?.error) toast.show(now.error, 'error');
          else if (now?.message) toast.show(now.message);
          await queryClient.invalidateQueries();
        }
      } catch {
        stopWatching();
      }
    }, 1200);
  }, [stopWatching, toast]);

  const start = useCallback(
    async (body: object, path = '/api/sync') => {
      try {
        const result = await api.post<StartResult>(path, body);
        if (result.job) setJob(result.job);
        if (result.started || result.job?.running) watch();
        return result;
      } catch (error) {
        toast.show(messageOf(error), 'error');
        return null;
      }
    },
    [toast, watch],
  );

  useEffect(() => {
    // Opening the app (or coming back to it) syncs if the last sync is old. `start` only sets
    // state once the server answers, so this doesn't render twice.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void start({ auto: true });
    const subscription = AppState.addEventListener('change', (state) => {
      if (state === 'active') void start({ auto: true });
    });
    return () => {
      subscription.remove();
      stopWatching();
    };
  }, [start, stopWatching]);

  const value = useMemo(() => ({ job, running: !!job?.running, start }), [job, start]);
  return <SyncContext.Provider value={value}>{children}</SyncContext.Provider>;
}

export function useSync(): SyncState {
  const sync = useContext(SyncContext);
  if (!sync) throw new Error('useSync outside SyncProvider');
  return sync;
}
