/**
 * Where Google sign-in comes back to (expensetracker://auth?code=...). The sign-in screen
 * already has the answer by then; in the browser this page hands it back to the window
 * that opened Google, and closes. Anyone who lands here is sent on: Home when signed in,
 * the sign-in screen otherwise (Home would only send them back here).
 */
import { Redirect } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';

import { useSession } from '@/lib/session';

WebBrowser.maybeCompleteAuthSession();

export default function AuthReturn() {
  const { status } = useSession();
  return <Redirect href={status === 'signed-in' ? '/' : '/sign-in'} />;
}
