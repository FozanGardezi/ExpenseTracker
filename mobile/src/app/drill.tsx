/** The payments behind a figure (a category, a limit, a place, part of a month), newest first,
 * with a monthly limit to keep it in check. */
import { useLocalSearchParams, useNavigation } from 'expo-router';
import { useEffect, useState } from 'react';

import { PaymentList } from '@/components/payment-list';
import { AmountField, Button, Card, Loaded, Screen, T } from '@/components/ui';
import { api } from '@/lib/api';
import { useAction, useApi } from '@/lib/query';
import type { Drill } from '@/lib/types';

export default function DrillSheet() {
  const params = useLocalSearchParams<{ kind: string; key?: string; month?: string; spent_for?: string; currency?: string; period?: string }>();
  const navigation = useNavigation();
  const drill = useApi<Drill>('/api/home/drill', params);
  useEffect(() => {
    if (drill.data) navigation.setOptions({ title: drill.data.title });
  }, [drill.data, navigation]);
  return (
    <Screen top={false}>
      <Loaded query={drill}>
        {(data) => (
          <>
            <T variant="small" muted>
              {data.subtitle}
            </T>
            {data.limit ? <SetLimit data={data} /> : null}
            <Card>
              <PaymentList rows={data.rows} slots={data.slots} byDay={false} />
            </Card>
          </>
        )}
      </Loaded>
    </Screen>
  );
}

function SetLimit({ data }: { data: Drill }) {
  const [amount, setAmount] = useState<number | null>(data.suggested);
  const { run, busy } = useAction();
  const limit = data.limit!;
  return (
    <Card>
      <AmountField key={data.title} label="Keep it in check: a monthly limit" value={amount} onChange={setAmount} />
      <Button
        label="Set limit"
        busy={busy}
        disabled={!amount}
        onPress={() => void run(() => api.post('/api/home/budget/limits', { ...limit, amount }))}
      />
    </Card>
  );
}
