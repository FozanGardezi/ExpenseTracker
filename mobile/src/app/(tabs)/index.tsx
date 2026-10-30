/**
 * Home: status, Add expense and syncing, the setup steps until they're done, then four
 * sub-tabs: Overview (one month), Trends, Places and Budget.
 */
import { useRouter } from 'expo-router';
import { View } from 'react-native';

import { Icon } from '@/components/icon';
import { Button, Card, Meter, Notice, Row, Screen, Segmented, T } from '@/components/ui';
import { useApi } from '@/lib/query';
import { useSubTab } from '@/lib/sub-tab';
import { useSync } from '@/lib/sync';
import { space, useTheme } from '@/lib/theme';
import type { HomeStatus } from '@/lib/types';
import { BudgetSection } from '@/sections/budget';
import { OverviewSection } from '@/sections/overview';
import { PlacesSection } from '@/sections/places';
import { TrendsSection } from '@/sections/trends';

const TABS = [
  { key: 'overview', label: 'Overview' },
  { key: 'trends', label: 'Trends' },
  { key: 'places', label: 'Places' },
  { key: 'budget', label: 'Budget' },
] as const;

export default function Home() {
  const router = useRouter();
  const status = useApi<HomeStatus>('/api/home/status');
  const sync = useSync();
  const [tab, setTab] = useSubTab(TABS.map((t) => t.key));
  const connected = status.data?.gmail_connected ?? false;

  return (
    <Screen onRefresh={() => void status.refetch()} refreshing={status.isRefetching}>
      <View style={{ gap: 4 }}>
        <T variant="title">{status.data ? `Hi, ${status.data.first_name}` : ' '}</T>
        <T variant="small" muted>
          {status.data?.status ?? ' '}
        </T>
      </View>
      <Row wrap>
        <Button label="Add expense" kind="primary" icon="add" onPress={() => router.push('/add-expense')} />
        <Button
          label="Sync now"
          icon="sync"
          disabled={!connected || sync.running}
          onPress={() => void sync.start({})}
        />
        <Button label="Sync options" icon="tune" onPress={() => router.push('/sync-options')} />
      </Row>
      <SyncProgress />
      {status.data?.steps.length ? <GetStarted status={status.data} /> : null}
      <Segmented options={[...TABS]} value={tab} onChange={setTab} />
      {tab === 'overview' && <OverviewSection />}
      {tab === 'trends' && <TrendsSection />}
      {tab === 'places' && <PlacesSection />}
      {tab === 'budget' && <BudgetSection />}
    </Screen>
  );
}

function SyncProgress() {
  const { job, running } = useSync();
  const { colors } = useTheme();
  if (!running || !job) return null;
  const share = job.total ? job.done / job.total : 0;
  return (
    <Card>
      <Row>
        <Icon name="sync" size={18} color={colors.accent} />
        <T variant="strong" style={{ flex: 1 }}>
          {job.total ? `${job.source}: reading email ${job.done} of ${job.total}` : `${job.source || 'Searching Gmail'}…`}
        </T>
      </Row>
      <Meter share={share} color={colors.accent} />
    </Card>
  );
}

function GetStarted({ status }: { status: HomeStatus }) {
  const router = useRouter();
  const sync = useSync();
  const open = (target: HomeStatus['steps'][number]['target']) => {
    if (target === 'settings') router.push('/settings');
    else if (target === 'accounts') router.push('/accounts');
    else void sync.start({});
  };
  return (
    <Card>
      <T variant="heading">Get started</T>
      <T muted>
        Your spending, built automatically from the receipts, alerts and monthly statements in your Gmail. Add anything
        they miss, like cash, with Add expense.
      </T>
      <View style={{ gap: space.xs }}>
        {status.steps.map((step) => (
          <Button
            key={step.label}
            label={step.label}
            kind="ghost"
            icon={step.done ? 'check_circle' : 'radio_button_unchecked'}
            disabled={step.done || (step.target === 'sync' && !status.gmail_connected)}
            onPress={() => open(step.target)}
          />
        ))}
      </View>
      <Notice text="inDrive and Careem only email a receipt when your profile in their app has an email address, and many banks need email alerts turned on in their app." />
    </Card>
  );
}
