/** Home → Budget: how much to spend in a month, and limits on parts of it (eating out, petrol, one coffee shop). */
import { useState } from 'react';
import { View } from 'react-native';

import {
  AmountField, Button, Card, CardTitle, Details, Divider, Expandable, Field, Loaded, Row, Select, T,
} from '@/components/ui';
import { api } from '@/lib/api';
import { useAction, useApi } from '@/lib/query';
import { space } from '@/lib/theme';
import type { BudgetPage } from '@/lib/types';

type LimitDraft = { id: number; name: string; category: string; words: string; amount: number | null };
let nextId = 1;

export function BudgetSection() {
  const budget = useApi<BudgetPage>('/api/home/budget');
  return <Loaded query={budget}>{(data) => <Editor key={budget.dataUpdatedAt} data={data} />}</Loaded>;
}

function Editor({ data }: { data: BudgetPage }) {
  const { run, busy } = useAction();
  const [total, setTotal] = useState<number | null>(data.total);
  const [limits, setLimits] = useState<LimitDraft[]>(() =>
    data.limits.map((l) => ({ id: nextId++, name: l.name, category: l.category, words: l.words, amount: l.amount })),
  );
  const change = (id: number, patch: Partial<LimitDraft>) => setLimits(limits.map((l) => (l.id === id ? { ...l, ...patch } : l)));
  const categories = data.categories.map((c) => ({ key: c, label: c }));

  return (
    <View style={{ gap: space.lg }}>
      <Card>
        <CardTitle title="Your monthly budget" />
        <AmountField
          label={`How much you want to spend in a month (${data.currency})`}
          value={total}
          onChange={setTotal}
          placeholder="No budget yet"
          hint={data.usual_month ? `Your usual month: about ${data.usual_month} (the average of the last three months).` : null}
        />
        <Divider />
        <T variant="heading">Limits</T>
        <T variant="caption">Keep part of your spending in check: a category, places whose name has certain words, or both.</T>
        {limits.map((limit, i) => {
          const saved = data.limits[i];
          return (
            <View key={limit.id} style={{ gap: space.sm }}>
              <Divider />
              <Field label="Name" value={limit.name} placeholder="e.g. Eating out" onChangeText={(name) => change(limit.id, { name })} />
              <Select
                label="Category"
                value={limit.category || null}
                options={categories}
                allowNone="Any category"
                onChange={(category) => change(limit.id, { category: category ?? '' })}
              />
              <Field
                label="Places with these words"
                value={limit.words}
                placeholder="double shot, gloria jeans"
                onChangeText={(words) => change(limit.id, { words })}
                hint="Words or names, separated by commas; any one matches."
              />
              <AmountField label="Monthly limit" value={limit.amount} onChange={(amount) => change(limit.id, { amount })} />
              {saved && saved.name === limit.name ? (
                <T variant="caption">
                  This month: {saved.spent} · usual month: {saved.usual}
                </T>
              ) : null}
              <View style={{ alignSelf: 'flex-start' }}>
                <Button label="Remove limit" kind="ghost" small icon="delete" onPress={() => setLimits(limits.filter((l) => l.id !== limit.id))} />
              </View>
            </View>
          );
        })}
        <Row wrap>
          <Button
            label="Add a limit"
            icon="add"
            onPress={() => setLimits([...limits, { id: nextId++, name: '', category: '', words: '', amount: null }])}
          />
          <Button
            label="Save budget"
            kind="primary"
            busy={busy}
            onPress={() =>
              void run(() =>
                api.put('/api/home/budget', {
                  total,
                  limits: limits.map(({ name, category, words, amount }) => ({ name, category, words, amount })),
                }),
              )
            }
          />
        </Row>
        <T variant="caption">Changes apply from {data.from} on; earlier months keep the budget they had.</T>
      </Card>
      <Card>
        <Expandable title="Examples">
          {data.examples.map((e) => (
            <Details
              key={e.name}
              rows={[{ label: e.name, value: [e.category, e.words, `limit ${e.amount}`].filter(Boolean).join(' · ') }]}
            />
          ))}
          <T variant="caption">
            A limit with words follows one place, like a coffee shop, whatever its category. You can also set one from a
            place’s or category’s payments on Overview or Places.
          </T>
        </Expandable>
        {data.history.length ? (
          <Expandable title="Earlier budgets">
            <Details rows={data.history.map((h) => ({ label: `From ${h.from}`, value: `${h.total} · ${h.limits} limits` }))} />
          </Expandable>
        ) : null}
      </Card>
    </View>
  );
}
