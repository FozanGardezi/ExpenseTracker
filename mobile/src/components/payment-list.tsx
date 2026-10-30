/** Payments as a list you tap, like a banking app: under day headers with times, or each with its date. */
import { useRouter } from 'expo-router';
import { View } from 'react-native';

import { ListRow, SectionLabel, T } from '@/components/ui';
import { slotColor, useTheme } from '@/lib/theme';
import type { PaymentRow } from '@/lib/types';

export function PaymentList({
  rows,
  slots = {},
  byDay = true,
  empty = 'Nothing here.',
}: {
  rows: PaymentRow[];
  slots?: Record<string, number>;
  byDay?: boolean;
  empty?: string;
}) {
  const { colors } = useTheme();
  const router = useRouter();
  if (!rows.length) return <T muted>{empty}</T>;
  return (
    <View>
      {rows.map((row, i) => {
        const header = byDay && (i === 0 || rows[i - 1].day !== row.day) ? row.day_label : null;
        return (
          <View key={row.id}>
            {header ? <SectionLabel>{header}</SectionLabel> : null}
            <ListRow
              title={row.title}
              sub={row.sub}
              amount={row.amount}
              meta={row.meta}
              moneyIn={row.money_in}
              category={row.category}
              color={slotColor(colors, slots, row.category)}
              onPress={() => router.push({ pathname: '/payment/[item]', params: { item: row.id } })}
            />
          </View>
        );
      })}
    </View>
  );
}
