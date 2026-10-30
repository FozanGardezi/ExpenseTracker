/** Activity → Statements: spending for each month from your monthly statements, and each month's transactions. */
import { useState } from 'react';
import { View } from 'react-native';

import { HBars, Legend, MonthBars } from '@/components/charts';
import { PaymentList } from '@/components/payment-list';
import { Card, CardTitle, Details, Expandable, Loaded, Notice, Row, Select, Stats, T } from '@/components/ui';
import { useApi } from '@/lib/query';
import { slotColor, space, useTheme } from '@/lib/theme';
import type { Statements } from '@/lib/types';

export function StatementsSection() {
  const { colors } = useTheme();
  const [filters, setFilters] = useState<{ bank?: string; currency?: string; month?: string }>({});
  const statements = useApi<Statements>('/api/activity/statements', filters);
  return (
    <Loaded query={statements}>
      {(data) => {
        if (data.empty) {
          return (
            <Notice text="Monthly statements appear here once they've been read. If your bank locks them with a password, add it under **Accounts → Statement settings**." />
          );
        }
        const color = (group: string) => slotColor(colors, data.slots, group);
        const groups = [...new Set(data.chart.flatMap((b) => b.segments.map((s) => s.group)))];
        return (
          <View style={{ gap: space.lg }}>
            {data.banks.length > 2 || data.currencies.length > 1 ? (
              <Row>
                {data.banks.length > 2 ? (
                  <View style={{ flex: 1 }}>
                    <Select
                      value={data.bank}
                      options={data.banks.map((b) => ({ key: b.key, label: b.name }))}
                      onChange={(bank) => setFilters({ ...filters, bank: bank ?? undefined, month: undefined })}
                    />
                  </View>
                ) : null}
                {data.currencies.length > 1 ? (
                  <View style={{ width: 110 }}>
                    <Select
                      value={data.currency}
                      options={data.currencies.map((c) => ({ key: c, label: c }))}
                      onChange={(currency) => setFilters({ ...filters, currency: currency ?? undefined, month: undefined })}
                    />
                  </View>
                ) : null}
              </Row>
            ) : null}
            <Card>
              <CardTitle title="Spending each month" />
              <MonthBars bars={data.chart} colorOf={color} selected={data.month} onPress={(month) => setFilters({ ...filters, month })} />
              <Legend items={groups.map((g) => ({ label: g, color: color(g) }))} />
              <T variant="caption">Tap a month to see what it went on.</T>
              <Expandable title="Month by month" icon="list">
                {data.months_table.map((m) => (
                  <View key={m.month} style={{ gap: 4 }}>
                    <T variant="strong">{m.month}</T>
                    <Details
                      rows={[
                        { label: 'Spent', value: m.spent },
                        { label: 'Received', value: m.received },
                        { label: 'Net', value: m.net },
                        { label: 'Transactions', value: String(m.count) },
                      ]}
                    />
                  </View>
                ))}
              </Expandable>
            </Card>
            <Select label="Month" value={data.month} options={data.months} onChange={(month) => setFilters({ ...filters, month: month ?? undefined })} />
            <Stats items={data.summary} />
            {data.by_category.length ? (
              <Card>
                <CardTitle title={`${data.month_label} by category`} />
                <HBars items={data.by_category.map((c) => ({ key: c.category, label: c.category, value: c.value, amount: c.amount, color: color(c.group) }))} />
              </Card>
            ) : null}
            <Card>
              <CardTitle title={`${data.month_label} transactions`} />
              <T variant="caption">Tap one to change its category, who it was for, or add a note.</T>
              <PaymentList rows={data.rows} slots={data.slots} byDay={false} />
            </Card>
          </View>
        );
      }}
    </Loaded>
  );
}
