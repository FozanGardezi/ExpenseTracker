/** Activity → Transactions: everything, as a list by day. Tap one to see it, change it, or add a note. */
import { useInfiniteQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { View } from 'react-native';

import { PeriodPicker, type Period } from '@/components/period';
import { PaymentList } from '@/components/payment-list';
import { Button, Card, Chips, Field, Loaded, Notice, Row, T, Toggle } from '@/components/ui';
import { api, messageOf } from '@/lib/api';
import { shareCsv } from '@/lib/export';
import { space } from '@/lib/theme';
import { useToast } from '@/components/toast';
import type { Transactions } from '@/lib/types';

const PAGE = 60;

export function TransactionsSection() {
  const toast = useToast();
  const [typed, setTyped] = useState('');
  const [search, setSearch] = useState('');
  const [period, setPeriod] = useState<Period>({});
  const [categories, setCategories] = useState<string[]>([]);
  const [sources, setSources] = useState<string[]>([]);
  const [transfers, setTransfers] = useState(false);
  const [showFilters, setShowFilters] = useState(false);
  const [exporting, setExporting] = useState(false);
  const query = { ...period, search, categories, sources, transfers };
  const pages = useInfiniteQuery({
    queryKey: ['/api/activity/transactions', query],
    queryFn: ({ pageParam }) => api.get<Transactions>('/api/activity/transactions', { ...query, offset: pageParam, limit: PAGE }),
    initialPageParam: 0,
    getNextPageParam: (last) => ((last.offset ?? 0) + last.rows.length < last.total ? (last.offset ?? 0) + last.rows.length : undefined),
  });
  const first = pages.data?.pages[0];
  const rows = pages.data?.pages.flatMap((p) => p.rows) ?? [];
  const filtered = categories.length + sources.length + (transfers ? 1 : 0) + (period.period ? 1 : 0);

  async function exportCsv() {
    setExporting(true);
    try {
      await shareCsv('transactions.csv', await api.text('/api/activity/transactions.csv', query));
    } catch (e) {
      toast.show(messageOf(e), 'error');
    } finally {
      setExporting(false);
    }
  }

  return (
    <Loaded query={{ data: first, isLoading: pages.isLoading, error: pages.error, refetch: pages.refetch }}>
      {(data) =>
        data.empty ? (
          <Notice text="Transactions appear here after the first sync." />
        ) : (
          <View style={{ gap: space.lg }}>
            <Row>
              <View style={{ flex: 1 }}>
                <Field
                  placeholder="Merchant, payee, note or email subject"
                  accessibilityLabel="Search"
                  value={typed}
                  onChangeText={setTyped}
                  onSubmitEditing={() => setSearch(typed.trim())}
                  onBlur={() => setSearch(typed.trim())}
                  returnKeyType="search"
                />
              </View>
              <Button label={filtered ? `Filters (${filtered})` : 'Filters'} icon="filter_list" onPress={() => setShowFilters(!showFilters)} />
            </Row>
            {showFilters ? (
              <Card>
                <PeriodPicker periods={data.periods} value={period} shown={data} onChange={setPeriod} />
                <T variant="small" style={{ fontWeight: '600' }}>
                  Categories
                </T>
                <Chips options={(data.options?.categories ?? []).map((c) => ({ key: c, label: c }))} selected={categories} onChange={setCategories} />
                <T variant="small" style={{ fontWeight: '600' }}>
                  Sources
                </T>
                <Chips options={(data.options?.sources ?? []).map((s) => ({ key: s, label: s }))} selected={sources} onChange={setSources} />
                <Toggle label="Transfers between my accounts" value={transfers} onChange={setTransfers} />
              </Card>
            ) : null}
            <T variant="caption">{data.caption}</T>
            <Card>
              <PaymentList rows={rows} slots={data.slots} empty="Nothing matches." />
              {pages.hasNextPage ? (
                <Button label="Show more" busy={pages.isFetchingNextPage} onPress={() => void pages.fetchNextPage()} />
              ) : null}
            </Card>
            <Button label="Export CSV" icon="ios_share" busy={exporting} onPress={() => void exportCsv()} />
          </View>
        )
      }
    </Loaded>
  );
}
