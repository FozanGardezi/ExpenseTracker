/** What the API returns, screen by screen (see api/*.py). Text marked **like this** is bold. */

export type User = { id: string; email: string; name: string };
export type Option = { key: string; name: string };
export type Labelled = { key: string; label: string };
export type Stat = { label: string; value: string; help?: string | null };

/** A payment in a list. Tapping it opens the payment sheet by `id`. */
export type PaymentRow = {
  id: string;
  title: string;
  sub: string;
  amount: string;
  meta: string;
  money_in: boolean;
  category: string;
  day: string;
  day_label: string;
};

export type SyncJob = {
  running: boolean;
  source: string;
  done: number;
  total: number;
  message: string;
  error: string;
  added: number;
  started_at: string;
  finished_at: string | null;
};

export type HomeStatus = {
  first_name: string;
  gmail_connected: boolean;
  last_sync: string | null;
  status: string;
  steps: { label: string; done: boolean; target: 'settings' | 'accounts' | 'sync' }[];
  currency: string;
  sync: SyncJob | null;
};

export type SyncOptions = {
  sources: Option[];
  statement_sources: Option[];
  lookback: number[];
  default_days: number;
  years: number[];
};

export type Insight = {
  id: string;
  kind: 'limit' | 'place' | 'category';
  key: string;
  title: string;
  text: string;
  level: 'critical' | 'warning' | 'info';
  category: string;
};

export type LimitRow = {
  position: number;
  title: string;
  category: string;
  status: string;
  sub: string;
  amount: string;
  meta: string;
  share: number;
};

export type Overview = {
  months: Labelled[];
  month: string;
  labels: string[];
  for: string;
  currencies: string[];
  currency: string;
  slots: Record<string, number>;
  empty: boolean;
  hero?: { label: string; value: string; sub: string; notes: string[]; not_counted: string | null };
  budget?:
    | { set: false; title: string; hint: string | null }
    | {
        set: true;
        title: string;
        status: 'over' | 'heading over' | 'on track' | 'under';
        status_label: string;
        used: number;
        used_text: string;
        remaining: string;
        sentence: string;
        explanation: string[];
      }
    | null;
  limits?: LimitRow[];
  where?: {
    count: number;
    categories: { category: string; group: string; sub: string; amount: string; meta: string; value: number }[];
    donut: { group: string; value: number }[];
    top: string | null;
    top_share: string | null;
  };
  insights?: Insight[];
  insights_empty?: string;
  recent?: PaymentRow[];
};

export type Drill = {
  title: string;
  subtitle: string;
  currency: string;
  slots: Record<string, number>;
  rows: PaymentRow[];
  limit: { name: string; category: string; words: string[] } | null;
  suggested: number | null;
};

export type MonthBar = {
  month: string;
  label: string;
  year: number;
  total: number;
  total_text: string;
  budget: number | null;
  segments: { group: string; value: number }[];
};

export type Trends = {
  labels: string[];
  for: string;
  currencies: string[];
  currency: string;
  range: string;
  ranges: Labelled[];
  empty: boolean;
  slots: Record<string, number>;
  stats?: Stat[];
  chart?: MonthBar[];
  groups?: string[];
  rest?: string[];
  categories?: { category: string; now: string; usual: string; change: string; trend: number[] }[];
  months_table?: { month: string; spent: string; budget: string; left: string; received: string }[];
};

export type Places = {
  empty: boolean;
  period: number;
  periods: { key: number; label: string }[];
  sort?: 'spent' | 'often';
  currency?: string;
  slots?: Record<string, number>;
  span?: string;
  caption?: string;
  places?: {
    place: string;
    name: string;
    category: string;
    times: number;
    spent: string;
    each: string;
    trend: number[];
  }[];
  found?: { search: string; empty: boolean; text: string } | null;
};

export type BudgetPage = {
  currency: string;
  total: number | null;
  from: string;
  usual_month: string | null;
  limits: { name: string; category: string; words: string; amount: number; spent: string; usual: string }[];
  categories: string[];
  history: { from: string; total: string; limits: number }[];
  examples: { name: string; category: string; words: string; amount: string }[];
};

export type Payment = {
  item: string;
  title: string;
  amount: string;
  money_out: boolean;
  sentence: string;
  category: string;
  spent_for: string | null;
  note: string;
  counted: boolean;
  transfer: boolean;
  counted_label: string;
  typed: { amount: number; description: string; date: string; account: string } | null;
  options: { categories: string[]; labels: string[]; accounts: Option[] };
  details: { label: string; value: string }[];
};

export type ExpenseOptions = {
  currency: string;
  accounts: Option[];
  message_accounts: Option[];
  categories: string[];
  labels: string[];
};

export type Parsed =
  | { ok: false; account: string; reason: string }
  | {
      ok: true;
      account: string;
      direction: 'debit' | 'credit';
      amount: number;
      currency: string;
      description: string;
      date: string;
    };

export type Transactions = {
  empty: boolean;
  total: number;
  slots?: Record<string, number>;
  offset?: number;
  rows: PaymentRow[];
  caption?: string;
  period?: string;
  start?: string;
  end?: string;
  periods: string[];
  options?: { categories: string[]; sources: string[] };
};

export type Statements = {
  empty: boolean;
  currency: string;
  currencies: string[];
  bank: string;
  banks: Option[];
  slots: Record<string, number>;
  chart: MonthBar[];
  months: Labelled[];
  months_table: { month: string; spent: string; received: string; net: string; count: number }[];
  month: string;
  month_label: string;
  summary: Stat[];
  by_category: { category: string; group: string; value: number; amount: string }[];
  rows: PaymentRow[];
};

export type Transfers = {
  limit: number;
  limit_currency: string;
  periods: string[];
  empty: boolean;
  period?: string;
  slots?: Record<string, number>;
  summary?: Stat[];
  rows?: PaymentRow[];
};

export type Orders = {
  empty: boolean;
  periods: string[];
  services?: Option[];
  chosen?: string[];
  period?: string;
  currencies?: string[];
  currency?: string;
  nothing?: boolean;
  summary?: Stat[];
  chart?: MonthBar[];
  by_service?: { key: string; name: string; value: number; amount: string }[];
  top_merchants?: { merchant: string; service: string; orders: number; spent: string }[];
  orders?: (PaymentRow & { service: string })[];
  orders_total?: number;
};

export type Institution = {
  key: string;
  name: string;
  kind: string;
  kind_label: string;
  enabled: boolean;
  senders: string;
  subjects: string;
  currency: string;
  statements: boolean;
  alerts_query: string;
  statements_query: string | null;
};

export type Institutions = {
  tracked: Institution[];
  presets: { key: string; name: string; kind: string; kind_label: string }[];
  kinds: Labelled[];
};

export type StatementSettings = {
  empty: boolean;
  unread: { received: string; bank: string; subject: string; reason: string }[];
  settings: {
    key: string;
    name: string;
    statements: boolean;
    has_password: boolean;
    senders: string;
    subjects: string;
    senders_placeholder: string;
    query: string;
  }[];
  read: { bank: string; period: string; received: string; files: string; found: number; added: number }[];
};

export type ImportOptions = { countries: Option[]; services: Option[] };
export type CsvMapping = Record<'date' | 'amount' | 'merchant' | 'reference' | 'currency', string | null>;
export type CsvPreview = { columns: string[]; preview: Record<string, unknown>[]; mapping: CsvMapping; service: string };

export type Account = {
  user: { name: string; email: string };
  gmail: { connected: boolean; account: string | null; since: string | null };
  configured: boolean;
  reads_from: string[];
  consent: string;
  queries: { name: string; query: string }[];
};

export type Rule = {
  words: string;
  category_is: string;
  min_amount: number | null;
  max_amount: number | null;
  category: string;
  spent_for: string;
  matches?: number;
};

export type Rules = {
  rules: Rule[];
  categories: string[];
  labels: string[];
  my_categories: string[];
  examples: { words: string; set: string }[];
};

export type Skipped = {
  sources: string[];
  rows: { received: string; source: string; subject: string; sender: string; reason: string }[];
  total?: number;
};

export type PublicConfig = { configured: boolean; consent: string; privacy_url: string };
