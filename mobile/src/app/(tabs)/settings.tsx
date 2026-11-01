/** Settings: account and Gmail access, categories and rules, skipped emails, and privacy. */
import { Card, Loaded, Screen, Segmented } from '@/components/ui';
import { Markdown } from '@/components/markdown';
import { useApi } from '@/lib/query';
import { useSubTab } from '@/lib/sub-tab';
import { AccountSection } from '@/sections/account';
import { RulesSection } from '@/sections/rules';
import { SkippedSection } from '@/sections/skipped';

const TABS = [
  { key: 'account', label: 'Gmail & account' },
  { key: 'categories', label: 'Categories' },
  { key: 'skipped', label: 'Skipped emails' },
  { key: 'privacy', label: 'Privacy' },
] as const;

export default function Settings() {
  const [tab, setTab] = useSubTab(TABS.map((t) => t.key));
  return (
    <Screen>
      <Segmented options={[...TABS]} value={tab} onChange={setTab} scroll />
      {tab === 'account' && <AccountSection />}
      {tab === 'categories' && <RulesSection />}
      {tab === 'skipped' && <SkippedSection />}
      {tab === 'privacy' && <PrivacySection />}
    </Screen>
  );
}

function PrivacySection() {
  const privacy = useApi<{ markdown: string }>('/api/privacy');
  return (
    <Loaded query={privacy}>
      {(data) => (
        <Card>
          <Markdown text={data.markdown} />
        </Card>
      )}
    </Loaded>
  );
}
