/** A period preset (This month … All time), or your own dates. */
import { View } from 'react-native';

import { DateField } from '@/components/date-field';
import { Select } from '@/components/ui';
import { space } from '@/lib/theme';

export type Period = { period?: string; start?: string; end?: string };

export function PeriodPicker({
  periods,
  value,
  shown,
  onChange,
}: {
  periods: string[];
  value: Period;
  shown?: { period?: string; start?: string; end?: string };
  onChange: (p: Period) => void;
}) {
  const current = value.period ?? shown?.period ?? periods[0];
  return (
    <View style={{ gap: space.sm }}>
      <Select
        label="Period"
        value={current}
        options={periods.map((p) => ({ key: p, label: p }))}
        onChange={(period) => onChange({ period: period ?? undefined, start: shown?.start, end: shown?.end })}
      />
      {current === 'Custom' && shown?.start && shown?.end ? (
        <>
          <DateField label="From" value={value.start ?? shown.start} onChange={(start) => onChange({ ...value, period: 'Custom', start })} />
          <DateField label="To" value={value.end ?? shown.end} onChange={(end) => onChange({ ...value, period: 'Custom', end })} />
        </>
      ) : null}
    </View>
  );
}
