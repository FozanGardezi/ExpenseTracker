/**
 * Small values kept on the device: the session token in the Keychain (iOS) or Keystore
 * (Android) through expo-secure-store; in the browser, which has neither, localStorage.
 */
import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

const web = Platform.OS === 'web';

export const storage = {
  async get(key: string): Promise<string | null> {
    if (web) {
      try {
        return globalThis.localStorage?.getItem(key) ?? null;
      } catch {
        return null;
      }
    }
    return SecureStore.getItemAsync(key);
  },
  async set(key: string, value: string): Promise<void> {
    if (web) {
      try {
        globalThis.localStorage?.setItem(key, value);
      } catch {
        // private browsing: the value just isn't remembered
      }
      return;
    }
    await SecureStore.setItemAsync(key, value);
  },
  async remove(key: string): Promise<void> {
    if (web) {
      try {
        globalThis.localStorage?.removeItem(key);
      } catch {
        // nothing to remove
      }
      return;
    }
    await SecureStore.deleteItemAsync(key);
  },
};
