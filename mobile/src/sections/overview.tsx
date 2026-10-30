/**
 * Home → Overview: one month at a glance, like a budgeting app's home screen. How much has
 * gone out and per day, the month against the budget and its limits, where it went, what to
 * keep an eye on, and the latest payments. Tapping a figure lists the payments behind it.
 */
import { useRouter } from 'expo-router';
import { useState } from 'react';
import { View } from 'react-native';

import { Donut } from '@/components/charts';
import { PaymentList } from '@/components/payment-list';
import {
  AmountField, Badge, Button, Card, CardTitle, Expandable, ListRow, Loaded, Meter, Notice, RichText, Row, Segmented, Select, T,
} from '@/components/ui';
import { api } from '@/lib/api';
import { useAction, useApi } from '@/lib/query';
import { slotColor, space, useTheme, type Palette } from '@/lib/theme';
import type { Overview } from '@/lib/types';

type Filters = { month?: string; spent_for: string; currency?: string };

export function OverviewSection() {
  const [filters, setFilters] = useState<Filters>({ spent_for: 'All' });
  const overview = useApi<Overview>('/api/home/overview', filters);
  return (
    <Loaded query={overview}>
      {(data) =>
        data.empty ? (
          <Notice text="Your spending appears here after the first sync. You can also add an expense yourself." />
        ) : (
          <Month data={data} filters={filters} setFilters={setFilters} />
        )
      }
    </Loaded>
  );
}

function statusColor(colors: Palette, status: string): string {
  return status === 'over' ? colors.critical : status === 'heading over' ? colors.warning : colors.accent;
}

function Month({ data, filters, setFilters }: { data: Overview; filters: Filters; setFilters: (f: Filters) => void }) {
  const { colors } = useTheme();
  const router = useRouter();
  const scope = { month: data.month, spent_for: data.for, currency: data.currency };
  const drill = (kind: string, key: string) => router.push({ pathname: '/drill', params: { kind, key, ...scope } });
  const color = (category: string) => slotColor(colors, data.slots, category);
  const hero = data.hero!;
  const where = data.where!;

  return (
    <View style={{ gap: space.lg }}>
      <View style={{ gap: space.sm }}>
        <Row>
          <View style={{ flex: 1 }}>
            <Select
              value={data.month}
              options={data.months.map((m) => ({ key: m.key, label: m.label }))}
              onChange={(month) => setFilters({ ...filters, month: month ?? undefined })}
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
        <Segmented
          options={['All', ...data.labels].map((l) => ({ key: l, label: l }))}
          value={data.for}
          onChange={(spentFor) => setFilters({ ...filters, spent_for: spentFor })}
        />
      </View>

      <Card>
        <T muted>{hero.label}</T>
        <T variant="hero" numberOfLines={1} style={{ fontVariant: ['tabular-nums'] }}>
          {hero.value}
        </T>
        <RichText text={hero.sub} />
        {hero.notes.map((note) => (
          <T key={note} variant="small" muted>
            {note}
          </T>
        ))}
        {hero.not_counted ? (
          <View style={{ gap: 2 }}>
            <T variant="small" muted>
              {hero.not_counted}
            </T>
            <View style={{ alignSelf: 'flex-start' }}>
              <Button label="Review transfers" kind="ghost" small icon="swap_horiz" onPress={() => router.push('/activity?tab=transfers')} />
            </View>
          </View>
        ) : null}
      </Card>

      {data.budget ? <BudgetCard budget={data.budget} /> : null}

      {data.limits?.length ? (
        <Card>
          <CardTitle title="Limits" />
          {data.limits.map((limit) => (
            <ListRow
              key={limit.position}
              title={limit.title}
              sub={limit.sub}
              amount={limit.amount}
              meta={limit.meta}
              category={limit.category}
              color={color(limit.category)}
              share={limit.share}
              shareColor={statusColor(colors, limit.status)}
              onPress={() => drill('limit', String(limit.position))}
            />
          ))}
        </Card>
      ) : null}

      <Card>
        <CardTitle
          title="Where it went"
          right={where.count ? <Badge label={`${where.count} ${where.count === 1 ? 'category' : 'categories'}`} color={colors.muted} /> : null}
        />
        {where.count ? (
          <>
            <Donut
              segments={where.donut.map((d) => ({ key: d.group, value: d.value, color: color(d.group) }))}
              label={where.top}
              value={where.top_share}
            />
            {where.categories.map((c) => (
              <ListRow
                key={c.category}
                title={c.category}
                sub={c.sub}
                wrap
                amount={c.amount}
                meta={c.meta}
                category={c.category}
                color={color(c.group)}
                onPress={() => drill('category', c.category)}
              />
            ))}
          </>
        ) : (
          <T muted>Nothing spent yet.</T>
        )}
      </Card>

      <Card>
        <CardTitle title="Keep an eye on" />
        {data.insights?.length ? (
          <>
            {data.insights.map((insight) => (
              <ListRow
                key={insight.id}
                title={insight.title}
                sub={insight.text}
                wrap
                category={insight.category}
                color={color(insight.category)}
                level={insight.level === 'critical' ? colors.critical : insight.level === 'warning' ? colors.warning : colors.accent}
                onPress={() => drill(insight.kind, insight.key)}
              />
            ))}
            <T variant="caption">Compared with your usual month: the average of up to three months before.</T>
          </>
        ) : (
          <T muted>{data.insights_empty}</T>
        )}
      </Card>

      <Card>
        <CardTitle title="Latest" right={<Button label="See all" kind="ghost" small onPress={() => router.push('/activity')} />} />
        <PaymentList rows={data.recent ?? []} slots={data.slots} empty="Nothing this month yet." />
      </Card>
    </View>
  );
}

function BudgetCard({ budget }: { budget: NonNullable<Overview['budget']> }) {
  const { colors } = useTheme();
  const [amount, setAmount] = useState<number | null>(null);
  const { run, busy } = useAction();
  if (!budget.set) {
    return (
      <Card>
        <CardTitle title={budget.title} />
        <T muted>Set how much you want to spend in a month, and see how you’re doing as it goes.</T>
        <Row style={{ alignItems: 'flex-end' }}>
          <View style={{ flex: 1 }}>
            <AmountField label="Monthly budget" value={amount} onChange={setAmount} hint={budget.hint} />
          </View>
        </Row>
        <Button
          label="Set budget"
          kind="primary"
          disabled={!amount}
          busy={busy}
          onPress={() => void run(() => api.put('/api/home/budget', { total: amount }))}
        />
      </Card>
    );
  }
  const fill = statusColor(colors, budget.status);
  const badge = budget.status === 'over' ? colors.critical : budget.status === 'heading over' ? colors.warning : colors.good;
  return (
    <Card>
      <CardTitle
        title={budget.title}
        right={<Badge label={budget.status_label} color={badge} icon={budget.status === 'over' ? 'warning' : budget.status === 'heading over' ? 'trending_up' : 'check_circle'} />}
      />
      <Meter share={budget.used} color={fill} />
      <Row style={{ justifyContent: 'space-between' }}>
        <T variant="caption">{budget.used_text}</T>
        <T variant="caption">{budget.remaining}</T>
      </Row>
      <RichText text={budget.sentence} />
      <Expandable title="See how we worked this out">
        {budget.explanation.map((line) => (
          <RichText key={line} text={`•  ${line}`} variant="small" />
        ))}
      </Expandable>
    </Card>
  );
}
