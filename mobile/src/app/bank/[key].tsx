/** One bank or wallet: how its emails are found, what the app searches for, and removing it. */
import { useLocalSearchParams, useNavigation, useRouter } from 'expo-router';
import { useEffect, useState } from 'react';

import { Button, Card, Code, Field, Loaded, Notice, Screen, Segmented, T, Toggle } from '@/components/ui';
import { api } from '@/lib/api';
import { confirm } from '@/lib/confirm';
import { useAction, useApi } from '@/lib/query';
import type { Institution, Institutions } from '@/lib/types';

export default function BankSheet() {
  const { key } = useLocalSearchParams<{ key: string }>();
  const institutions = useApi<Institutions>('/api/accounts/institutions');
  const navigation = useNavigation();
  const found = institutions.data?.tracked.find((i) => i.key === key);
  useEffect(() => {
    if (found) navigation.setOptions({ title: found.name });
  }, [found, navigation]);
  return (
    <Screen top={false}>
      <Loaded query={institutions}>
        {(data) => {
          const institution = data.tracked.find((i) => i.key === key);
          return institution ? <Editor institution={institution} kinds={data.kinds} /> : <Notice text="That bank or wallet isn't there any more." />;
        }}
      </Loaded>
    </Screen>
  );
}

function Editor({ institution, kinds }: { institution: Institution; kinds: Institutions['kinds'] }) {
  const router = useRouter();
  const { run, busy } = useAction();
  const [name, setName] = useState(institution.name);
  const [kind, setKind] = useState(institution.kind);
  const [senders, setSenders] = useState(institution.senders);
  const [subjects, setSubjects] = useState(institution.subjects);
  const [currency, setCurrency] = useState(institution.currency);
  const [enabled, setEnabled] = useState(institution.enabled);
  const path = `/api/accounts/institutions/${institution.key}`;

  async function remove() {
    const ok = await confirm(`Remove ${institution.name}?`, 'Everything read from its emails is removed too.', 'Remove');
    if (ok && (await run(() => api.delete(path)))) router.back();
  }

  return (
    <>
      <Card>
        <Toggle label="Read its emails" value={enabled} onChange={setEnabled} />
        <Field label="Name" value={name} onChangeText={setName} />
        <Segmented options={kinds} value={kind} onChange={setKind} />
        <Field label="Sender" value={senders} onChangeText={setSenders} autoCapitalize="none" hint="Separate several with commas." />
        <Field label="Only subjects containing (optional)" value={subjects} onChangeText={setSubjects} />
        <Field label="Currency" value={currency} onChangeText={setCurrency} autoCapitalize="characters" />
        <Button
          label="Save"
          kind="primary"
          busy={busy}
          onPress={async () => {
            if (await run(() => api.patch(path, { name, kind, senders, subjects, currency, enabled }))) router.back();
          }}
        />
      </Card>
      <Card>
        <T variant="heading">What the app searches for</T>
        <T variant="caption">Paste these into Gmail’s search box to see the emails it reads.</T>
        <T variant="strong">Alerts</T>
        <Code>{institution.alerts_query}</Code>
        {institution.statements_query ? (
          <>
            <T variant="strong">Statements</T>
            <Code>{institution.statements_query}</Code>
          </>
        ) : null}
      </Card>
      <Button label={`Remove ${institution.name}`} kind="danger" icon="delete" onPress={() => void remove()} />
    </>
  );
}
