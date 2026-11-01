/**
 * Charts, drawn with SVG: where the money went (a donut), months side by side (stacked
 * columns you can tap), a category's last six months (mini bars), and amounts compared
 * (horizontal bars). Colors come from the caller, so a category keeps its color.
 */
import { useState } from 'react';
import { Platform, Pressable, ScrollView, StyleSheet, View, type LayoutChangeEvent } from 'react-native';
import Svg, { Circle, G, Line, Rect, Text as SvgText } from 'react-native-svg';

import { T } from '@/components/ui';
import { compact } from '@/lib/format';
import { space, useTheme } from '@/lib/theme';
import type { MonthBar } from '@/lib/types';

export function Donut({
  segments,
  label,
  value,
  size = 200,
}: {
  segments: { key: string; value: number; color: string }[];
  label?: string | null;
  value?: string | null;
  size?: number;
}) {
  const { colors } = useTheme();
  const stroke = size * 0.14;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const total = segments.reduce((sum, s) => sum + s.value, 0) || 1;
  const gap = segments.length > 1 ? 2.5 : 0;
  const starts = segments.map((_, i) => segments.slice(0, i).reduce((sum, s) => sum + (s.value / total) * c, 0));
  return (
    <View style={{ alignItems: 'center' }} accessibilityRole="image" accessibilityLabel={label && value ? `${label}: ${value}` : undefined}>
      <View style={{ width: size, height: size }}>
        <Svg width={size} height={size}>
          <G transform={`rotate(-90 ${size / 2} ${size / 2})`}>
            {segments.map((s, i) => {
              const length = (s.value / total) * c;
              return (
                <Circle
                  key={s.key}
                  cx={size / 2}
                  cy={size / 2}
                  r={r}
                  fill="none"
                  stroke={s.color}
                  strokeWidth={stroke}
                  strokeDasharray={`${Math.max(length - gap, 0.1)} ${c}`}
                  strokeDashoffset={-starts[i]}
                />
              );
            })}
          </G>
        </Svg>
        <View style={[StyleSheet.absoluteFill, { alignItems: 'center', justifyContent: 'center', padding: stroke + 8 }]}>
          {label ? (
            <T variant="small" muted numberOfLines={1}>
              {label}
            </T>
          ) : null}
          {value ? <T style={{ fontSize: 28, fontWeight: '700', color: colors.text }}>{value}</T> : null}
        </View>
      </View>
    </View>
  );
}

const SLOT = 44; // room for one month's column
const FONT = Platform.OS === 'web' ? 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif' : undefined;
const AXIS = 40;

/**
 * Monthly columns split into parts, biggest at the bottom, with the total on top and the
 * budget as a dashed line. Tapping part of a column calls onPress(month, group); tapping the
 * month's label calls onPress(month, null). The SVG only draws: taps go to Pressables laid
 * over each part, which work the same on phones and the web and can be read out.
 */
export function MonthBars({
  bars,
  colorOf,
  onPress,
  selected,
  height = 230,
}: {
  bars: MonthBar[];
  colorOf: (group: string) => string;
  onPress?: (month: string, group: string | null) => void;
  selected?: string | null;
  height?: number;
}) {
  const { colors } = useTheme();
  const [width, setWidth] = useState(0);
  const plotHeight = height - 36;
  const top = Math.max(...bars.map((b) => Math.max(b.total, b.budget ?? 0)), 1) * 1.15;
  const scale = (v: number) => (v / top) * (plotHeight - 18);
  const y = (v: number) => plotHeight - scale(v);
  const inner = Math.max(width - AXIS, bars.length * SLOT, 6 * SLOT);
  const slot = inner / Math.max(bars.length, 6);
  const start = bars.length < 6 ? ((6 - bars.length) * slot) / 2 : 0;
  const barWidth = Math.min(28, slot * 0.62);
  const biggest = bars.reduce((best, b) => (b.total > best.total ? b : best), bars[0]);
  const ticks = [top / 1.15 / 2, top / 1.15].map((v) => Math.round(v));
  // Each part's place, bottom up: [bar index, group, value, top y, height].
  const parts = bars.flatMap((bar, i) => {
    const tops = bar.segments.map((_, k) => plotHeight - bar.segments.slice(0, k + 1).reduce((sum, s) => sum + scale(s.value), 0));
    return bar.segments.map((segment, k) => ({ i, bar, segment, top: tops[k], h: scale(segment.value) }));
  });
  const xOf = (i: number) => start + i * slot + (slot - barWidth) / 2;

  const chart = (
    <View style={{ width: inner, height }}>
      <Svg width={inner} height={height}>
        {ticks.map((t) => (
          <Line key={t} x1={0} x2={inner} y1={y(t)} y2={y(t)} stroke={colors.grid} strokeWidth={1} />
        ))}
        <Line x1={0} x2={inner} y1={plotHeight} y2={plotHeight} stroke={colors.border} strokeWidth={1} />
        {parts.map(({ i, bar, segment, top: partTop, h }) => (
          <Rect
            key={`${bar.month}-${segment.group}`}
            x={xOf(i)}
            y={partTop}
            width={barWidth}
            height={Math.max(h - 1, 0.5)}
            rx={h > 6 ? 3 : 0}
            fill={colorOf(segment.group)}
            opacity={selected && selected !== bar.month ? 0.35 : 1}
          />
        ))}
        {bars.map((bar, i) => {
          const x = xOf(i);
          const labelled = bars.length <= 6 || bar === biggest || i === bars.length - 1;
          return (
            <G key={bar.month}>
              {labelled ? (
                <SvgText fontFamily={FONT} x={x + barWidth / 2} y={y(bar.total) - 5} fontSize={11} fill={colors.muted} textAnchor="middle">
                  {compact(bar.total)}
                </SvgText>
              ) : null}
              {bar.budget ? (
                <Line
                  x1={start + i * slot + 2}
                  x2={start + (i + 1) * slot - 2}
                  y1={y(bar.budget)}
                  y2={y(bar.budget)}
                  stroke={colors.text}
                  strokeWidth={1.5}
                  strokeDasharray="5 4"
                />
              ) : null}
              <SvgText fontFamily={FONT} x={x + barWidth / 2} y={plotHeight + 15} fontSize={11} fill={colors.muted} textAnchor="middle">
                {bar.label}
              </SvgText>
              {i === 0 || bar.label === 'Jan' ? (
                <SvgText fontFamily={FONT} x={x + barWidth / 2} y={plotHeight + 29} fontSize={10} fill={colors.muted} textAnchor="middle">
                  {String(bar.year)}
                </SvgText>
              ) : null}
            </G>
          );
        })}
      </Svg>
      {onPress ? (
        <>
          {parts.map(({ i, bar, segment, top: partTop, h }) => (
            <Pressable
              key={`tap-${bar.month}-${segment.group}`}
              accessibilityRole="button"
              accessibilityLabel={`${bar.label} ${bar.year}, ${segment.group}: ${compact(segment.value)}`}
              onPress={() => onPress(bar.month, segment.group)}
              style={{ position: 'absolute', left: xOf(i) - 4, top: partTop, width: barWidth + 8, height: Math.max(h, 6) }}
            />
          ))}
          {bars.map((bar, i) => (
            <Pressable
              key={`tap-${bar.month}`}
              accessibilityRole="button"
              accessibilityLabel={`${bar.label} ${bar.year}: ${bar.total_text}`}
              onPress={() => onPress(bar.month, null)}
              style={{ position: 'absolute', left: start + i * slot, top: plotHeight, width: slot, height: height - plotHeight }}
            />
          ))}
        </>
      ) : null}
    </View>
  );

  return (
    <View onLayout={(e: LayoutChangeEvent) => setWidth(e.nativeEvent.layout.width)} style={{ flexDirection: 'row' }}>
      <Svg width={AXIS} height={height}>
        {ticks.map((t) => (
          <SvgText fontFamily={FONT} key={t} x={AXIS - 6} y={y(t) + 4} fontSize={10} fill={colors.muted} textAnchor="end">
            {compact(t)}
          </SvgText>
        ))}
      </Svg>
      {width > 0 ? (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentOffset={{ x: Math.max(inner - (width - AXIS), 0), y: 0 }}>
          {chart}
        </ScrollView>
      ) : null}
    </View>
  );
}

/** A small key for MonthBars: each group's color and name. */
export function Legend({ items }: { items: { label: string; color: string }[] }) {
  return (
    <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.md }}>
      {items.map((item) => (
        <View key={item.label} style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
          <View style={{ width: 10, height: 10, borderRadius: 5, backgroundColor: item.color }} />
          <T variant="caption">{item.label}</T>
        </View>
      ))}
    </View>
  );
}

/** A category's or place's last six months, as tiny columns. */
export function Sparkbars({ values, color }: { values: number[]; color: string }) {
  const max = Math.max(...values, 1);
  return (
    <View style={{ flexDirection: 'row', alignItems: 'flex-end', gap: 2, height: 24 }} accessibilityElementsHidden>
      {values.map((v, i) => (
        <View
          key={i}
          style={{ width: 5, height: Math.max((v / max) * 24, v > 0 ? 2 : 1), borderRadius: 1.5, backgroundColor: v > 0 ? color : `${color}40` }}
        />
      ))}
    </View>
  );
}

/** Amounts side by side as bars, biggest first, each with its amount written at the end. */
export function HBars({
  items,
  onPress,
}: {
  items: { key: string; label: string; value: number; amount: string; color: string }[];
  onPress?: (key: string) => void;
}) {
  const max = Math.max(...items.map((i) => i.value), 1);
  return (
    <View style={{ gap: space.sm }}>
      {items.map((item) => (
        <Pressable key={item.key} disabled={!onPress} onPress={() => onPress?.(item.key)} style={{ gap: 4 }}>
          <View style={{ flexDirection: 'row', justifyContent: 'space-between', gap: space.sm }}>
            <T variant="small" numberOfLines={1} style={{ flex: 1 }}>
              {item.label}
            </T>
            <T variant="small" style={{ fontWeight: '600' }}>
              {item.amount}
            </T>
          </View>
          <View style={{ height: 10, borderRadius: 5, width: `${Math.max((item.value / max) * 100, 2)}%`, backgroundColor: item.color }} />
        </Pressable>
      ))}
    </View>
  );
}
