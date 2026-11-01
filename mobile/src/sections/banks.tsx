/** Accounts → Banks & wallets: which ones to read, and how their emails are found. */
import { useRouter } from 'expo-router';
import { useState } from 'react';
import { Switch, View } from 'react-native';

import { Button, Card, CardTitle, Expandable, Field, ListRow, Loaded, Notice, Segmented, Select, T } from '@/components/ui';
import { api } from '@/lib/api';
import { useAction, useApi } from '@/lib/query';
import { space, useTheme } from '@/lib/theme';
import type { Institutions } from '@/lib/types';

export function BanksSection() {
  const { colors } = useTheme();
  const router = useRouter();
  const institutions = useApi<Institutions>('/api/accounts/institutions');
  const { run } = useAction();
  return (
    <Loaded query={institutions}>
      {(data) => (
        <View style={{ gap: space.lg }}>
          {data.tracked.length ? (
            <Card>
              <CardTitle title="Your banks and wallets" />
              <T variant="caption">Tap one to change how its emails are found, or to remove it. Switch one off to pause it.</T>
              {data.tracked.map((i) => (
                <ListRow
                  key={i.key}
                  title={i.name}
                  sub={`${i.kind_label} · ${i.senders}${i.subjects ? ` · subjects with ${i.subjects}` : ''}`}
                  icon="account_balance"
                  color={i.enabled ? colors.accent : colors.neutral}
                  onPress={() => router.push({ pathname: '/bank/[key]', params: { key: i.key } })}
                  right={
                    <Switch
                      accessibilityLabel={`Read ${i.name}`}
                      value={i.enabled}
                      trackColor={{ true: colors.accent, false: colors.border }}
                      onValueChange={(enabled) => void run(() => api.patch(`/api/accounts/institutions/${i.key}`, { enabled }))}
                    />
                  }
                />
              ))}
            </Card>
          ) : (
            <Notice text="Many banks send alerts by SMS only; turn on email alerts in their app so there's something to read." />
          )}
          <AddPreset data={data} />
          <AddOwn data={data} />
        </View>
      )}
    </Loaded>
  );
}

function AddPreset({ data }: { data: Institutions }) {
  const [choice, setChoice] = useState<string | null>(null);
  const { run, busy } = useAction();
  if (!data.presets.length) return null;
  return (
    <Card>
      <CardTitle title="Add a bank or wallet" />
      <Select
        label="Common banks and wallets"
        value={choice}
        placeholder="Pick one"
        options={data.presets.map((p) => ({ key: p.key, label: `${p.name} (${p.kind_label.toLowerCase()})` }))}
        onChange={setChoice}
      />
      <Button
        label="Add"
        kind="primary"
        busy={busy}
        disabled={!choice}
        onPress={async () => {
          if (await run(() => api.post('/api/accounts/institutions', { preset: choice }))) setChoice(null);
        }}
      />
    </Card>
  );
}

function AddOwn({ data }: { data: Institutions }) {
  const [name, setName] = useState('');
  const [kind, setKind] = useState('bank');
  const [senders, setSenders] = useState('');
  const [subjects, setSubjects] = useState('');
  const [currency, setCurrency] = useState('PKR');
  const { run, busy } = useAction();
  return (
    <Card>
      <Expandable title="Not in the list? Add your own">
        <Field label="Name" value={name} onChangeText={setName} placeholder="e.g. Silkbank" />
        <Segmented options={data.kinds} value={kind} onChange={setKind} />
        <Field
          label="Sender"
          value={senders}
          onChangeText={setSenders}
          autoCapitalize="none"
          placeholder="alerts@silkbank.com.pk, silkbank"
          hint="Copy the sender from one of its alert emails. A full address, a domain or a word from the sender's name all work. Separate several with commas."
        />
        <Field
          label="Only subjects containing (optional)"
          value={subjects}
          onChangeText={setSubjects}
          placeholder="Transaction Alert"
          hint="Use this when the sender also emails you promotions."
        />
        <Field label="Currency" value={currency} onChangeText={setCurrency} autoCapitalize="characters" hint="Used when an alert shows an amount without a currency." />
        <Button
          label="Add"
          busy={busy}
          disabled={!name.trim() || !senders.trim()}
          onPress={async () => {
            if (await run(() => api.post('/api/accounts/institutions', { name, kind, senders, subjects, currency }))) {
              setName('');
              setSenders('');
              setSubjects('');
            }
          }}
        />
      </Expandable>
    </Card>
  );
}
