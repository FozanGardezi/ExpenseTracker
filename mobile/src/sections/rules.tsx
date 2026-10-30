/** Settings → Categories: your rules, your own categories, and who you spend for. */
import { useState } from 'react';
import { View } from 'react-native';

import { AmountField, Button, Card, CardTitle, Details, Divider, Expandable, Field, Loaded, Row, Select, T } from '@/components/ui';
import { api } from '@/lib/api';
import { useAction, useApi } from '@/lib/query';
import { space } from '@/lib/theme';
import type { Rule, Rules } from '@/lib/types';

type Draft = Rule & { id: number };
let nextId = 1;

export function RulesSection() {
  const rules = useApi<Rules>('/api/settings/rules');
  return (
    <Loaded query={rules}>
      {(data) => (
        <View style={{ gap: space.lg }}>
          <RulesEditor key={rules.dataUpdatedAt} data={data} />
          <Lists key={`lists-${rules.dataUpdatedAt}`} data={data} />
        </View>
      )}
    </Loaded>
  );
}

function RulesEditor({ data }: { data: Rules }) {
  const { run, busy } = useAction();
  const [drafts, setDrafts] = useState<Draft[]>(() => data.rules.map((r) => ({ ...r, id: nextId++ })));
  const change = (id: number, patch: Partial<Draft>) => setDrafts(drafts.map((d) => (d.id === id ? { ...d, ...patch } : d)));
  const categories = data.categories.map((c) => ({ key: c, label: c }));
  const labels = data.labels.map((l) => ({ key: l, label: l }));

  return (
    <Card>
      <CardTitle title="Rules" />
      <T muted>
        Rules give money going out a category, say who it was for, or both. When more than one rule matches, the one with
        the most conditions wins, so a big shop can be Groceries for Home while a small one at the same store is Food for
        Mine. A change you make to one transaction always wins.
      </T>
      <Expandable title="Examples">
        <Details rows={data.examples.map((e) => ({ label: e.words, value: e.set }))} />
      </Expandable>
      {drafts.map((rule, i) => (
        <View key={rule.id} style={{ gap: space.sm }}>
          <Divider />
          <Row>
            <T variant="strong" style={{ flex: 1 }}>
              Rule {i + 1}
            </T>
            {rule.matches !== undefined ? <T variant="caption">Applies to {rule.matches}</T> : null}
          </Row>
          <T variant="caption">When…</T>
          <Field
            label="Merchant or payee has"
            value={rule.words}
            placeholder="pso, total, shell"
            onChangeText={(words) => change(rule.id, { words })}
          />
          <Select label="Category is" value={rule.category_is || null} allowNone="Any" options={categories} onChange={(c) => change(rule.id, { category_is: c ?? '' })} />
          <Row>
            <View style={{ flex: 1 }}>
              <AmountField label="From amount" value={rule.min_amount} onChange={(v) => change(rule.id, { min_amount: v })} placeholder="Any" />
            </View>
            <View style={{ flex: 1 }}>
              <AmountField label="Up to amount" value={rule.max_amount} onChange={(v) => change(rule.id, { max_amount: v })} placeholder="Any" />
            </View>
          </Row>
          <T variant="caption">…set</T>
          <Select label="Category" value={rule.category || null} allowNone="Keep it" options={categories} onChange={(c) => change(rule.id, { category: c ?? '' })} />
          <Select label="For" value={rule.spent_for || null} allowNone="Keep it" options={labels} onChange={(l) => change(rule.id, { spent_for: l ?? '' })} />
          <View style={{ alignSelf: 'flex-start' }}>
            <Button label="Remove rule" kind="ghost" small icon="delete" onPress={() => setDrafts(drafts.filter((d) => d.id !== rule.id))} />
          </View>
        </View>
      ))}
      <Row wrap>
        <Button
          label="Add a rule"
          icon="add"
          onPress={() =>
            setDrafts([...drafts, { id: nextId++, words: '', category_is: '', min_amount: null, max_amount: null, category: '', spent_for: '' }])
          }
        />
        <Button
          label="Save rules"
          kind="primary"
          busy={busy}
          onPress={() => void run(() => api.put('/api/settings/rules', { rules: drafts.map(({ id: _, matches: __, ...rule }) => rule) }))}
        />
      </Row>
    </Card>
  );
}

function Lists({ data }: { data: Rules }) {
  const { run, busy } = useAction();
  const [categories, setCategories] = useState(data.my_categories.join(', '));
  const [spendFor, setSpendFor] = useState(data.labels.join(', '));
  return (
    <Card>
      <CardTitle title="Your lists" />
      <Field
        label="Your own categories"
        value={categories}
        onChangeText={setCategories}
        placeholder="Going out, Clothes, Gifts"
        hint="Added to the built-in categories everywhere you pick one. Separate them with commas."
      />
      <Field
        label="Who you spend for"
        value={spendFor}
        onChangeText={setSpendFor}
        hint="Each payment can be marked as for one of these, like yourself or your home. The first one is used until a rule or you say otherwise."
      />
      <Button label="Save lists" busy={busy} onPress={() => void run(() => api.put('/api/settings/lists', { categories, spend_for: spendFor }))} />
    </Card>
  );
}
