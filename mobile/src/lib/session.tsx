/**
 * Who is signed in, and Continue with Google.
 *
 * Google's consent screen opens in the system browser (Google doesn't allow it in a web
 * view). The server handles Google's answer and sends the browser back to the app with a
 * one-time code, which the app swaps for a session token. The swap needs a secret
 * (`verifier`) the app made up before starting and never sent anywhere but the server's
 * exchange, so a code caught by another app is useless (PKCE, see api/auth_routes.py).
 */
import * as Crypto from 'expo-crypto';
import * as Linking from 'expo-linking';
import * as WebBrowser from 'expo-web-browser';
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type PropsWithChildren } from 'react';

import { api, ApiError, onSignedOut, setToken, url } from '@/lib/api';
import { queryClient } from '@/lib/query';
import { storage } from '@/lib/storage';
import type { User } from '@/lib/types';

const TOKEN = 'session_token';
const USER = 'session_user';

/** How Gmail access stands after coming back from Google. */
export type GmailAnswer = 'allowed' | 'confirm' | 'not_allowed';
export type SignInResult = { ok: true; gmail: GmailAnswer } | { ok: false; message: string | null };

type SessionState = {
  status: 'loading' | 'signed-out' | 'signed-in';
  user: User | null;
  signIn: (options?: { gmail?: boolean }) => Promise<SignInResult>;
  signOut: () => Promise<void>;
};

const SessionContext = createContext<SessionState | null>(null);

function hex(bytes: Uint8Array): string {
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

function base64url(base64: string): string {
  return base64.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

export function SessionProvider({ children }: PropsWithChildren) {
  const [status, setStatus] = useState<SessionState['status']>('loading');
  const [user, setUser] = useState<User | null>(null);

  const forget = useCallback(async () => {
    setToken(null);
    setUser(null);
    setStatus('signed-out');
    queryClient.clear();
    await Promise.all([storage.remove(TOKEN), storage.remove(USER)]);
  }, []);

  useEffect(() => {
    (async () => {
      const [token, saved] = await Promise.all([storage.get(TOKEN), storage.get(USER)]);
      if (token && saved) {
        setToken(token);
        setUser(JSON.parse(saved) as User);
        setStatus('signed-in');
      } else {
        setStatus('signed-out');
      }
    })();
  }, []);

  useEffect(() => {
    onSignedOut(() => void forget());
    return () => onSignedOut(null);
  }, [forget]);

  const signIn = useCallback(
    async ({ gmail = false } = {}): Promise<SignInResult> => {
      const verifier = hex(Crypto.getRandomBytes(32));
      const digest = await Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256, verifier, {
        encoding: Crypto.CryptoEncoding.BASE64,
      });
      const returnTo = Linking.createURL('auth');
      const start = url('/auth/google/start', {
        return_to: returnTo,
        challenge: base64url(digest),
        gmail: gmail ? 'true' : undefined,
        login_hint: gmail ? user?.email : undefined,
      });
      const result = await WebBrowser.openAuthSessionAsync(start, returnTo);
      if (result.type !== 'success') return { ok: false, message: null }; // closed the browser
      const params = Linking.parse(result.url).queryParams ?? {};
      if (params.error === 'cancelled') {
        return { ok: false, message: "You didn't continue with Google, so nothing was shared with the app." };
      }
      if (params.error || typeof params.code !== 'string') {
        return { ok: false, message: "Google sign-in didn't complete. Please try again." };
      }
      try {
        const signedIn = await api.post<{ token: string; user: User }>('/auth/exchange', {
          code: params.code,
          verifier,
        });
        const previous = await storage.get(TOKEN);
        setToken(signedIn.token);
        await Promise.all([storage.set(TOKEN, signedIn.token), storage.set(USER, JSON.stringify(signedIn.user))]);
        if (previous && previous !== signedIn.token) {
          // Renewing Gmail access signs in afresh; the old session isn't needed any more.
          void fetch(url('/auth/sign-out'), { method: 'POST', headers: { Authorization: `Bearer ${previous}` } });
        }
        setUser(signedIn.user);
        setStatus('signed-in');
        void queryClient.invalidateQueries();
        return { ok: true, gmail: (params.gmail as GmailAnswer) ?? 'not_allowed' };
      } catch (error) {
        return { ok: false, message: error instanceof ApiError ? error.message : 'Sign-in failed. Please try again.' };
      }
    },
    [user],
  );

  const signOut = useCallback(async () => {
    try {
      await api.post('/auth/sign-out');
    } catch {
      // signed out here either way
    }
    await forget();
  }, [forget]);

  const value = useMemo(() => ({ status, user, signIn, signOut }), [status, user, signIn, signOut]);
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionState {
  const session = useContext(SessionContext);
  if (!session) throw new Error('useSession outside SessionProvider');
  return session;
}
