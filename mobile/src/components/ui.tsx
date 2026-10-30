/**
 * The building blocks every screen uses, in the app's look: cards on a calm background,
 * lists you tap, a teal accent. Text that comes with **bold** parts goes through RichText.
 */
import { useState, type PropsWithChildren, type ReactNode } from 'react';
import {
  ActivityIndicator,
  FlatList,
  Modal,
  Platform,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  View,
  type StyleProp,
  type TextInputProps,
  type TextStyle,
  type ViewStyle,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { categoryIcon, Icon, type IconName } from '@/components/icon';
import { messageOf } from '@/lib/api';
import { radius, space, useTheme, wash } from '@/lib/theme';

export const MAX_WIDTH = 760;

// --- text ---

type Variant = 'hero' | 'title' | 'heading' | 'body' | 'strong' | 'small' | 'caption' | 'mono';

const textStyles = StyleSheet.create({
  hero: { fontSize: 44, fontWeight: '700', letterSpacing: -0.8, lineHeight: 50 },
  title: { fontSize: 28, fontWeight: '700', letterSpacing: -0.3 },
  heading: { fontSize: 18, fontWeight: '600' },
  body: { fontSize: 15, lineHeight: 21 },
  strong: { fontSize: 15, lineHeight: 21, fontWeight: '600' },
  small: { fontSize: 13, lineHeight: 18 },
  caption: { fontSize: 12.5, lineHeight: 17 },
  mono: { fontSize: 12.5, fontFamily: Platform.select({ ios: 'Menlo', android: 'monospace', default: 'monospace' }) },
});

export function T({
  variant = 'body',
  muted,
  color,
  style,
  children,
  numberOfLines,
  selectable,
}: PropsWithChildren<{
  variant?: Variant;
  muted?: boolean;
  color?: string;
  style?: StyleProp<TextStyle>;
  numberOfLines?: number;
  selectable?: boolean;
}>) {
  const { colors } = useTheme();
  const tone = color ?? (muted || variant === 'caption' ? colors.muted : colors.text);
  return (
    <Text style={[textStyles[variant], { color: tone }, style]} numberOfLines={numberOfLines} selectable={selectable}>
      {children}
    </Text>
  );
}

/** Text with **bold** parts, as the API writes sentences ("**Rs 3,000** left"). */
export function RichText({ text, variant = 'body', muted, style }: { text: string; variant?: Variant; muted?: boolean; style?: StyleProp<TextStyle> }) {
  const parts = text.split('**');
  return (
    <T variant={variant} muted={muted} style={style}>
      {parts.map((part, i) =>
        i % 2 ? (
          <Text key={i} style={{ fontWeight: '700' }}>
            {part}
          </Text>
        ) : (
          part
        ),
      )}
    </T>
  );
}

// --- layout ---

/** A tab or sheet's scrolling page, centred on wide screens. */
export function Screen({
  children,
  onRefresh,
  refreshing = false,
  top = true,
}: PropsWithChildren<{ onRefresh?: () => void; refreshing?: boolean; top?: boolean }>) {
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  return (
    <ScrollView
      style={{ flex: 1, backgroundColor: colors.background }}
      contentInsetAdjustmentBehavior="automatic"
      keyboardShouldPersistTaps="handled"
      contentContainerStyle={[
        styles.screen,
        { paddingTop: (top ? insets.top : 0) + space.lg, paddingBottom: insets.bottom + 110 },
      ]}
      refreshControl={onRefresh ? <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.muted} /> : undefined}>
      {children}
    </ScrollView>
  );
}

export function Card({ children, style }: PropsWithChildren<{ style?: StyleProp<ViewStyle> }>) {
  const { colors } = useTheme();
  return <View style={[styles.card, { backgroundColor: colors.card, borderColor: colors.line }, style]}>{children}</View>;
}

export function CardTitle({ title, right }: { title: string; right?: ReactNode }) {
  return (
    <View style={styles.cardTitle}>
      <T variant="heading" style={{ flex: 1 }}>
        {title}
      </T>
      {right}
    </View>
  );
}

export function Row({ children, gap = space.sm, style, wrap }: PropsWithChildren<{ gap?: number; style?: StyleProp<ViewStyle>; wrap?: boolean }>) {
  return <View style={[{ flexDirection: 'row', alignItems: 'center', gap, flexWrap: wrap ? 'wrap' : 'nowrap' }, style]}>{children}</View>;
}

export function Gap({ size = space.md }: { size?: number }) {
  return <View style={{ height: size }} />;
}

// --- actions ---

type ButtonKind = 'primary' | 'secondary' | 'ghost' | 'danger';

export function Button({
  label,
  onPress,
  kind = 'secondary',
  icon,
  disabled,
  busy,
  wide,
  small,
}: {
  label: string;
  onPress: () => void;
  kind?: ButtonKind;
  icon?: IconName;
  disabled?: boolean;
  busy?: boolean;
  wide?: boolean;
  small?: boolean;
}) {
  const { colors } = useTheme();
  const look = {
    primary: { bg: colors.accent, fg: colors.onAccent, border: colors.accent },
    secondary: { bg: colors.card, fg: colors.text, border: colors.border },
    ghost: { bg: 'transparent', fg: colors.accent, border: 'transparent' },
    danger: { bg: 'transparent', fg: colors.critical, border: colors.critical },
  }[kind];
  const off = disabled || busy;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled: !!off, busy: !!busy }}
      disabled={off}
      onPress={onPress}
      style={({ pressed }) => [
        styles.button,
        small && styles.buttonSmall,
        { backgroundColor: look.bg, borderColor: look.border, opacity: off ? 0.45 : pressed ? 0.75 : 1 },
        wide && { alignSelf: 'stretch' },
      ]}>
      {busy ? <ActivityIndicator size="small" color={look.fg} /> : icon ? <Icon name={icon} size={small ? 16 : 18} color={look.fg} /> : null}
      <Text style={[styles.buttonText, small && { fontSize: 14 }, { color: look.fg }]}>{label}</Text>
    </Pressable>
  );
}

/** A choice among a few options, like Overview / Trends / Places / Budget. */
export function Segmented<K extends string | number>({
  options,
  value,
  onChange,
  scroll,
}: {
  options: { key: K; label: string }[];
  value: K;
  onChange: (key: K) => void;
  scroll?: boolean;
}) {
  const { colors } = useTheme();
  const items = options.map((option) => {
    const on = option.key === value;
    return (
      <Pressable
        key={String(option.key)}
        accessibilityRole="tab"
        accessibilityState={{ selected: on }}
        onPress={() => onChange(option.key)}
        style={[styles.segment, scroll ? { paddingHorizontal: 12 } : { flex: 1 }, on && { backgroundColor: colors.card, borderColor: colors.line }]}>
        <Text numberOfLines={1} style={[styles.segmentText, { color: on ? colors.text : colors.muted, fontWeight: on ? '600' : '500' }]}>
          {option.label}
        </Text>
      </Pressable>
    );
  });
  const track = [styles.segments, { backgroundColor: colors.element }];
  return scroll ? (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={track}>
      {items}
    </ScrollView>
  ) : (
    <View accessibilityRole="tablist" style={track}>
      {items}
    </View>
  );
}

/** Toggle chips, for picking several (sources, categories, months). */
export function Chips<K extends string | number>({
  options,
  selected,
  onChange,
}: {
  options: { key: K; label: string }[];
  selected: K[];
  onChange: (next: K[]) => void;
}) {
  const { colors } = useTheme();
  return (
    <Row wrap gap={space.sm}>
      {options.map((option) => {
        const on = selected.includes(option.key);
        return (
          <Pressable
            key={String(option.key)}
            accessibilityRole="checkbox"
            accessibilityState={{ checked: on }}
            onPress={() => onChange(on ? selected.filter((k) => k !== option.key) : [...selected, option.key])}
            style={[
              styles.chip,
              { borderColor: on ? colors.accent : colors.border, backgroundColor: on ? wash(colors.accent, 0.12) : colors.card },
            ]}>
            {on && <Icon name="check" size={14} color={colors.accent} />}
            <Text style={{ color: on ? colors.accent : colors.text, fontSize: 14, fontWeight: '500' }}>{option.label}</Text>
          </Pressable>
        );
      })}
    </Row>
  );
}

// --- inputs ---

export function Field({
  label,
  hint,
  style,
  ...input
}: TextInputProps & { label?: string; hint?: string | null; style?: StyleProp<ViewStyle> }) {
  const { colors } = useTheme();
  return (
    <View style={[{ gap: 6 }, style]}>
      {label ? <T variant="small" style={{ fontWeight: '600' }}>{label}</T> : null}
      <TextInput
        placeholderTextColor={colors.muted}
        {...input}
        accessibilityLabel={input.accessibilityLabel ?? label}
        style={[
          styles.input,
          { color: colors.text, backgroundColor: colors.card, borderColor: colors.border },
          input.multiline && { minHeight: 96, textAlignVertical: 'top' },
        ]}
      />
      {hint ? <T variant="caption">{hint}</T> : null}
    </View>
  );
}

/** An amount typed in; empty is null. */
export function AmountField({
  label,
  value,
  onChange,
  hint,
  placeholder = 'Amount',
}: {
  label?: string;
  value: number | null;
  onChange: (value: number | null) => void;
  hint?: string | null;
  placeholder?: string;
}) {
  const [text, setText] = useState(value === null ? '' : String(value));
  return (
    <Field
      label={label}
      hint={hint}
      value={text}
      placeholder={placeholder}
      keyboardType="decimal-pad"
      inputMode="decimal"
      onChangeText={(next) => {
        const clean = next.replace(/[^0-9.]/g, '');
        setText(clean);
        const parsed = parseFloat(clean);
        onChange(Number.isFinite(parsed) ? parsed : null);
      }}
    />
  );
}

export function Toggle({ label, value, onChange, hint, disabled }: { label: string; value: boolean; onChange: (v: boolean) => void; hint?: string; disabled?: boolean }) {
  const { colors } = useTheme();
  return (
    <Pressable
      accessibilityRole="switch"
      accessibilityState={{ checked: value, disabled }}
      disabled={disabled}
      onPress={() => onChange(!value)}
      style={styles.toggle}>
      <View style={{ flex: 1, gap: 2 }}>
        <T variant="strong">{label}</T>
        {hint ? <T variant="caption">{hint}</T> : null}
      </View>
      <Switch
        value={value}
        onValueChange={onChange}
        disabled={disabled}
        trackColor={{ true: colors.accent, false: colors.border }}
        thumbColor={Platform.OS === 'android' ? colors.card : undefined}
      />
    </Pressable>
  );
}

/** Pick one from a list, in a sheet: categories, months, accounts. */
export function Select<K extends string | number>({
  label,
  value,
  options,
  onChange,
  placeholder = 'Choose',
  allowNone,
}: {
  label?: string;
  value: K | null;
  options: { key: K; label: string }[];
  onChange: (key: K | null) => void;
  placeholder?: string;
  allowNone?: string;
}) {
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const [open, setOpen] = useState(false);
  const current = options.find((o) => o.key === value);
  const listed: { key: K | null; label: string }[] = allowNone ? [{ key: null, label: allowNone }, ...options] : options;
  return (
    <View style={{ gap: 6 }}>
      {label ? <T variant="small" style={{ fontWeight: '600' }}>{label}</T> : null}
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={label ? `${label}: ${current?.label ?? placeholder}` : undefined}
        onPress={() => setOpen(true)}
        style={[styles.input, styles.select, { backgroundColor: colors.card, borderColor: colors.border }]}>
        <Text numberOfLines={1} style={{ flex: 1, fontSize: 15, color: current ? colors.text : colors.muted }}>
          {current?.label ?? (value === null && allowNone ? allowNone : placeholder)}
        </Text>
        <Icon name="expand_more" size={18} color={colors.muted} />
      </Pressable>
      <Modal visible={open} transparent animationType="fade" onRequestClose={() => setOpen(false)}>
        <Pressable style={styles.backdrop} onPress={() => setOpen(false)}>
          <Pressable style={[styles.sheet, { backgroundColor: colors.card, paddingBottom: insets.bottom + space.md }]}>
            {label ? (
              <T variant="heading" style={{ padding: space.lg, paddingBottom: space.sm }}>
                {label}
              </T>
            ) : null}
            <FlatList
              data={listed}
              keyExtractor={(item) => String(item.key)}
              renderItem={({ item }) => {
                const on = item.key === value;
                return (
                  <Pressable
                    accessibilityRole="menuitem"
                    accessibilityState={{ selected: on }}
                    onPress={() => {
                      onChange(item.key);
                      setOpen(false);
                    }}
                    style={({ pressed }) => [styles.option, pressed && { backgroundColor: colors.element }]}>
                    <Text style={{ flex: 1, fontSize: 16, color: colors.text, fontWeight: on ? '600' : '400' }}>{item.label}</Text>
                    {on && <Icon name="check" size={18} color={colors.accent} />}
                  </Pressable>
                );
              }}
            />
          </Pressable>
        </Pressable>
      </Modal>
    </View>
  );
}

// --- lists ---

/** A tappable list row: an icon on a wash of its color, a title and line under it, an amount. */
export function ListRow({
  title,
  sub,
  amount,
  meta,
  icon,
  category,
  color,
  moneyIn,
  onPress,
  level,
  share,
  shareColor,
  wrap,
  right,
}: {
  title: string;
  sub?: string | null;
  amount?: string | null;
  meta?: string | null;
  icon?: IconName;
  category?: string;
  color?: string;
  moneyIn?: boolean;
  onPress?: () => void;
  level?: string;
  share?: number;
  shareColor?: string;
  wrap?: boolean;
  right?: ReactNode;
}) {
  const { colors } = useTheme();
  const tint = color ?? colors.neutral;
  const glyph = icon ?? (category ? categoryIcon(category) : undefined);
  const body = (
    <>
      <View style={styles.listRow}>
        {glyph ? (
          <View style={[styles.rowIcon, { backgroundColor: wash(tint) }]}>
            <Icon name={glyph} size={20} color={tint} />
          </View>
        ) : null}
        <View style={{ flex: 1, minWidth: 0 }}>
          <T variant="strong" numberOfLines={1}>
            {title}
          </T>
          {sub ? (
            <T variant="small" muted numberOfLines={wrap ? undefined : 1}>
              {sub}
            </T>
          ) : null}
        </View>
        {right}
        {amount || meta ? (
          <View style={{ alignItems: 'flex-end', maxWidth: '45%' }}>
            {amount ? (
              <T variant="strong" color={moneyIn ? colors.good : undefined} style={{ fontVariant: ['tabular-nums'] }} numberOfLines={1}>
                {amount}
              </T>
            ) : null}
            {meta ? (
              <T variant="caption" numberOfLines={1}>
                {meta}
              </T>
            ) : null}
          </View>
        ) : onPress && !right ? (
          <Icon name="chevron_right" size={18} color={colors.muted} />
        ) : null}
      </View>
      {share !== undefined ? <Meter share={share} color={shareColor ?? colors.accent} style={{ marginLeft: glyph ? 52 : 0 }} /> : null}
    </>
  );
  const edge = level ? { borderLeftWidth: 3, borderLeftColor: level, paddingLeft: space.sm } : null;
  if (!onPress) return <View style={[styles.rowWrap, edge]}>{body}</View>;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={[title, amount, sub].filter(Boolean).join(', ')}
      onPress={onPress}
      style={({ pressed }) => [styles.rowWrap, edge, pressed && { backgroundColor: colors.element }]}>
      {body}
    </Pressable>
  );
}

export function SectionLabel({ children }: PropsWithChildren) {
  return (
    <T variant="caption" style={{ fontWeight: '600', marginTop: space.md, marginBottom: 2, paddingHorizontal: 4 }}>
      {children}
    </T>
  );
}

// --- figures ---

export function Meter({ share, color, style }: { share: number; color: string; style?: StyleProp<ViewStyle> }) {
  return (
    <View style={[styles.meter, { backgroundColor: wash(color, 0.2) }, style]}>
      <View style={{ width: `${Math.min(Math.max(share, 0), 1) * 100}%`, height: '100%', borderRadius: 4, backgroundColor: color }} />
    </View>
  );
}

export function Badge({ label, color, icon }: { label: string; color: string; icon?: IconName }) {
  return (
    <View style={[styles.badge, { backgroundColor: wash(color, 0.15) }]}>
      {icon && <Icon name={icon} size={14} color={color} />}
      <Text style={{ color, fontSize: 12.5, fontWeight: '600' }}>{label}</Text>
    </View>
  );
}

export function Stats({ items }: { items: { label: string; value: string; help?: string | null }[] }) {
  const { colors } = useTheme();
  return (
    <View style={styles.stats}>
      {items.map((item) => (
        <View key={item.label} style={[styles.stat, { backgroundColor: colors.card, borderColor: colors.line }]}>
          <T variant="caption">{item.label}</T>
          <T variant="heading" style={{ fontSize: 20 }} numberOfLines={1}>
            {item.value}
          </T>
          {item.help ? <T variant="caption">{item.help}</T> : null}
        </View>
      ))}
    </View>
  );
}

export function Details({ rows }: { rows: { label: string; value: string }[] }) {
  const { colors } = useTheme();
  return (
    <View>
      {rows.map((row) => (
        <View key={row.label} style={[styles.detail, { borderTopColor: colors.line }]}>
          <T variant="small" muted style={{ flex: 1 }}>
            {row.label}
          </T>
          <T variant="small" selectable style={{ flex: 2, textAlign: 'right', fontWeight: '600' }}>
            {row.value}
          </T>
        </View>
      ))}
    </View>
  );
}

// --- states ---

export function Notice({ text, kind = 'info', children }: PropsWithChildren<{ text?: string; kind?: 'info' | 'success' | 'warning' | 'error' }>) {
  const { colors } = useTheme();
  const tone = { info: colors.accent, success: colors.good, warning: colors.warning, error: colors.critical }[kind];
  const icon: IconName = { info: 'info', success: 'check_circle', warning: 'warning', error: 'error' }[kind] as IconName;
  return (
    <View style={[styles.notice, { backgroundColor: wash(tone, 0.12), borderColor: wash(tone, 0.35) }]}>
      <Icon name={icon} size={20} color={tone} />
      <View style={{ flex: 1, gap: space.sm }}>
        {text ? <RichText text={text} /> : null}
        {children}
      </View>
    </View>
  );
}

export function Loading() {
  const { colors } = useTheme();
  return (
    <View style={{ padding: space.xxl, alignItems: 'center' }}>
      <ActivityIndicator color={colors.muted} />
    </View>
  );
}

/** What a screen shows while loading, after an error, or when it has data. */
export function Loaded<T>({
  query,
  children,
}: {
  query: { data?: T; isLoading: boolean; error: unknown; refetch: () => unknown };
  children: (data: T) => ReactNode;
}) {
  if (query.data !== undefined) return <>{children(query.data)}</>;
  if (query.error) {
    return (
      <Notice kind="error" text={messageOf(query.error)}>
        <Button label="Try again" small icon="sync" onPress={() => void query.refetch()} />
      </Notice>
    );
  }
  return <Loading />;
}

export function Expandable({ title, children, initiallyOpen = false, icon }: PropsWithChildren<{ title: string; initiallyOpen?: boolean; icon?: IconName }>) {
  const { colors } = useTheme();
  const [open, setOpen] = useState(initiallyOpen);
  return (
    <View>
      <Pressable
        accessibilityRole="button"
        accessibilityState={{ expanded: open }}
        onPress={() => setOpen(!open)}
        style={styles.expandable}>
        {icon ? <Icon name={icon} size={18} color={colors.muted} /> : null}
        <T variant="strong" style={{ flex: 1 }}>
          {title}
        </T>
        <Icon name={open ? 'expand_less' : 'expand_more'} size={20} color={colors.muted} />
      </Pressable>
      {open ? <View style={{ gap: space.md, paddingBottom: space.sm }}>{children}</View> : null}
    </View>
  );
}

export function Code({ children }: { children: string }) {
  const { colors } = useTheme();
  return (
    <View style={[styles.code, { backgroundColor: colors.element }]}>
      <T variant="mono" selectable>
        {children}
      </T>
    </View>
  );
}

export function Divider() {
  const { colors } = useTheme();
  return <View style={{ height: StyleSheet.hairlineWidth, backgroundColor: colors.border, marginVertical: space.sm }} />;
}

const styles = StyleSheet.create({
  screen: { paddingHorizontal: space.lg, gap: space.lg, width: '100%', maxWidth: MAX_WIDTH, alignSelf: 'center' },
  card: { borderRadius: radius.lg, borderWidth: 1, padding: space.lg, gap: space.md },
  cardTitle: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  button: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    borderRadius: radius.md,
    borderWidth: 1,
    paddingVertical: 11,
    paddingHorizontal: 16,
    minHeight: 44,
  },
  buttonSmall: { paddingVertical: 7, paddingHorizontal: 12, minHeight: 36 },
  buttonText: { fontSize: 15, fontWeight: '600' },
  segments: { flexDirection: 'row', borderRadius: radius.md, padding: 3, gap: 2 },
  segment: { borderRadius: 11, paddingVertical: 8, paddingHorizontal: 6, alignItems: 'center', borderWidth: 1, borderColor: 'transparent' },
  segmentText: { fontSize: 14 },
  chip: { flexDirection: 'row', alignItems: 'center', gap: 4, borderWidth: 1, borderRadius: radius.pill, paddingVertical: 7, paddingHorizontal: 12 },
  input: { borderWidth: 1, borderRadius: radius.sm + 2, paddingHorizontal: 12, paddingVertical: 11, fontSize: 15, minHeight: 46 },
  select: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  toggle: { flexDirection: 'row', alignItems: 'center', gap: space.md, paddingVertical: 4 },
  backdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.35)', justifyContent: 'flex-end' },
  sheet: { maxHeight: '75%', borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg, width: '100%', maxWidth: MAX_WIDTH, alignSelf: 'center' },
  option: { flexDirection: 'row', alignItems: 'center', paddingVertical: 14, paddingHorizontal: space.lg },
  rowWrap: { borderRadius: radius.md, paddingVertical: 10, paddingHorizontal: 6, gap: 6 },
  listRow: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  rowIcon: { width: 40, height: 40, borderRadius: 20, alignItems: 'center', justifyContent: 'center' },
  meter: { height: 8, borderRadius: 4, overflow: 'hidden' },
  badge: { flexDirection: 'row', alignItems: 'center', gap: 4, borderRadius: radius.pill, paddingVertical: 4, paddingHorizontal: 10 },
  stats: { flexDirection: 'row', flexWrap: 'wrap', gap: space.sm },
  stat: { flexGrow: 1, flexBasis: 150, borderWidth: 1, borderRadius: radius.md, padding: space.md, gap: 2 },
  detail: { flexDirection: 'row', gap: space.md, paddingVertical: 9, borderTopWidth: StyleSheet.hairlineWidth },
  notice: { flexDirection: 'row', gap: space.md, borderRadius: radius.md, borderWidth: 1, padding: space.md, alignItems: 'flex-start' },
  expandable: { flexDirection: 'row', alignItems: 'center', gap: space.sm, paddingVertical: space.sm },
  code: { borderRadius: radius.sm, padding: space.md },
});
