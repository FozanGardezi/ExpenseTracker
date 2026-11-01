/** Accounts → Import: history that isn't in Gmail, from your foodpanda account or a CSV file. */
import * as DocumentPicker from 'expo-document-picker';
import { useState } from 'react';
import { Platform, View } from 'react-native';

import { Button, Card, CardTitle, Expandable, Field, Loaded, Notice, Row, Segmented, Select, T, Toggle } from '@/components/ui';
import { api, messageOf, type Message } from '@/lib/api';
import { useAction, useApi } from '@/lib/query';
import { space } from '@/lib/theme';
import type { CsvMapping, CsvPreview, ImportOptions } from '@/lib/types';

type Picked = DocumentPicker.DocumentPickerAsset;

function fileForm(file: Picked): FormData {
  const form = new FormData();
  if (Platform.OS === 'web' && file.file) form.append('file', file.file, file.name);
  // React Native uploads a local file from its uri.
  else form.append('file', { uri: file.uri, name: file.name, type: file.mimeType ?? 'text/csv' } as unknown as Blob);
  return form;
}

export function ImportSection() {
  const options = useApi<ImportOptions>('/api/accounts/import/options');
  return (
    <Loaded query={options}>
      {(data) => (
        <View style={{ gap: space.lg }}>
          <Foodpanda options={data} />
          <Csv options={data} />
        </View>
      )}
    </Loaded>
  );
}

function Foodpanda({ options }: { options: ImportOptions }) {
  const [country, setCountry] = useState(options.countries[0]?.key ?? 'PK');
  const [token, setToken] = useState('');
  const [result, setResult] = useState<string | null>(null);
  const { run, busy } = useAction();
  return (
    <Card>
      <CardTitle title="Foodpanda account" />
      <T muted>Your full foodpanda order history, including orders whose emails you deleted.</T>
      <Expandable title="How to get your login token">
        <T>1. Log in at foodpanda.pk (or foodpanda.com.bd) in Chrome or Edge on a computer.</T>
        <T>2. Press F12, open Application → Cookies and select the foodpanda site.</T>
        <T>3. Copy the Value of the cookie named token and paste it below.</T>
        <T variant="caption">
          The token works like a password until it expires; the app uses it for this one fetch and doesn’t save it. This uses
          the unofficial endpoint behind foodpanda’s own Orders page, so it can stop working if foodpanda changes their site.
        </T>
      </Expandable>
      <Segmented options={options.countries.map((c) => ({ key: c.key, label: c.name }))} value={country} onChange={setCountry} />
      <Field label="Login token" value={token} onChangeText={setToken} secureTextEntry autoCapitalize="none" />
      <Button
        label="Fetch order history"
        kind="primary"
        busy={busy}
        disabled={!token.trim()}
        onPress={async () => {
          const done = await run(() => api.post<Message>('/api/accounts/import/foodpanda', { token, country }), { quiet: true });
          if (done) {
            setResult(done.message);
            setToken('');
          }
        }}
      />
      {result ? <Notice kind="success" text={result} /> : null}
    </Card>
  );
}

const FIELDS: { key: keyof CsvMapping; label: string }[] = [
  { key: 'date', label: 'Date column' },
  { key: 'amount', label: 'Amount column' },
  { key: 'merchant', label: 'Merchant / description column' },
  { key: 'reference', label: 'Order or booking ID column' },
  { key: 'currency', label: 'Currency column' },
];

function Csv({ options }: { options: ImportOptions }) {
  const [file, setFile] = useState<Picked | null>(null);
  const [preview, setPreview] = useState<CsvPreview | null>(null);
  const [service, setService] = useState(options.services[0]?.key ?? 'careem');
  const [mapping, setMapping] = useState<CsvMapping | null>(null);
  const [currency, setCurrency] = useState('PKR');
  const [dayfirst, setDayfirst] = useState(true);
  const [summary, setSummary] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { run, busy } = useAction();

  async function pick() {
    setError(null);
    const picked = await DocumentPicker.getDocumentAsync({ type: ['text/csv', 'text/comma-separated-values', 'application/vnd.ms-excel', '*/*'] });
    if (picked.canceled) return;
    const chosen = picked.assets[0];
    try {
      const result = await api.upload<CsvPreview>('/api/accounts/import/csv/preview', fileForm(chosen));
      setFile(chosen);
      setPreview(result);
      setService(result.service);
      setMapping(result.mapping);
      setSummary(null);
    } catch (e) {
      setError(messageOf(e));
    }
  }

  function form(dryRun: boolean): FormData {
    const data = fileForm(file!);
    data.append('service', service);
    data.append('mapping', JSON.stringify(mapping));
    data.append('currency', currency);
    data.append('dayfirst', String(dayfirst));
    data.append('dry_run', String(dryRun));
    return data;
  }

  async function check() {
    setError(null);
    try {
      setSummary((await api.upload<Message>('/api/accounts/import/csv', form(true))).message);
    } catch (e) {
      setError(messageOf(e));
    }
  }

  const columns = preview?.columns.map((c) => ({ key: c, label: c })) ?? [];
  return (
    <Card>
      <CardTitle title="CSV file" />
      <T muted>
        Order history a service lets you download, such as Careem’s (careem.com → My rides → History → Download a copy). It
        needs a date and an amount column; rows already tracked are skipped.
      </T>
      <Button label={file ? `Change file (${file.name})` : 'Choose a CSV file'} icon="upload_file" onPress={() => void pick()} />
      {error ? <Notice kind="error" text={error} /> : null}
      {preview && mapping ? (
        <>
          <Select label="Service" value={service} options={options.services.map((s) => ({ key: s.key, label: s.name }))} onChange={(s) => setService(s ?? service)} />
          <Field label="Currency when the file doesn't say" value={currency} onChangeText={setCurrency} autoCapitalize="characters" />
          {FIELDS.map((field) => (
            <Select
              key={field.key}
              label={field.label}
              value={mapping[field.key]}
              allowNone="(none)"
              options={columns}
              onChange={(column) => {
                setMapping({ ...mapping, [field.key]: column });
                setSummary(null);
              }}
            />
          ))}
          <Toggle label="Dates are day first (31/12/2025)" value={dayfirst} onChange={setDayfirst} />
          {summary ? <Notice text={summary} /> : null}
          <Row wrap>
            <Button label="Check" disabled={!mapping.date || !mapping.amount} onPress={() => void check()} />
            <Button
              label="Import"
              kind="primary"
              busy={busy}
              disabled={!mapping.date || !mapping.amount}
              onPress={async () => {
                if (await run(() => api.upload('/api/accounts/import/csv', form(false)))) {
                  setFile(null);
                  setPreview(null);
                }
              }}
            />
          </Row>
        </>
      ) : null}
    </Card>
  );
}
