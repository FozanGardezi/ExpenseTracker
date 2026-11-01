/** Activity → Delivery orders: Foodpanda, Careem, inDrive and Krave Mart, by service, by merchant, every order. */
import { useRouter } from 'expo-router';
import { useState } from 'react';
import { View } from 'react-native';

import { HBars, Legend, MonthBars } from '@/components/charts';
import { PeriodPicker, type Period } from '@/components/period';
import { Card, CardTitle, Chips, Details, Field, ListRow, Loaded, Notice, Select, Stats, T } from '@/components/ui';
import { useApi } from '@/lib/query';
import { space, useTheme } from '@/lib/theme';
import type { Orders } from '@/lib/types';

export function OrdersSection() {
  const { colors } = useTheme();
  const router = useRouter();
  const [period, setPeriod] = useState<Period>({});
  const [services, setServices] = useState<string[]>([]);
  const [currency, setCurrency] = useState<string | undefined>();
  const [typed, setTyped] = useState('');
  const [search, setSearch] = useState('');
  const orders = useApi<Orders>('/api/activity/orders', { ...period, services, currency, search });
  const serviceColor = (key: string) => colors.services[key as keyof typeof colors.services] ?? colors.neutral;

  return (
    <Loaded query={orders}>
      {(data) =>
        data.empty ? (
          <Notice text="Delivery orders appear here after a sync. You can also fetch your full foodpanda history under **Accounts → Import**." />
        ) : (
          <View style={{ gap: space.lg }}>
            <Chips
              options={(data.services ?? []).map((s) => ({ key: s.key, label: s.name }))}
              selected={services.length ? services : (data.chosen ?? [])}
              onChange={setServices}
            />
            <PeriodPicker periods={data.periods} value={period} shown={data} onChange={setPeriod} />
            {(data.currencies?.length ?? 0) > 1 ? (
              <Select
                label="Currency"
                value={data.currency ?? null}
                options={(data.currencies ?? []).map((c) => ({ key: c, label: c }))}
                onChange={(c) => setCurrency(c ?? undefined)}
              />
            ) : null}
            {data.nothing ? (
              <Notice text="No orders match these filters." />
            ) : (
              <>
                <Stats items={data.summary ?? []} />
                <Card>
                  <CardTitle title="Monthly spending" />
                  <MonthBars bars={data.chart ?? []} colorOf={serviceColor} />
                  <Legend items={(data.by_service ?? []).map((s) => ({ label: s.name, color: serviceColor(s.key) }))} />
                </Card>
                <Card>
                  <CardTitle title="By service" />
                  <HBars items={(data.by_service ?? []).map((s) => ({ key: s.key, label: s.name, value: s.value, amount: s.amount, color: serviceColor(s.key) }))} />
                </Card>
                <Card>
                  <CardTitle title="Top merchants" />
                  <Details rows={(data.top_merchants ?? []).map((m) => ({ label: `${m.merchant} (${m.service})`, value: `${m.spent} · ${m.orders} orders` }))} />
                </Card>
                <Card>
                  <CardTitle title="All orders" />
                  <Field
                    placeholder="Merchant or email subject"
                    accessibilityLabel="Search orders"
                    value={typed}
                    onChangeText={setTyped}
                    onSubmitEditing={() => setSearch(typed.trim())}
                    onBlur={() => setSearch(typed.trim())}
                    returnKeyType="search"
                  />
                  {(data.orders ?? []).map((o) => (
                    <ListRow
                      key={o.id}
                      title={o.title}
                      sub={o.sub}
                      amount={o.amount}
                      meta={o.meta}
                      moneyIn={o.money_in}
                      category={o.category}
                      color={serviceColor(o.service)}
                      onPress={() => router.push({ pathname: '/payment/[item]', params: { item: o.id } })}
                    />
                  ))}
                  {(data.orders_total ?? 0) > (data.orders?.length ?? 0) ? (
                    <T variant="caption">Showing the latest {data.orders?.length} of {data.orders_total}. Search to find older ones.</T>
                  ) : null}
                </Card>
              </>
            )}
          </View>
        )
      }
    </Loaded>
  );
}
