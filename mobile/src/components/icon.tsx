/**
 * Icons: SF Symbols on iOS, Material Symbols on Android and the web (the same Material
 * names the website uses), through expo-symbols.
 */
import { SymbolView } from 'expo-symbols';
import type { AndroidSymbol } from 'expo-symbols';
import type { SFSymbol } from 'sf-symbols-typescript';
import type { StyleProp, ViewStyle } from 'react-native';

const ICONS = {
  restaurant: 'fork.knife',
  shopping_basket: 'basket',
  local_taxi: 'car',
  delivery_dining: 'bicycle',
  local_gas_station: 'fuelpump',
  bolt: 'bolt',
  wifi: 'wifi',
  subscriptions: 'play.rectangle.on.rectangle',
  shopping_bag: 'bag',
  medical_services: 'cross.case',
  school: 'graduationcap',
  atm: 'banknote',
  receipt_long: 'doc.text',
  swap_horiz: 'arrow.left.arrow.right',
  payments: 'dollarsign.circle',
  undo: 'arrow.uturn.backward',
  category: 'square.grid.2x2',
  more_horiz: 'ellipsis',
  sell: 'tag',
  home: 'house',
  account_balance: 'building.columns',
  settings: 'gearshape',
  add: 'plus',
  sync: 'arrow.triangle.2.circlepath',
  tune: 'slider.horizontal.3',
  check_circle: 'checkmark.circle.fill',
  radio_button_unchecked: 'circle',
  warning: 'exclamationmark.triangle',
  trending_up: 'chart.line.uptrend.xyaxis',
  arrow_back: 'chevron.left',
  chevron_right: 'chevron.right',
  search: 'magnifyingglass',
  filter_list: 'line.3.horizontal.decrease',
  delete: 'trash',
  close: 'xmark',
  shield: 'shield',
  logout: 'rectangle.portrait.and.arrow.right',
  mail: 'envelope',
  lock: 'lock',
  upload_file: 'doc.badge.plus',
  list: 'list.bullet',
  edit: 'pencil',
  expand_more: 'chevron.down',
  expand_less: 'chevron.up',
  ios_share: 'square.and.arrow.up',
  calendar_month: 'calendar',
  info: 'info.circle',
  error: 'exclamationmark.circle',
  check: 'checkmark',
  chevron_left: 'chevron.left',
} as const satisfies Record<string, SFSymbol>;

export type IconName = keyof typeof ICONS;

/** The website's icon for each category; the user's own categories get a tag. */
const CATEGORY_ICONS: Record<string, IconName> = {
  Food: 'restaurant',
  Groceries: 'shopping_basket',
  Ride: 'local_taxi',
  Delivery: 'delivery_dining',
  Fuel: 'local_gas_station',
  'Bills & utilities': 'bolt',
  'Mobile & internet': 'wifi',
  Subscriptions: 'subscriptions',
  Shopping: 'shopping_bag',
  Health: 'medical_services',
  Education: 'school',
  'Cash withdrawal': 'atm',
  'Fees & charges': 'receipt_long',
  Transfers: 'swap_horiz',
  Income: 'payments',
  Refunds: 'undo',
  Other: 'category',
  'Everything else': 'more_horiz',
};

export function categoryIcon(category: string): IconName {
  return CATEGORY_ICONS[category] ?? 'sell';
}

export function Icon({
  name,
  size = 22,
  color,
  style,
}: {
  name: IconName;
  size?: number;
  color: string;
  style?: StyleProp<ViewStyle>;
}) {
  return (
    <SymbolView
      name={{ ios: ICONS[name], android: name as AndroidSymbol, web: name as AndroidSymbol }}
      size={size}
      tintColor={color}
      style={style}
    />
  );
}
