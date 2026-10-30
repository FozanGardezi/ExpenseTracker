/**
 * The app's look: a teal accent on calm surfaces, in light and dark, the same colors as
 * the website. Charts use a fixed palette: a category keeps its color slot (0-4, from the
 * API) everywhere, and the rest share the gray as "Everything else".
 */
import { createContext, useContext, useEffect, useMemo, useState, type PropsWithChildren } from 'react';
import { useColorScheme } from 'react-native';

import { storage } from '@/lib/storage';

export const palettes = {
  light: {
    background: '#f3f6f5',
    card: '#ffffff',
    element: '#e7eeec',
    text: '#13201d',
    muted: '#5c6a67',
    border: '#d6dfdc',
    line: 'rgba(16,32,29,0.09)',
    accent: '#0b7d74',
    onAccent: '#ffffff',
    good: '#0b8a0b',
    warning: '#b77d00',
    critical: '#d03b3b',
    slots: ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4'],
    neutral: '#898781',
    grid: '#e1e0d9',
    services: { foodpanda: '#2a78d6', careem: '#eb6834', indrive: '#1baf7a', kravemart: '#eda100' },
  },
  dark: {
    background: '#0e1514',
    card: '#172120',
    element: '#1d2827',
    text: '#e7efed',
    muted: '#9aa9a6',
    border: '#26332f',
    line: 'rgba(255,255,255,0.07)',
    accent: '#74d9cd',
    onAccent: '#0e1514',
    good: '#3fc23f',
    warning: '#fab219',
    critical: '#ef6464',
    slots: ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181'],
    neutral: '#898781',
    grid: '#2c2c2a',
    services: { foodpanda: '#3987e5', careem: '#d95926', indrive: '#199e70', kravemart: '#c98500' },
  },
};

export type Palette = (typeof palettes)['light'];
export type ThemeChoice = 'system' | 'light' | 'dark';

type ThemeState = { colors: Palette; scheme: 'light' | 'dark'; choice: ThemeChoice; setChoice: (c: ThemeChoice) => void };

const ThemeContext = createContext<ThemeState | null>(null);
const KEY = 'theme';

export function ThemeProvider({ children }: PropsWithChildren) {
  const system = useColorScheme();
  const [choice, setChoiceState] = useState<ThemeChoice>('system');
  useEffect(() => {
    storage.get(KEY).then((saved) => {
      if (saved === 'light' || saved === 'dark') setChoiceState(saved);
    });
  }, []);
  const value = useMemo<ThemeState>(() => {
    const scheme = choice === 'system' ? (system === 'dark' ? 'dark' : 'light') : choice;
    return {
      colors: palettes[scheme],
      scheme,
      choice,
      setChoice: (next) => {
        setChoiceState(next);
        void storage.set(KEY, next);
      },
    };
  }, [choice, system]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeState {
  const theme = useContext(ThemeContext);
  if (!theme) throw new Error('useTheme outside ThemeProvider');
  return theme;
}

/** A category's color: its slot, or the shared gray. */
export function slotColor(colors: Palette, slots: Record<string, number>, category: string): string {
  const slot = slots[category];
  return slot === undefined ? colors.neutral : colors.slots[slot];
}

/** A pale wash of a color, for icon backgrounds and meter tracks. */
export function wash(color: string, alpha = 0.16): string {
  if (!color.startsWith('#') || color.length !== 7) return color;
  const a = Math.round(alpha * 255).toString(16).padStart(2, '0');
  return `${color}${a}`;
}

export const space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 } as const;
export const radius = { sm: 10, md: 14, lg: 20, pill: 999 } as const;
