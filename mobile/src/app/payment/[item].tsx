/**
 * One payment, like a banking app's detail sheet: change its category, who it was for, its
 * note and whether it counts; or, for something you added, everything, and remove it.
 */
import { useLocalSearchParams, useNavigation, useRouter } from 'expo-router';
import { useEffect, useState } from 'react';
import { View } from 'react-native';

import { DateField } from '@/components/date-field';
import { AmountField, Button, Card, Details, Field, Loaded, RichText, Screen, Segmented, Select, T, Toggle } from '@/components/ui';
import { api } from '@/lib/api';
import { confirm } from '@/lib/confirm';
import { useAction, useApi } from '@/lib/query';
import { space, useTheme } from '@/lib/theme';
import type { Payment } from '@/lib/types';

export default function PaymentSheet() {
  const { item } = useLocalSearchParams<{ item: string }>();
  const payment = useApi<Payment>(`/api/payments/${encodeURIComponent(item)}`);
  const navigation = useNavigation();
  useEffect(() => {
    if (payment.data) navigation.setOptions({ title: payment.data.title });
  }, [payment.data, navigation]);
  return (
    <Screen top={false}>
      <Loaded query={payment}>{(data) => <Editor data={data} />}</Loaded>
    </Screen>
  );
}

function Editor({ data }: { data: Payment }) {
  const { colors } = useTheme();
  const router = useRouter();
  const { run, busy } = useAction();
  const [category, setCategory] = useState(data.category);
  const [spentFor, setSpentFor] = useState<string | null>(data.spent_for);
  const [note, setNote] = useState(data.note);
  const [counted, setCounted] = useState(data.counted);
  const [amount, setAmount] = useState<number | null>(data.typed?.amount ?? null);
  const [description, setDescription] = useState(data.typed?.description ?? '');
  const [date, setDate] = useState(data.typed?.date ?? '');
  const [account, setAccount] = useState(data.typed?.account ?? '');
  const path = `/api/payments/${encodeURIComponent(data.item)}`;

  async function save() {
    const change: Record<string, unknown> = { category, note, counted };
    if (data.money_out) change.spent_for = spentFor;
    if (data.typed) Object.assign(change, { amount, description, date, account });
    if (data.transfer) delete change.counted;
    if (await run(() => api.patch(path, change))) router.back();
  }

  async function remove() {
    if (await confirm('Remove this expense?', `${data.title}, ${data.amount}`, 'Remove')) {
      if (await run(() => api.delete(path))) router.back();
    }
  }

  return (
    <View style={{ gap: space.lg }}>
      <View style={{ alignItems: 'center', gap: 4 }}>
        <T variant="caption">Amount</T>
        <T variant="hero" color={data.money_out ? colors.text : colors.good}>
          {data.amount}
        </T>
        <RichText text={data.sentence} variant="small" muted style={{ textAlign: 'center' }} />
      </View>
      <Card>
        {data.typed ? (
          <>
            <AmountField label="Amount" value={amount} onChange={setAmount} />
            <Field label="What was it?" value={description} onChangeText={setDescription} />
            <DateField label="Date" value={date} onChange={setDate} />
            <Select
              label="Paid with"
              value={account}
              options={data.options.accounts.map((a) => ({ key: a.key, label: a.name }))}
              onChange={(key) => setAccount(key ?? account)}
            />
          </>
        ) : null}
        <Select
          label="Category"
          value={category}
          options={data.options.categories.map((c) => ({ key: c, label: c }))}
          onChange={(key) => setCategory(key ?? category)}
        />
        {data.money_out ? (
          <View style={{ gap: 6 }}>
            <T variant="small" style={{ fontWeight: '600' }}>
              For
            </T>
            <Segmented
              options={[...data.options.labels.map((l) => ({ key: l, label: l })), { key: '', label: 'Rules decide' }]}
              value={spentFor ?? ''}
              onChange={(key) => setSpentFor(key || null)}
              scroll
            />
          </View>
        ) : null}
        <Field label="Note" value={note} onChangeText={setNote} placeholder='e.g. "Outing with Zain"' />
        {data.transfer ? (
          <T variant="caption">This moved money between your own accounts, so it isn’t spending or income.</T>
        ) : (
          <Toggle label={data.counted_label} value={counted} onChange={setCounted} />
        )}
        <Button label="Save" kind="primary" busy={busy} onPress={() => void save()} wide />
      </Card>
      <Card>
        <T variant="heading">Details</T>
        <Details rows={data.details} />
      </Card>
      {data.typed ? <Button label="Remove this expense" kind="danger" icon="delete" onPress={() => void remove()} /> : null}
    </View>
  );
}
