import { QueryClientProvider } from '@tanstack/react-query';
import { DarkTheme, DefaultTheme, Stack, ThemeProvider as NavigationTheme, useRouter } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';
import { Pressable, Text } from 'react-native';

import { ToastProvider } from '@/components/toast';
import { queryClient } from '@/lib/query';
import { SessionProvider, useSession } from '@/lib/session';
import { SyncProvider } from '@/lib/sync';
import { ThemeProvider, useTheme } from '@/lib/theme';

SplashScreen.preventAutoHideAsync();

export default function RootLayout() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <ToastProvider>
          <SessionProvider>
            <Navigation />
          </SessionProvider>
        </ToastProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}

function Done() {
  const router = useRouter();
  const { colors } = useTheme();
  return (
    <Pressable accessibilityRole="button" onPress={() => router.back()} hitSlop={12} style={{ paddingHorizontal: 12 }}>
      <Text style={{ color: colors.accent, fontSize: 16, fontWeight: '600' }}>Done</Text>
    </Pressable>
  );
}

function Navigation() {
  const { status } = useSession();
  const { colors, scheme } = useTheme();
  useEffect(() => {
    if (status !== 'loading') void SplashScreen.hideAsync();
  }, [status]);
  if (status === 'loading') return null;

  const signedIn = status === 'signed-in';
  const base = scheme === 'dark' ? DarkTheme : DefaultTheme;
  const navigationTheme = {
    ...base,
    colors: { ...base.colors, primary: colors.accent, background: colors.background, card: colors.card, text: colors.text, border: colors.border },
  };
  const sheet = (title: string) => ({
    presentation: 'modal' as const,
    headerShown: true,
    title,
    headerRight: () => <Done />,
    headerStyle: { backgroundColor: colors.card },
    contentStyle: { backgroundColor: colors.background },
  });
  const stack = (
    <NavigationTheme value={navigationTheme}>
      <StatusBar style={scheme === 'dark' ? 'light' : 'dark'} />
      <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: colors.background } }}>
        <Stack.Protected guard={signedIn}>
          <Stack.Screen name="(tabs)" />
          <Stack.Screen name="payment/[item]" options={sheet('Payment')} />
          <Stack.Screen name="drill" options={sheet('Payments')} />
          <Stack.Screen name="add-expense" options={sheet('Add an expense')} />
          <Stack.Screen name="sync-options" options={sheet('Sync options')} />
          <Stack.Screen name="bank/[key]" options={sheet('Bank or wallet')} />
        </Stack.Protected>
        <Stack.Protected guard={!signedIn}>
          <Stack.Screen name="sign-in" />
        </Stack.Protected>
        <Stack.Screen name="auth" />
        <Stack.Screen name="privacy" options={sheet('Privacy')} />
      </Stack>
    </NavigationTheme>
  );
  return signedIn ? <SyncProvider>{stack}</SyncProvider> : stack;
}
