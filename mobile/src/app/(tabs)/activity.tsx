/** Activity: every transaction, monthly statements, transfers, and delivery orders. */
import { Screen, Segmented } from '@/components/ui';
import { useSubTab } from '@/lib/sub-tab';
import { OrdersSection } from '@/sections/orders';
import { StatementsSection } from '@/sections/statements';
import { TransactionsSection } from '@/sections/transactions';
import { TransfersSection } from '@/sections/transfers';

const TABS = [
  { key: 'transactions', label: 'Transactions' },
  { key: 'statements', label: 'Statements' },
  { key: 'transfers', label: 'Transfers' },
  { key: 'orders', label: 'Delivery orders' },
] as const;

export default function Activity() {
  const [tab, setTab] = useSubTab(TABS.map((t) => t.key));
  return (
    <Screen>
      <Segmented options={[...TABS]} value={tab} onChange={setTab} scroll />
      {tab === 'transactions' && <TransactionsSection />}
      {tab === 'statements' && <StatementsSection />}
      {tab === 'transfers' && <TransfersSection />}
      {tab === 'orders' && <OrdersSection />}
    </Screen>
  );
}
