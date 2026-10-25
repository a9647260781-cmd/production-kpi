import { useCallback, useEffect, useState } from "react";

export function useResource<T>(loader: () => Promise<T>, dependencies: readonly unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const next = await loader();
      setData(next);
      return next;
    } catch (caught) {
      setError(caught instanceof Error ? caught : new Error("Неизвестная ошибка"));
      return null;
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, dependencies);

  useEffect(() => {
    void load();
  }, [load]);

  return { data, loading, error, reload: load, setData };
}

