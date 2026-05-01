"use client";
/**
 * Main dashboard page with upload and tasks tabs.
 * Sidebar + auth guard is in dashboard/layout.tsx — shared across all routes.
 */
import { useState, useEffect } from "react";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { UploadPanel } from "@/components/upload/upload-panel";
import { TaskList } from "@/components/tasks/task-list";
import { useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useT } from "@/lib/i18n/use-translation";
import { LanguageToggle } from "@/components/ui/language-toggle";

type Tab = "upload" | "tasks";

function DashboardContent() {
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const t = useT();

  const initialTab = (searchParams.get("tab") as Tab) || "upload";
  const [tab, setTab] = useState<Tab>(initialTab);

  useEffect(() => {
    const tabParam = searchParams.get("tab");
    if (tabParam === "tasks") {
      setTab("tasks");
    } else {
      // No tab param or "upload" → default to upload
      setTab("upload");
    }
  }, [searchParams]);

  const handleTaskCreated = (taskId: string) => {
    queryClient.invalidateQueries({ queryKey: ["tasks"] });
    queryClient.invalidateQueries({ queryKey: ["recent-tasks"] });
    setTab("tasks");
  };

  return (
    <div className="p-8">
      <LanguageToggle />
      {tab === "upload" ? (
        <div className="max-w-3xl mx-auto">
          <h2 className="text-lg font-semibold text-gray-900 mb-1">{t("dashboard.uploadTitle")}</h2>
          <p className="text-sm text-gray-500 mb-6">
            {t("dashboard.uploadDesc")}
          </p>
          <div className="bg-white rounded-2xl border border-gray-100 p-6">
            <UploadPanel onTaskCreated={handleTaskCreated} />
          </div>
        </div>
      ) : (
        <div className="max-w-5xl mx-auto">
          <TaskList />
        </div>
      )}
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
