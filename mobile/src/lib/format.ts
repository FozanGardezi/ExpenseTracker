/** Numbers and dates for charts and pickers. Amounts in sentences come ready-written from the API. */

/** 1,284 / 12.9K / 4.2M: short enough for an axis or a column's cap. */
export function compact(value: number): string {
  const sizes: [number, string, number][] = [
    [1e9, 'B', 1e9],
    [1e6, 'M', 1e6],
    [1e4, 'K', 1e3],
  ];
  for (const [size, suffix, divisor] of sizes) {
    if (Math.abs(value) >= size) return `${(value / divisor).toFixed(1).replace(/\.0$/, '')}${suffix}`;
  }
  return Math.round(value).toLocaleString('en-US');
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
export const MONTH_NAMES = [
  'January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December',
];

/** "2026-10-05" as a local date (no time zone shift). */
export function parseDay(iso: string): Date {
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(y, m - 1, d);
}

export function isoDay(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

export function today(): string {
  return isoDay(new Date());
}

export function addDays(iso: string, days: number): string {
  const date = parseDay(iso);
  date.setDate(date.getDate() + days);
  return isoDay(date);
}

/** "Today", "Yesterday", or "Mon 5 Oct" (with the year if it isn't this year). */
export function dayName(iso: string): string {
  if (iso === today()) return 'Today';
  if (iso === addDays(today(), -1)) return 'Yesterday';
  const date = parseDay(iso);
  const year = date.getFullYear() === new Date().getFullYear() ? '' : ` ${date.getFullYear()}`;
  return `${DAYS[date.getDay()]} ${date.getDate()} ${MONTHS[date.getMonth()]}${year}`;
}
