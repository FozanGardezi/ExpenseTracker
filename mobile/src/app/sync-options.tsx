/** Which sources to sync and how far back, re-reading them from scratch, and reading older statements. */
import { useRouter } from 'expo-router';
import { useState } from 'react';

import { Button, Card, Chips, Loaded, Notice, Screen, Segmented, Select, T } from '@/components/ui';
import { confirm } from '@/lib/confirm';
import { MONTH_NAMES } from '@/lib/format';
import { useApi } from '@/lib/query';
import { useSync } from '@/lib/sync';
import type { HomeStatus, SyncOptions } from '@/lib/types';

const DAYS = (d: number) => (d % 365 === 0 ? `${d / 365} ${d === 365 ? 'year' : 'years'}` : `${d} days`);

export default function SyncOptionsSheet() {
  const options = useApi<SyncOptions>('/api/sync/options');
  const status = useApi<HomeStatus>('/api/home/status');
  return (
    <Screen top={false}>
      <Loaded query={options}>{(data) => <Form data={data} connected={status.data?.gmail_connected ?? false} />}</Loaded>
    </Screen>
  );
}

function Form({ data, connected }: { data: SyncOptions; connected: boolean }) {
  const router = useRouter();
  const sync = useSync();
  const [sources, setSources] = useState(data.sources.map((s) => s.key));
  const [days, setDays] = useState(data.default_days);
  const [banks, setBanks] = useState(data.statement_sources.map((s) => s.key));
  const [year, setYear] = useState(data.years[0]);
  const [months, setMonths] = useState<number[]>([]);

  async function go(body: object, path?: string) {
    const result = await sync.start(body, path);
    if (result?.started) router.back();
  }

  async function rescan() {
    const ok = await confirm(
      'Re-scan these sources?',
      "Their emails are read again from scratch. Imports and your category changes are kept.",
      'Re-scan',
    );
    if (ok) await go({ sources, days, rescan: true });
  }

  return (
    <>
      {!connected ? <Notice kind="warning" text="Gmail isn't connected. Allow it under **Settings → Gmail & account** first." /> : null}
      {sync.running ? <Notice text="A sync is running. You can start another once it's done." /> : null}
      <Card>
        <T variant="heading">Sources</T>
        <Chips options={data.sources.map((s) => ({ key: s.key, label: s.name }))} selected={sources} onChange={setSources} />
        <T variant="heading">Look back</T>
        <Segmented options={data.lookback.map((d) => ({ key: d, label: DAYS(d) }))} value={days} onChange={setDays} scroll />
        <T variant="caption">The app also syncs by itself when you open it, if the last sync was more than 6 hours ago.</T>
        <Button label="Sync these" kind="primary" icon="sync" disabled={!connected || !sources.length || sync.running} onPress={() => void go({ sources, days })} />
        <Button label="Re-scan selected sources" disabled={!connected || !sources.length || sync.running} onPress={() => void rescan()} />
      </Card>
      <Card>
        <T variant="heading">Read older statements</T>
        {data.statement_sources.length ? (
          <>
            <Chips options={data.statement_sources.map((s) => ({ key: s.key, label: s.name }))} selected={banks} onChange={setBanks} />
            <Select label="Year" value={year} options={data.years.map((y) => ({ key: y, label: String(y) }))} onChange={(y) => setYear(y ?? year)} />
            <T variant="small" style={{ fontWeight: '600' }}>
              Months (none picked: the whole year)
            </T>
            <Chips options={MONTH_NAMES.map((name, i) => ({ key: i + 1, label: name.slice(0, 3) }))} selected={months} onChange={setMonths} />
            <Button
              label="Read these statements"
              disabled={!connected || !banks.length || sync.running}
              onPress={() => void go({ sources: banks, year, months }, '/api/sync/older')}
            />
          </>
        ) : (
          <T muted>Turn on statements for a bank under Accounts → Statement settings.</T>
        )}
      </Card>
    </>
  );
}
