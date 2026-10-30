/**
 * Something your emails don't show, like cash for samosas; or a bank's SMS or app
 * notification, pasted in and read the same way as an alert email.
 */
import { useRouter } from 'expo-router';
import { useState } from 'react';
import { View } from 'react-native';

import { DateField } from '@/components/date-field';
import { AmountField, Button, Card, Field, Loaded, Notice, Screen, Segmented, Select, T } from '@/components/ui';
import { api, ApiError, messageOf } from '@/lib/api';
import { today } from '@/lib/format';
import { useAction, useApi } from '@/lib/query';
import { space } from '@/lib/theme';
import type { ExpenseOptions, Parsed } from '@/lib/types';

export default function AddExpense() {
  const options = useApi<ExpenseOptions>('/api/expenses/options');
  const [how, setHow] = useState<'typed' | 'message'>('typed');
  return (
    <Screen top={false}>
      <Segmented
        options={[
          { key: 'typed', label: 'Type it in' },
          { key: 'message', label: 'Paste a bank message' },
        ]}
        value={how}
        onChange={setHow}
      />
      <Loaded query={options}>{(data) => (how === 'typed' ? <Typed options={data} /> : <Pasted options={data} />)}</Loaded>
    </Screen>
  );
}

function Pasted({ options }: { options: ExpenseOptions }) {
  const [text, setText] = useState('');
  const [account, setAccount] = useState<string | null>(null);
  const [parsed, setParsed] = useState<Parsed | null>(null);
  const [reading, setReading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function read(from: string | null) {
    setReading(true);
    setError(null);
    try {
      const result = await api.post<Parsed>('/api/expenses/parse', { text, account: from });
      setParsed(result);
      setAccount(result.account);
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setReading(false);
    }
  }

  return (
    <View style={{ gap: space.lg }}>
      <Card>
        <Field
          label="The SMS or notification"
          value={text}
          onChangeText={(t) => {
            setText(t);
            setParsed(null);
          }}
          multiline
          placeholder="e.g. PKR 750 paid to DOUBLE SHOT from A/c **1234 on 05-Oct-2026 18:05"
          hint="Copy the message from your bank or wallet and paste it here. Its amount, payee and date are read the same way as an alert email."
        />
        {parsed ? (
          <Select
            label="From"
            value={account}
            options={options.message_accounts.map((a) => ({ key: a.key, label: a.name }))}
            onChange={(key) => void read(key)}
          />
        ) : null}
        {!parsed ? <Button label="Read message" kind="primary" busy={reading} disabled={!text.trim()} onPress={() => void read(null)} /> : null}
        {error ? <Notice kind="error" text={error} /> : null}
        {parsed && !parsed.ok ? <Notice kind="warning" text={parsed.reason} /> : null}
      </Card>
      {parsed?.ok ? (
        <Confirm
          key={`${parsed.account}-${parsed.amount}-${parsed.date}`}
          options={options}
          how="message"
          text={text}
          account={parsed.account}
          start={{ amount: parsed.amount, description: parsed.description, date: parsed.date }}
          moneyIn={parsed.direction === 'credit'}
        />
      ) : null}
    </View>
  );
}

function Typed({ options }: { options: ExpenseOptions }) {
  return <Confirm options={options} how="typed" account="cash" start={{ amount: null, description: '', date: today() }} moneyIn={false} />;
}

function Confirm({
  options,
  how,
  text = '',
  account: firstAccount,
  start,
  moneyIn,
}: {
  options: ExpenseOptions;
  how: 'typed' | 'message';
  text?: string;
  account: string;
  start: { amount: number | null; description: string; date: string };
  moneyIn: boolean;
}) {
  const router = useRouter();
  const { run, busy, error, clearError } = useAction();
  const [amount, setAmount] = useState(start.amount);
  const [description, setDescription] = useState(start.description);
  const [date, setDate] = useState(start.date);
  const [account, setAccount] = useState(firstAccount);
  const [category, setCategory] = useState<string | null>(null);
  const [spentFor, setSpentFor] = useState<string>('');
  const [note, setNote] = useState('');
  const twin = error instanceof ApiError && error.status === 409 && (error.detail as { existing?: string })?.existing;

  async function add(force: boolean) {
    const body = { how, text, account, amount, description, date, category, spent_for: spentFor || null, note, force };
    if (await run(() => api.post('/api/expenses', body), { keepError: true })) router.back();
  }

  return (
    <Card>
      {how === 'message' ? <T variant="caption">{moneyIn ? 'Money in' : 'Money out'} · check the details, then add it.</T> : null}
      <AmountField label="Amount" value={amount} onChange={setAmount} placeholder="0" />
      <Field
        label={how === 'typed' ? 'What was it?' : moneyIn ? 'From' : 'Paid to'}
        value={description}
        onChangeText={setDescription}
        placeholder="e.g. Samosas, Petrol, Gas bill"
      />
      <DateField label="Date" value={date} onChange={setDate} />
      {how === 'typed' ? (
        <Select
          label="Paid with"
          value={account}
          options={options.accounts.map((a) => ({ key: a.key, label: a.name }))}
          onChange={(key) => setAccount(key ?? account)}
        />
      ) : null}
      <Select
        label="Category"
        value={category}
        allowNone="Let the app decide"
        options={options.categories.map((c) => ({ key: c, label: c }))}
        onChange={setCategory}
      />
      {!moneyIn ? (
        <View style={{ gap: 6 }}>
          <T variant="small" style={{ fontWeight: '600' }}>
            For
          </T>
          <Segmented
            options={[...options.labels.map((l) => ({ key: l, label: l })), { key: '', label: 'Rules decide' }]}
            value={spentFor}
            onChange={setSpentFor}
            scroll
          />
        </View>
      ) : null}
      <Field label="Note" value={note} onChangeText={setNote} placeholder='e.g. "Outing with Zain"' />
      {error ? (
        <Notice kind={twin ? 'warning' : 'error'} text={error.message}>
          {twin ? <Button label="Add it anyway" small onPress={() => void add(true)} /> : null}
        </Notice>
      ) : null}
      <Button
        label="Add"
        kind="primary"
        busy={busy}
        disabled={!amount || !description.trim()}
        onPress={() => {
          clearError();
          void add(false);
        }}
        wide
      />
    </Card>
  );
}
