/**
 * Welcome: what the app reads from Gmail, a tick that the user allows it, then Continue
 * with Google. Nothing is shared before the tick.
 */
import { useRouter } from 'expo-router';
import { useState } from 'react';
import { View } from 'react-native';

import { Icon } from '@/components/icon';
import { Markdown } from '@/components/markdown';
import { Button, Card, Loaded, Notice, Screen, T, Toggle } from '@/components/ui';
import { API_URL } from '@/lib/api';
import { useApi } from '@/lib/query';
import { useSession } from '@/lib/session';
import { space, useTheme, wash } from '@/lib/theme';
import type { PublicConfig } from '@/lib/types';

export default function SignIn() {
  const { colors } = useTheme();
  const router = useRouter();
  const { signIn } = useSession();
  const config = useApi<PublicConfig>('/api/config');
  const [agree, setAgree] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function go() {
    setBusy(true);
    setMessage(null);
    const result = await signIn();
    setBusy(false);
    if (!result.ok) setMessage(result.message);
    // Signed in: the navigator moves on to Home by itself.
  }

  return (
    <Screen>
      <View style={{ alignItems: 'center', gap: space.md, paddingTop: space.xl }}>
        <View style={{ width: 72, height: 72, borderRadius: 22, backgroundColor: wash(colors.accent, 0.18), alignItems: 'center', justifyContent: 'center' }}>
          <Icon name="receipt_long" size={38} color={colors.accent} />
        </View>
        <T variant="title">Expense Tracker</T>
        <T muted style={{ textAlign: 'center' }}>
          Track your spending automatically from the emails your banks, wallets and delivery apps send you, instead of
          entering it by hand.
        </T>
      </View>
      <Loaded query={config}>
        {(data) =>
          data.configured ? (
            <Card>
              <T variant="heading">Before you continue</T>
              <Markdown text={data.consent} />
              <Toggle label="I've read this and allow the app read-only access to my Gmail" value={agree} onChange={setAgree} />
              {message ? <Notice kind="warning" text={message} /> : null}
              <Button label="Continue with Google" kind="primary" icon="mail" disabled={!agree} busy={busy} onPress={go} wide />
              <T variant="caption">
                Google will ask you to share your name, email address and read-only access to your Gmail. If you’ve allowed
                this before, it won’t ask again, and this phone stays signed in.
              </T>
            </Card>
          ) : (
            <Notice
              kind="warning"
              text={`The server at ${API_URL} isn't registered with Google yet. Whoever runs it needs to set the Google client (see the README).`}
            />
          )
        }
      </Loaded>
      <Button label="Privacy" kind="ghost" icon="shield" onPress={() => router.push('/privacy')} />
    </Screen>
  );
}
