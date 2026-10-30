/** Home → Places: where the money goes, place by place, and how often. Search for one to see what it costs a month. */
import { useRouter } from 'expo-router';
import { useState } from 'react';
import { View } from 'react-native';

import { Sparkbars } from '@/components/charts';
import { Button, Card, CardTitle, Field, ListRow, Loaded, Notice, RichText, Segmented, T } from '@/components/ui';
import { useApi } from '@/lib/query';
import { slotColor, space, useTheme } from '@/lib/theme';
import type { Places } from '@/lib/types';

export function PlacesSection() {
  const { colors } = useTheme();
  const router = useRouter();
  const [period, setPeriod] = useState(3);
  const [sort, setSort] = useState<'spent' | 'often'>('spent');
  const [typed, setTyped] = useState('');
  const [search, setSearch] = useState('');
  const places = useApi<Places>('/api/home/places', { period, sort, search });

  return (
    <Loaded query={places}>
      {(data) =>
        data.empty ? (
          <Notice text="The places you pay appear here after the first sync." />
        ) : (
          <View style={{ gap: space.lg }}>
            <Segmented options={data.periods} value={data.period} onChange={setPeriod} />
            <Field
              placeholder="Find a place, e.g. double shot"
              value={typed}
              onChangeText={setTyped}
              onSubmitEditing={() => setSearch(typed.trim())}
              onBlur={() => setSearch(typed.trim())}
              returnKeyType="search"
              accessibilityLabel="Find a place"
            />
            {data.found ? (
              <Card>
                <CardTitle title={`“${data.found.search}”`} />
                {data.found.empty ? <T muted>{data.found.text}</T> : <RichText text={data.found.text} />}
                {!data.found.empty ? (
                  <Button
                    label="See the payments"
                    icon="list"
                    onPress={() => router.push({ pathname: '/drill', params: { kind: 'search', key: data.found!.search } })}
                  />
                ) : null}
              </Card>
            ) : null}
            <Card>
              <CardTitle title="Places" />
              <T variant="caption">{data.caption}</T>
              <Segmented
                options={[
                  { key: 'spent', label: 'Most spent' },
                  { key: 'often', label: 'Most often' },
                ]}
                value={data.sort ?? 'spent'}
                onChange={setSort}
              />
              {(data.places ?? []).map((place) => (
                <ListRow
                  key={place.place}
                  title={place.name}
                  sub={`${place.times} ${place.times === 1 ? 'time' : 'times'} · ${place.each} each`}
                  amount={place.spent}
                  category={place.category}
                  color={slotColor(colors, data.slots ?? {}, place.category)}
                  right={<Sparkbars values={place.trend} color={slotColor(colors, data.slots ?? {}, place.category)} />}
                  onPress={() =>
                    router.push({ pathname: '/drill', params: { kind: 'places', key: place.place, period: String(data.period) } })
                  }
                />
              ))}
              {!data.places?.length ? <T muted>Nothing spent in this period.</T> : null}
            </Card>
          </View>
        )
      }
    </Loaded>
  );
}
