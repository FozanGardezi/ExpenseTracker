/**
 * Fetching screens with React Query: cached, refreshed when the app comes back, and
 * refetched after any change (a change to one payment can move figures on every tab).
 */
import { keepPreviousData, QueryClient, useMutation, useQuery } from '@tanstack/react-query';
import { useState } from 'react';

import { api, ApiError, messageOf, type Query } from '@/lib/api';
import { useToast } from '@/components/toast';

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: (count, error) => !(error instanceof ApiError && error.status >= 400 && error.status < 500) && count < 2,
    },
  },
});

/** One screen's data from GET `path`. Changing a filter keeps the figures shown until the new ones arrive. */
export function useApi<T>(path: string, query?: Query, enabled = true) {
  return useQuery({
    queryKey: [path, query ?? {}],
    queryFn: () => api.get<T>(path, query),
    enabled,
    placeholderData: keepPreviousData,
  });
}

/**
 * Run a change: shows its message (or error) as a toast and refreshes everything.
 * `run` resolves to the server's answer, or undefined if it failed.
 */
export function useAction() {
  const toast = useToast();
  const [error, setError] = useState<ApiError | null>(null);
  const mutation = useMutation({
    mutationFn: (action: () => Promise<unknown>) => action(),
  });
  async function run<T>(action: () => Promise<T>, options: { quiet?: boolean; keepError?: boolean } = {}) {
    setError(null);
    try {
      const result = await mutation.mutateAsync(action);
      const message = (result as { message?: unknown } | undefined)?.message;
      if (!options.quiet && typeof message === 'string') toast.show(message);
      await queryClient.invalidateQueries();
      return result as T;
    } catch (caught) {
      if (caught instanceof ApiError) setError(caught);
      if (!options.keepError) toast.show(messageOf(caught), 'error');
      return undefined;
    }
  }
  return { run, busy: mutation.isPending, error, clearError: () => setError(null) };
}
