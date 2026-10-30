/** Accounts: the banks and wallets to read, their statement settings, and importing history. */
import { Screen, Segmented } from '@/components/ui';
import { useSubTab } from '@/lib/sub-tab';
import { BanksSection } from '@/sections/banks';
import { ImportSection } from '@/sections/imports';
import { StatementSettingsSection } from '@/sections/statement-settings';

const TABS = [
  { key: 'banks', label: 'Banks & wallets' },
  { key: 'statements', label: 'Statement settings' },
  { key: 'import', label: 'Import' },
] as const;

export default function Accounts() {
  const [tab, setTab] = useSubTab(TABS.map((t) => t.key));
  return (
    <Screen>
      <Segmented options={[...TABS]} value={tab} onChange={setTab} scroll />
      {tab === 'banks' && <BanksSection />}
      {tab === 'statements' && <StatementSettingsSection />}
      {tab === 'import' && <ImportSection />}
    </Screen>
  );
}
