/** Home → Trends: past months side by side against the budget, and how each category moves. */
import { useRouter } from 'expo-router';
import { useState } from 'react';
import { View } from 'react-native';

import { Legend, MonthBars, Sparkbars } from '@/components/charts';
import { Card, CardTitle, Details, Expandable, ListRow, Loaded, Notice, Row, Segmented, Select, Stats, T } from '@/components/ui';
import { useApi } from '@/lib/query';
import { slotColor, space, useTheme } from '@/lib/theme';
import type { Trends } from '@/lib/types';

type Filters = { range: string; spent_for: string; currency?: string };

export function TrendsSection() {
  const [filters, setFilters] = useState<Filters>({ range: '12', spent_for: 'All' });
  const trends = useApi<Trends>('/api/home/trends', filters);
  return (
    <Loaded query={trends}>
      {(data) => (
        <View style={{ gap: space.lg }}>
          <Segmented options={data.ranges} value={data.range} onChange={(range) => setFilters({ ...filters, range })} />
          <Row>
            <View style={{ flex: 1 }}>
              <Segmented
                options={['All', ...data.labels].map((l) => ({ key: l, label: l }))}
                value={data.for}
                onChange={(spentFor) => setFilters({ ...filters, spent_for: spentFor })}
              />
            </View>
            {data.currencies.length > 1 ? (
              <View style={{ width: 110 }}>
                <Select
                  value={data.currency}
                  options={data.currencies.map((c) => ({ key: c, label: c }))}
                  onChange={(currency) => setFilters({ ...filters, currency: currency ?? undefined })}
                />
              </View>
            ) : null}
          </Row>
          {data.empty ? <Notice text="Your months appear here after the first sync." /> : <Body data={data} />}
        </View>
      )}
    </Loaded>
  );
}

function Body({ data }: { data: Trends }) {
  const { colors } = useTheme();
  const router = useRouter();
  const color = (group: string) => slotColor(colors, data.slots, group);
  const scope = { spent_for: data.for, currency: data.currency };
  return (
    <>
      <Stats items={data.stats ?? []} />
      <Card>
        <CardTitle title="Each month" />
        <MonthBars
          bars={data.chart ?? []}
          colorOf={color}
          onPress={(month, group) =>
            router.push({ pathname: '/drill', params: { kind: 'trend', key: group ? `${month}|${group}` : month, ...scope } })
          }
        />
        <Legend
          items={[
            ...(data.groups ?? []).map((g) => ({
              label: g === 'Everything else' && data.rest?.length ? `Everything else (${data.rest.join(', ')})` : g,
              color: color(g),
            })),
            ...(data.chart?.some((b) => b.budget) ? [{ label: 'Budget (dashed)', color: colors.text }] : []),
          ]}
        />
        <T variant="caption">Tap part of a month to see its payments.</T>
      </Card>
      <Card>
        <CardTitle title="Categories over time" />
        <T variant="caption">This month so far against a usual month (the average of up to three months before).</T>
        {(data.categories ?? []).map((c) => (
          <ListRow
            key={c.category}
            title={c.category}
            sub={`Usual ${c.usual} · ${c.change === 'new' ? 'new' : `${c.change} vs usual`}`}
            category={c.category}
            color={color(c.category)}
            amount={c.now}
            right={<Sparkbars values={c.trend} color={color(c.category)} />}
          />
        ))}
      </Card>
      <Card>
        <Expandable title="Month by month" icon="list">
          {(data.months_table ?? []).map((m) => (
            <View key={m.month} style={{ gap: 4 }}>
              <T variant="strong">{m.month}</T>
              <Details
                rows={[
                  { label: 'Spent', value: m.spent },
                  { label: 'Budget', value: m.budget },
                  { label: 'Left (over if negative)', value: m.left },
                  { label: 'Came in', value: m.received },
                ]}
              />
            </View>
          ))}
          <T variant="caption">Amounts in {data.currency}.</T>
        </Expandable>
      </Card>
    </>
  );
}
