import { Markdown } from '@/components/markdown';
import { Card, Loaded, Screen } from '@/components/ui';
import { useApi } from '@/lib/query';

export default function Privacy() {
  const privacy = useApi<{ markdown: string }>('/api/privacy');
  return (
    <Screen top={false}>
      <Loaded query={privacy}>
        {(data) => (
          <Card>
            <Markdown text={data.markdown} />
          </Card>
        )}
      </Loaded>
    </Screen>
  );
}
