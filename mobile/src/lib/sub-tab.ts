/** The open sub-tab lives in the address (/activity?tab=transfers), so it can be linked to. */
import { useLocalSearchParams, useRouter } from 'expo-router';

export function useSubTab<K extends string>(keys: readonly K[]): [K, (key: K) => void] {
  const { tab } = useLocalSearchParams<{ tab?: string }>();
  const router = useRouter();
  const current = keys.includes(tab as K) ? (tab as K) : keys[0];
  return [current, (key: K) => router.setParams({ tab: key })];
}
