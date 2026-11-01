/** The little Markdown the API's texts use: ### headings, - lists, **bold**, `code`, [links](https://...). */
import * as WebBrowser from 'expo-web-browser';
import { Text, View } from 'react-native';

import { T } from '@/components/ui';
import { space, useTheme } from '@/lib/theme';

function Inline({ text }: { text: string }) {
  const { colors } = useTheme();
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\(https:\/\/[^)\s]+\)|\*[^*]+\*)/g);
  return (
    <>
      {parts.map((part, i) => {
        if (part.startsWith('**')) return <Text key={i} style={{ fontWeight: '700' }}>{part.slice(2, -2)}</Text>;
        if (part.startsWith('`')) return <Text key={i} style={{ fontFamily: 'monospace', fontSize: 13 }}>{part.slice(1, -1)}</Text>;
        if (part.startsWith('*') && part.length > 2) return <Text key={i} style={{ fontStyle: 'italic' }}>{part.slice(1, -1)}</Text>;
        const link = part.match(/^\[([^\]]+)\]\((https:\/\/[^)\s]+)\)$/);
        if (link) {
          return (
            <Text key={i} accessibilityRole="link" style={{ color: colors.accent }} onPress={() => void WebBrowser.openBrowserAsync(link[2])}>
              {link[1]}
            </Text>
          );
        }
        return part;
      })}
    </>
  );
}

export function Markdown({ text }: { text: string }) {
  const blocks = text.trim().split(/\n\s*\n/);
  return (
    <View style={{ gap: space.md }}>
      {blocks.map((block, b) => {
        const lines = block.split('\n').map((l) => l.trim()).filter(Boolean);
        const out = [];
        if (lines[0]?.startsWith('### ')) {
          out.push(<T key="h" variant="heading">{lines.shift()!.slice(4)}</T>);
        }
        const items: string[] = [];
        const paragraph: string[] = [];
        for (const line of lines) {
          if (line.startsWith('- ')) items.push(line.slice(2));
          else if (items.length) items[items.length - 1] += ` ${line}`;
          else paragraph.push(line);
        }
        if (paragraph.length) out.push(<T key="p"><Inline text={paragraph.join(' ')} /></T>);
        if (items.length) {
          out.push(
            <View key="l" style={{ gap: 6 }}>
              {items.map((item, i) => (
                <View key={i} style={{ flexDirection: 'row', gap: 8, paddingRight: 8 }}>
                  <T>•</T>
                  <T style={{ flex: 1 }}><Inline text={item} /></T>
                </View>
              ))}
            </View>,
          );
        }
        return <View key={b} style={{ gap: space.sm }}>{out}</View>;
      })}
    </View>
  );
}
