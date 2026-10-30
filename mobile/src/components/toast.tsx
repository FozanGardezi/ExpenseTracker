/** Short messages that confirm a change ("Saved.") or say what went wrong, then fade away. */
import { createContext, useCallback, useContext, useRef, useState, type PropsWithChildren } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import Animated, { FadeInDown, FadeOutDown } from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useTheme } from '@/lib/theme';

type Kind = 'info' | 'error';
type Toast = { id: number; text: string; kind: Kind };
const ToastContext = createContext<{ show: (text: string, kind?: Kind) => void } | null>(null);

export function ToastProvider({ children }: PropsWithChildren) {
  const [toast, setToast] = useState<Toast | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const show = useCallback((text: string, kind: Kind = 'info') => {
    if (timer.current) clearTimeout(timer.current);
    setToast({ id: Date.now(), text, kind });
    timer.current = setTimeout(() => setToast(null), kind === 'error' ? 6000 : 3500);
  }, []);
  return (
    <ToastContext.Provider value={{ show }}>
      {children}
      {toast && (
        <View pointerEvents="box-none" style={[styles.host, { bottom: insets.bottom + 90 }]}>
          <Animated.View key={toast.id} entering={FadeInDown} exiting={FadeOutDown}>
            <Pressable
              accessibilityRole="alert"
              onPress={() => setToast(null)}
              style={[styles.toast, { backgroundColor: toast.kind === 'error' ? colors.critical : colors.text }]}>
              <Text style={[styles.text, { color: colors.background }]}>{toast.text}</Text>
            </Pressable>
          </Animated.View>
        </View>
      )}
    </ToastContext.Provider>
  );
}

export function useToast() {
  const toast = useContext(ToastContext);
  if (!toast) throw new Error('useToast outside ToastProvider');
  return toast;
}

const styles = StyleSheet.create({
  host: { position: 'absolute', left: 16, right: 16, alignItems: 'center' },
  toast: { borderRadius: 14, paddingVertical: 12, paddingHorizontal: 16, maxWidth: 520 },
  text: { fontSize: 15, fontWeight: '600' },
});
