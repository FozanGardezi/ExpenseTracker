/** Accounts → Statement settings: per bank, statements on or off, the PDF password and sender; what was read. */
import { useState } from 'react';
import { View } from 'react-native';

import { Button, Card, CardTitle, Code, Details, Expandable, Field, Loaded, Notice, T, Toggle } from '@/components/ui';
import { api } from '@/lib/api';
import { useAction, useApi } from '@/lib/query';
import { space } from '@/lib/theme';
import type { StatementSettings } from '@/lib/types';

export function StatementSettingsSection() {
  const page = useApi<StatementSettings>('/api/accounts/statements');
  return (
    <Loaded query={page}>
      {(data) =>
        data.empty ? (
          <Notice text="Add your banks and wallets under **Banks & wallets** first." />
        ) : (
          <View style={{ gap: space.lg }}>
            {data.unread.length ? (
              <Card>
                <CardTitle title="Couldn't read" />
                {data.unread.map((u, i) => (
                  <Notice key={i} kind="warning" text={`**${u.bank}**, ${u.received}: ${u.subject}. ${u.reason}`} />
                ))}
              </Card>
            ) : null}
            <Card>
              <CardTitle title="Settings" />
              {data.settings.map((s) => (
                <Expandable key={s.key} title={s.name + (s.statements ? '' : ' (off)')}>
                  <BankStatements setting={s} />
                </Expandable>
              ))}
            </Card>
            <Card>
              <CardTitle title="Statements read" />
              {data.read.length ? (
                data.read.map((r, i) => (
                  <Details
                    key={i}
                    rows={[{ label: `${r.bank} · ${r.period}`, value: `${r.found} transactions, ${r.added} new · received ${r.received}` }]}
                  />
                ))
              ) : (
                <T muted>None yet. Statements are read with each sync; for older months use Sync options on Home.</T>
              )}
            </Card>
          </View>
        )
      }
    </Loaded>
  );
}

function BankStatements({ setting }: { setting: StatementSettings['settings'][number] }) {
  const { run, busy } = useAction();
  const [on, setOn] = useState(setting.statements);
  const [password, setPassword] = useState('');
  const [removePassword, setRemovePassword] = useState(false);
  const [senders, setSenders] = useState(setting.senders);
  const [subjects, setSubjects] = useState(setting.subjects);
  return (
    <View style={{ gap: space.md }}>
      <Toggle label="Read monthly statements" value={on} onChange={setOn} />
      <Field
        label="Statement password"
        value={password}
        onChangeText={setPassword}
        secureTextEntry
        autoCapitalize="none"
        placeholder={setting.has_password ? 'Saved. Leave empty to keep it.' : 'Only if the PDF asks for one'}
        hint="Banks often lock e-statements with a password, for example made from your CNIC number or date of birth. It's stored encrypted and only used to open this bank's statements."
      />
      {setting.has_password ? <Toggle label="Remove the saved password" value={removePassword} onChange={setRemovePassword} /> : null}
      <Field
        label="Statements come from (optional)"
        value={senders}
        onChangeText={setSenders}
        autoCapitalize="none"
        placeholder={setting.senders_placeholder}
        hint="Only needed when statements come from a different address than the alerts."
      />
      <Field label="Statement subjects contain (optional)" value={subjects} onChangeText={setSubjects} placeholder="statement" />
      <Button
        label="Save"
        busy={busy}
        onPress={async () => {
          const body = { statements: on, password, remove_password: removePassword, senders, subjects };
          if (await run(() => api.put(`/api/accounts/institutions/${setting.key}/statements`, body))) setPassword('');
        }}
      />
      <T variant="caption">Searches Gmail for:</T>
      <Code>{setting.query}</Code>
    </View>
  );
}
