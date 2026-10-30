/** Settings → Skipped emails: emails from tracked senders that weren't counted, and why. */
import { useState } from 'react';
import { View } from 'react-native';

import { Card, Chips, ListRow, Loaded, Notice, T } from '@/components/ui';
import { useApi } from '@/lib/query';
import { space } from '@/lib/theme';
import type { Skipped } from '@/lib/types';

export function SkippedSection() {
  const [sources, setSources] = useState<string[]>([]);
  const skipped = useApi<Skipped>('/api/settings/skipped', { sources });
  return (
    <Loaded query={skipped}>
      {(data) =>
        !data.sources.length ? (
          <Notice text="Nothing skipped yet." />
        ) : (
          <View style={{ gap: space.lg }}>
            <T variant="caption">
              Promotions, OTPs and emails in a layout the app doesn’t recognise. If a real receipt, alert or statement is
              here, its parser needs adjusting (see the README), or narrow the bank’s sender.
            </T>
            <Chips options={data.sources.map((s) => ({ key: s, label: s }))} selected={sources} onChange={setSources} />
            <Card>
              {data.rows.map((row, i) => (
                <ListRow key={i} title={row.subject || '(no subject)'} sub={`${row.source} · ${row.received}\n${row.reason}`} wrap icon="mail" />
              ))}
            </Card>
          </View>
        )
      }
    </Loaded>
  );
}
