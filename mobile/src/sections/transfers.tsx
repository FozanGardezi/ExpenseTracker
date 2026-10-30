/** Activity → Transfers: money sent to people or accounts, which only counts as spending when you say so. */
import { useState } from 'react';
import { View } from 'react-native';

import { PeriodPicker, type Period } from '@/components/period';
import { PaymentList } from '@/components/payment-list';
import { AmountField, Button, Card, Loaded, Notice, Stats, T } from '@/components/ui';
import { api } from '@/lib/api';
import { useAction, useApi } from '@/lib/query';
import { space } from '@/lib/theme';
import type { Transfers } from '@/lib/types';

export function TransfersSection() {
  const [period, setPeriod] = useState<Period>({});
  const transfers = useApi<Transfers>('/api/activity/transfers', period);
  return <Loaded query={transfers}>{(data) => <Body data={data} period={period} setPeriod={setPeriod} />}</Loaded>;
}

function Body({ data, period, setPeriod }: { data: Transfers; period: Period; setPeriod: (p: Period) => void }) {
  const [limit, setLimit] = useState<number | null>(data.limit);
  const { run, busy } = useAction();
  return (
    <View style={{ gap: space.lg }}>
      <Card>
        <AmountField
          key={String(data.limit)}
          label={`Count transfers up to this amount as spending (${data.limit_currency})`}
          value={limit}
          onChange={setLimit}
          hint="Small transfers, like paying a shop or a rickshaw by JazzCash or Raast, are usually spending; big ones are often moving money. 0 counts none."
        />
        <Button label="Save" busy={busy} onPress={() => void run(() => api.put('/api/activity/transfers/limit', { limit: limit ?? 0 }))} />
        <T variant="caption">
          A bigger transfer counts as spending when you turn on Count as spending or give it a category, e.g. money you
          sent a friend for your share of an outing.
        </T>
      </Card>
      {data.empty ? (
        <Notice text="No transfers yet. Money you send to people or other accounts appears here." />
      ) : (
        <>
          <PeriodPicker periods={data.periods} value={period} shown={data} onChange={setPeriod} />
          <Stats items={data.summary ?? []} />
          <Card>
            <PaymentList rows={data.rows ?? []} slots={data.slots} byDay={false} empty="No transfers in this period." />
          </Card>
        </>
      )}
    </View>
  );
}
