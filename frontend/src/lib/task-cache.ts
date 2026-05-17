import type { QueryClient } from "@tanstack/react-query";

export interface CachedTask {
  id: string;
  original_filename: string;
  status: string;
  progress: number;
}

interface TaskListCache<T extends CachedTask = CachedTask> {
  items: T[];
  total: number;
  page_size?: number;
}

function upsertTask<T extends CachedTask>(
  cache: TaskListCache<T> | undefined,
  task: CachedTask,
  prependIfMissing = false
): TaskListCache<T> | undefined {
  if (!cache) return cache;

  const existingIndex = cache.items.findIndex((item) => item.id === task.id);
  if (existingIndex !== -1) {
    return {
      ...cache,
      items: cache.items.map((item) =>
        item.id === task.id ? ({ ...item, ...task } as T) : item
      ),
    };
  }

  if (!prependIfMissing) return cache;

  return {
    ...cache,
    items: [task as T, ...cache.items].slice(0, cache.page_size ?? cache.items.length + 1),
    total: cache.total + 1,
  };
}

export function syncTaskCaches(queryClient: QueryClient, task: CachedTask) {
  queryClient.setQueryData<CachedTask>(["task", task.id], (cache) =>
    cache ? { ...cache, ...task } : task
  );

  queryClient.setQueriesData<TaskListCache>(
    { queryKey: ["recent-tasks"] },
    (cache) => upsertTask(cache, task, true)
  );

  queryClient.setQueriesData<TaskListCache>(
    { queryKey: ["tasks"] },
    (cache) => upsertTask(cache, task)
  );
}

export function refetchTaskCollections(queryClient: QueryClient) {
  void queryClient.refetchQueries({ queryKey: ["recent-tasks"], type: "active" });
  void queryClient.refetchQueries({ queryKey: ["tasks"], type: "active" });
}
