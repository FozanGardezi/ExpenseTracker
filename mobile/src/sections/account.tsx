/** Settings → Gmail & account: who's signed in, the Gmail permission, the look, and deleting data. */
import { useState } from 'react';
import { View } from 'react-native';

import { Markdown } from '@/components/markdown';
import { useToast } from '@/components/toast';
import { Button, Card, CardTitle, Code, Expandable, Loaded, Notice, Row, Segmented, T, Toggle } from '@/components/ui';
import { api } from '@/lib/api';
import { confirm } from '@/lib/confirm';
import { useAction, useApi } from '@/lib/query';
import { useSession } from '@/lib/session';
import { space, useTheme, type ThemeChoice } from '@/lib/theme';
import type { Account } from '@/lib/types';

export function AccountSection() {
  const account = useApi<Account>('/api/settings/account');
  const { signOut } = useSession();
  const theme = useTheme();
  return (
    <Loaded query={account}>
      {(data) => (
        <View style={{ gap: space.lg }}>
          <Card>
            <Row>
              <View style={{ flex: 1 }}>
                <T variant="strong">{data.user.name}</T>
                <T variant="small" muted>
                  {data.user.email}
                </T>
              </View>
              <Button label="Sign out" icon="logout" small onPress={() => void signOut()} />
            </Row>
          </Card>
          <Gmail data={data} />
          <Card>
            <CardTitle title="Appearance" />
            <Segmented
              options={[
                { key: 'system', label: 'Like my phone' },
                { key: 'light', label: 'Light' },
                { key: 'dark', label: 'Dark' },
              ]}
              value={theme.choice}
              onChange={(c: ThemeChoice) => theme.setChoice(c)}
            />
          </Card>
          <DeleteData />
        </View>
      )}
    </Loaded>
  );
}

function Gmail({ data }: { data: Account }) {
  const { signIn } = useSession();
  const toast = useToast();
  const { run, busy } = useAction();
  const [agree, setAgree] = useState(false);
  const [asking, setAsking] = useState(false);

  async function allow() {
    setAsking(true);
    const result = await signIn({ gmail: true });
    setAsking(false);
    if (!result.ok) {
      if (result.message) toast.show(result.message, 'error');
    } else if (result.gmail === 'allowed') {
      toast.show('Gmail connected. Use Sync now on Home to read your emails.');
    } else {
      toast.show("Gmail access wasn't allowed: keep its box ticked on Google's screen.", 'error');
    }
  }

  async function disconnect() {
    if (await confirm('Disconnect Gmail?', "The app stops reading your email, and its access is withdrawn at Google. What it has read so far stays.", 'Disconnect')) {
      await run(() => api.delete('/api/settings/gmail'));
    }
  }

  return (
    <Card>
      <CardTitle title="Gmail" />
      {data.gmail.connected ? (
        <>
          <Notice kind="success" text={`Connected to **${data.gmail.account}**, read-only${data.gmail.since ? ` since ${data.gmail.since}` : ''}.`} />
          <T variant="small" muted>
            Reads emails from: {data.reads_from.join(', ')}.
          </T>
          <Button label="Disconnect Gmail" kind="danger" busy={busy} onPress={() => void disconnect()} />
        </>
      ) : (
        <>
          <T>To track your spending, the app needs to read the receipts, alerts and statements in your Gmail.</T>
          <Markdown text={data.consent} />
          {data.configured ? (
            <>
              <Toggle label="I've read this and allow the app read-only access to my Gmail" value={agree} onChange={setAgree} />
              <Button label="Allow Gmail access" kind="primary" icon="mail" disabled={!agree} busy={asking} onPress={() => void allow()} />
              <T variant="caption">Google opens and asks you to confirm for {data.user.email}; keep the Gmail box ticked.</T>
            </>
          ) : (
            <Notice kind="warning" text="Gmail access isn't configured on the server yet (see the README)." />
          )}
        </>
      )}
      <Expandable title="Exactly what the app searches for">
        <T variant="caption">Paste any of these into Gmail’s search box to see the emails it matches.</T>
        {data.queries.map((q) => (
          <View key={q.name} style={{ gap: 4 }}>
            <T variant="strong">{q.name}</T>
            <Code>{q.query}</Code>
          </View>
        ))}
      </Expandable>
    </Card>
  );
}

function DeleteData() {
  const [sure, setSure] = useState(false);
  const { run, busy } = useAction();
  return (
    <Card>
      <Expandable title="Delete my data" icon="delete">
        <T>
          Removes everything the app stores for you, including the Gmail permission, which is also withdrawn at Google. This
          can’t be undone. You stay signed in.
        </T>
        <Toggle label="Yes, delete all my data" value={sure} onChange={setSure} />
        <Button
          label="Delete my data"
          kind="danger"
          busy={busy}
          disabled={!sure}
          onPress={async () => {
            if (await run(() => api.delete('/api/settings/data'))) setSure(false);
          }}
        />
      </Expandable>
    </Card>
  );
}
