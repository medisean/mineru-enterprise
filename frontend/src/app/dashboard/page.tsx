"use client";
/**
 * Main dashboard page with upload panel.
 * Sidebar + auth guard is in dashboard/layout.tsx — shared across all routes.
 */
import { useEffect } from "react";
import { useSearchParams } from "next/navigation";
import { useRouter } from "next/navigation";
import { Suspense } from "react";
import { CreatedTask, UploadPanel } from "@/components/upload/upload-panel";
import { useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useT } from "@/lib/i18n/use-translation";
import { LanguageToggle } from "@/components/ui/language-toggle";

interface TaskListCache {
  items: CreatedTask[];
  total: number;
  page?: number;
  page_size?: number;
}

function prependTask(cache: TaskListCache | undefined, task: CreatedTask): TaskListCache | undefined {
  if (!cache) return cache;
  const withoutDuplicate = cache.items.filter((item) => item.id !== task.id);
  return {
    ...cache,
    items: [task, ...withoutDuplicate].slice(0, cache.page_size ?? cache.items.length + 1),
    total: cache.items.some((item) => item.id === task.id) ? cache.total : cache.total + 1,
  };
}

function DashboardContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const queryClient = useQueryClient();
  const t = useT();

  useEffect(() => {
    if (searchParams.get("tab") === "tasks") {
      router.replace("/dashboard/tasks");
    }
  }, [router, searchParams]);

  const handleTaskCreated = (task: CreatedTask) => {
    queryClient.setQueriesData<TaskListCache>(
      { queryKey: ["recent-tasks"] },
      (cache) => prependTask(cache, task)
    );
    queryClient.setQueriesData<TaskListCache>(
      {
        queryKey: ["tasks"],
        predicate: ({ queryKey }) => {
          const [, page, , statusFilter, searchQuery, favoriteOnly] = queryKey;
          if (page !== 1 || favoriteOnly) return false;
          if (statusFilter && statusFilter !== task.status) return false;
          return !searchQuery || task.original_filename.toLowerCase().includes(String(searchQuery).toLowerCase());
        },
      },
      (cache) => prependTask(cache, task)
    );
    void Promise.all([
      queryClient.refetchQueries({ queryKey: ["recent-tasks"], type: "active" }),
      queryClient.refetchQueries({ queryKey: ["tasks"], type: "active" }),
    ]);
    router.push("/dashboard/tasks");
  };

  return (
    <div className="p-8">
      <LanguageToggle />
      <div className="max-w-5xl mx-auto">
        <h2 className="text-lg font-semibold text-gray-900 mb-1">{t("dashboard.uploadTitle")}</h2>
        <p className="text-sm text-gray-500 mb-6">
          {t("dashboard.uploadDesc")}
        </p>
        <div className="bg-white rounded-2xl border border-gray-100 p-6">
          <UploadPanel onTaskCreated={handleTaskCreated} />
        </div>
      </div>
    </div>
  );
}

export default function DashboardPage() {
  return (
    <Suspense fallback={<div className="flex items-center justify-center min-h-screen"><Loader2 className="h-6 w-6 animate-spin text-gray-400" /></div>}>
      <DashboardContent />
    </Suspense>
  );
}
