"use client";
/**
 * Main dashboard page with upload, tasks, and settings tabs.
 * Includes auth guard — redirects to /login if not authenticated.
 */
import { useState, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { UploadPanel } from "@/components/upload/upload-panel";
import { TaskList } from "@/components/tasks/task-list";
import { useAuthStore } from "@/lib/auth-store";
import { useQueryClient } from "@tanstack/react-query";
import {
  LogOut, FileText, Plus, Loader2,
} from "lucide-react";

type Tab = "upload" | "tasks";

function DashboardContent() {
  const { user, accessToken, logout } = useAuthStore();
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();

  const initialTab = (searchParams.get("tab") as Tab) || "upload";
  const [tab, setTab] = useState<Tab>(initialTab);
  const [authChecked, setAuthChecked] = useState(false);

  useEffect(() => {
    if (!accessToken) {
      router.replace("/login");
    } else {
      setAuthChecked(true);
    }
  }, [accessToken, router]);

  useEffect(() => {
    const tabParam = searchParams.get("tab") as Tab;
    if (tabParam === "tasks" || tabParam === "upload") {
      setTab(tabParam);
    }
  }, [searchParams]);

  const handleLogout = () => {
    logout();
    router.push("/login");
  };

  const handleTaskCreated = (taskId: string) => {
    queryClient.invalidateQueries({ queryKey: ["tasks"] });
    setTab("tasks");
  };

  if (!authChecked) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Sidebar */}
      <aside className="fixed inset-y-0 left-0 w-56 bg-white border-r border-gray-100 flex flex-col z-10">
        <div className="p-5 border-b border-gray-100">
          <h1 className="text-base font-semibold text-gray-900">MinerU Enterprise</h1>
          <p className="text-xs text-gray-400 mt-0.5">企业文档解析平台</p>
        </div>

        <nav className="flex-1 p-3 space-y-1">
          <NavItem
            icon={<Plus className="h-4 w-4" />}
            label="新解析"
            active={tab === "upload"}
            onClick={() => setTab("upload")}
          />
          <NavItem
            icon={<FileText className="h-4 w-4" />}
            label="任务管理"
            active={tab === "tasks"}
            onClick={() => setTab("tasks")}
          />
        </nav>

        <div className="p-3 border-t border-gray-100">
          <div className="flex items-center gap-2.5 px-3 py-2 mb-1">
            <div className="h-7 w-7 rounded-full bg-blue-100 flex items-center justify-center text-xs font-medium text-blue-700">
              {user?.full_name?.[0] || user?.username?.[0] || "U"}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-xs font-medium truncate">{user?.full_name || user?.username}</p>
              <p className="text-xs text-gray-400 truncate">{user?.email}</p>
            </div>
          </div>
          <button
            onClick={handleLogout}
            className="w-full flex items-center gap-2.5 px-3 py-2 text-sm text-gray-500 hover:text-gray-700 hover:bg-gray-50 rounded-lg transition-colors"
          >
            <LogOut className="h-4 w-4" />
            退出登录
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="ml-56 p-8">
        <div className="max-w-3xl mx-auto">
          {tab === "upload" ? (
            <div>
              <h2 className="text-lg font-semibold text-gray-900 mb-1">上传文档</h2>
              <p className="text-sm text-gray-500 mb-6">
                支持 PDF/DOC/DOCX/PPT/PPTX/XLSX/图片/HTML，解析为 Markdown、JSON、DOCX、HTML 或 LaTeX
              </p>
              <div className="bg-white rounded-2xl border border-gray-100 p-6">
                <UploadPanel onTaskCreated={handleTaskCreated} />
              </div>
            </div>
          ) : (
            <div>
              <h2 className="text-lg font-semibold text-gray-900 mb-1">解析任务</h2>
              <p className="text-sm text-gray-500 mb-6">查看所有文档解析任务的状态与结果</p>
              <TaskList />
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

function NavItem({ icon, label, active, onClick, badge }: {
  icon: React.ReactNode;
  label: string;
  active: boolean;
  onClick: () => void;
  badge?: string;
}) {
  return (
    <button
      onClick={onClick}
      className={`w-full flex items-center gap-2.5 px-3 py-2 text-sm rounded-lg transition-colors ${
        active ? "bg-blue-50 text-blue-700 font-medium" : "text-gray-600 hover:bg-gray-50"
      }`}
    >
      {icon}
      <span className="flex-1 text-left">{label}</span>
      {badge && (
        <span className="text-[10px] text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded">{badge}</span>
      )}
    </button>
  );
}

export default function DashboardPage() {
  return (
    <Suspense fallback={<div className="flex items-center justify-center min-h-screen"><Loader2 className="h-6 w-6 animate-spin text-gray-400" /></div>}>
      <DashboardContent />
    </Suspense>
  );
}
