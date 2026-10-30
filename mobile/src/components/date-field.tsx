/** Picking a day (never in the future): Today and Yesterday at a tap, any other day from a calendar. */
import { useState } from 'react';
import { Modal, Pressable, StyleSheet, Text, View } from 'react-native';

import { Icon } from '@/components/icon';
import { Button, Row, T } from '@/components/ui';
import { addDays, dayName, isoDay, MONTH_NAMES, parseDay, today } from '@/lib/format';
import { radius, space, useTheme } from '@/lib/theme';

const WEEKDAYS = ['M', 'T', 'W', 'T', 'F', 'S', 'S'];

export function DateField({ label, value, onChange }: { label: string; value: string; onChange: (iso: string) => void }) {
  const { colors } = useTheme();
  const [open, setOpen] = useState(false);
  const quick = [today(), addDays(today(), -1)];
  return (
    <View style={{ gap: 6 }}>
      <T variant="small" style={{ fontWeight: '600' }}>
        {label}
      </T>
      <Row wrap>
        {quick.map((day) => (
          <Pressable
            key={day}
            accessibilityRole="radio"
            accessibilityState={{ checked: value === day }}
            onPress={() => onChange(day)}
            style={[styles.pill, { borderColor: value === day ? colors.accent : colors.border, backgroundColor: colors.card }]}>
            <Text style={{ color: value === day ? colors.accent : colors.text, fontWeight: '500' }}>{dayName(day)}</Text>
          </Pressable>
        ))}
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={`Pick a date, ${dayName(value)}`}
          onPress={() => setOpen(true)}
          style={[styles.pill, { borderColor: quick.includes(value) ? colors.border : colors.accent, backgroundColor: colors.card }]}>
          <Icon name="calendar_month" size={16} color={quick.includes(value) ? colors.muted : colors.accent} />
          <Text style={{ color: quick.includes(value) ? colors.text : colors.accent, fontWeight: '500' }}>
            {quick.includes(value) ? 'Another day' : dayName(value)}
          </Text>
        </Pressable>
      </Row>
      <Modal visible={open} transparent animationType="fade" onRequestClose={() => setOpen(false)}>
        <Pressable style={styles.backdrop} onPress={() => setOpen(false)}>
          <Pressable style={[styles.calendar, { backgroundColor: colors.card }]}>
            <Calendar
              value={value}
              onPick={(day) => {
                onChange(day);
                setOpen(false);
              }}
            />
            <Button label="Close" kind="ghost" onPress={() => setOpen(false)} />
          </Pressable>
        </Pressable>
      </Modal>
    </View>
  );
}

function Calendar({ value, onPick }: { value: string; onPick: (iso: string) => void }) {
  const { colors } = useTheme();
  const picked = parseDay(value);
  const [month, setMonth] = useState(new Date(picked.getFullYear(), picked.getMonth(), 1));
  const now = new Date();
  const lead = (month.getDay() + 6) % 7; // weeks start on Monday
  const days = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate();
  const cells: (number | null)[] = [...Array(lead).fill(null), ...Array.from({ length: days }, (_, i) => i + 1)];
  const isLatest = month.getFullYear() === now.getFullYear() && month.getMonth() === now.getMonth();
  const shift = (n: number) => setMonth(new Date(month.getFullYear(), month.getMonth() + n, 1));
  return (
    <View style={{ gap: space.sm }}>
      <Row>
        <Pressable accessibilityRole="button" accessibilityLabel="Previous month" onPress={() => shift(-1)} style={styles.nav}>
          <Icon name="chevron_left" size={20} color={colors.text} />
        </Pressable>
        <T variant="heading" style={{ flex: 1, textAlign: 'center' }}>
          {MONTH_NAMES[month.getMonth()]} {month.getFullYear()}
        </T>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Next month"
          disabled={isLatest}
          onPress={() => shift(1)}
          style={[styles.nav, isLatest && { opacity: 0.3 }]}>
          <Icon name="chevron_right" size={20} color={colors.text} />
        </Pressable>
      </Row>
      <View style={styles.grid}>
        {WEEKDAYS.map((d, i) => (
          <View key={`h${i}`} style={styles.cell}>
            <T variant="caption">{d}</T>
          </View>
        ))}
        {cells.map((day, i) => {
          if (day === null) return <View key={`e${i}`} style={styles.cell} />;
          const iso = isoDay(new Date(month.getFullYear(), month.getMonth(), day));
          const future = iso > today();
          const on = iso === value;
          return (
            <Pressable
              key={iso}
              accessibilityRole="button"
              accessibilityLabel={dayName(iso)}
              accessibilityState={{ selected: on, disabled: future }}
              disabled={future}
              onPress={() => onPick(iso)}
              style={[styles.cell, on && { backgroundColor: colors.accent, borderRadius: 20 }]}>
              <Text style={{ color: on ? colors.onAccent : future ? colors.border : colors.text, fontSize: 15 }}>{day}</Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  pill: { flexDirection: 'row', alignItems: 'center', gap: 6, borderWidth: 1, borderRadius: radius.pill, paddingVertical: 8, paddingHorizontal: 14 },
  backdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.35)', alignItems: 'center', justifyContent: 'center', padding: space.lg },
  calendar: { borderRadius: radius.lg, padding: space.lg, width: '100%', maxWidth: 360, gap: space.sm },
  nav: { padding: 8 },
  grid: { flexDirection: 'row', flexWrap: 'wrap' },
  cell: { width: `${100 / 7}%`, aspectRatio: 1, alignItems: 'center', justifyContent: 'center' },
});
