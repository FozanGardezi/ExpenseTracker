/** The four tabs in the browser: a bar along the bottom, like the phone app's. */
import { TabList, TabSlot, TabTrigger, Tabs, type TabTriggerSlotProps } from 'expo-router/ui';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { Icon, type IconName } from '@/components/icon';
import { useTheme } from '@/lib/theme';

const TABS: { name: string; href: '/' | '/activity' | '/accounts' | '/settings'; label: string; icon: IconName }[] = [
  { name: 'index', href: '/', label: 'Home', icon: 'home' },
  { name: 'activity', href: '/activity', label: 'Activity', icon: 'receipt_long' },
  { name: 'accounts', href: '/accounts', label: 'Accounts', icon: 'account_balance' },
  { name: 'settings', href: '/settings', label: 'Settings', icon: 'settings' },
];

export default function AppTabs() {
  const { colors } = useTheme();
  return (
    <Tabs>
      <TabSlot style={{ flex: 1 }} />
      <TabList asChild>
        {/* A Slot's child takes one style object, not a list. */}
        <View style={StyleSheet.flatten([styles.bar, { backgroundColor: colors.card, borderTopColor: colors.border }])}>
          {TABS.map((tab) => (
            <TabTrigger key={tab.name} name={tab.name} href={tab.href} asChild>
              <TabButton icon={tab.icon} label={tab.label} />
            </TabTrigger>
          ))}
        </View>
      </TabList>
    </Tabs>
  );
}

function TabButton({ icon, label, isFocused, ref: _ref, ...props }: TabTriggerSlotProps & { icon: IconName; label: string }) {
  const { colors } = useTheme();
  const color = isFocused ? colors.accent : colors.muted;
  return (
    <Pressable {...props} accessibilityRole="tab" accessibilityState={{ selected: isFocused }} style={styles.tab}>
      <View style={[styles.pill, isFocused && { backgroundColor: colors.element }]}>
        <Icon name={icon} size={22} color={color} />
      </View>
      <Text style={[styles.label, { color }]}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  bar: { flexDirection: 'row', borderTopWidth: StyleSheet.hairlineWidth, paddingTop: 6, paddingBottom: 10 },
  tab: { flex: 1, alignItems: 'center', gap: 2 },
  pill: { borderRadius: 14, paddingVertical: 4, paddingHorizontal: 18 },
  label: { fontSize: 12, fontWeight: '600' },
});
