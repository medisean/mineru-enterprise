"use client";
/**
 * Dashboard layout — persistent sidebar with collapsible panel + recent tasks.
 * Shared across all /dashboard/* routes.
 */
import { useState, useEffect, useRef } from "react";
import { useRouter, usePathname } from "next/navigation";
import Link from "next/link";
import { useAuthStore } from "@/lib/auth-store";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { tasksApi } from "@/lib/api";
import { getWebSocketBaseUrl } from "@/lib/runtime-config";
import {
  LogOut, FileText, Plus, Loader2, PanelLeftClose, PanelLeftOpen,
  CheckCircle2, XCircle, Clock, AlertCircle, LayoutDashboard,
  Shield, Users, Clock4,
} from "lucide-react";
import { useT } from "@/lib/i18n/use-translation";

interface RecentTask {
  id: string;
  original_filename: string;
  status: string;
  progress: number;
  created_at: string;
}

const STATUS_DOT: Record<string, { color: string; icon: React.ReactNode }> = {
  pending: { color: "text-yellow-500", icon: <Clock className="h-3 w-3" /> },
  processing: { color: "text-blue-500", icon: <Loader2 className="h-3 w-3 animate-spin" /> },
  success: { color: "text-green-500", icon: <CheckCircle2 className="h-3 w-3" /> },
  failed: { color: "text-red-500", icon: <XCircle className="h-3 w-3" /> },
  cancelled: { color: "text-gray-400", icon: <AlertCircle className="h-3 w-3" /> },
};

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { user, accessToken, logout, hasHydrated } = useAuthStore();
  const router = useRouter();
  const pathname = usePathname();
  const queryClient = useQueryClient();
  const wsRefs = useRef<Map<string, WebSocket>>(new Map());
  const wsRetryRefs = useRef<Map<string, number>>(new Map()); // task_id -> retry count
  const t = useT();

  const [collapsed, setCollapsed] = useState(false);

  // ── All hooks MUST be called before any conditional return ──

  // Fetch recent tasks for sidebar (enabled only when authenticated)
  const { data: recentData } = useQuery({
    queryKey: ["recent-tasks"],
    queryFn: () =>
      tasksApi
        .list({ page: 1, page_size: 50 })
        .then((r: { data: { items: RecentTask[]; total: number } }) => r.data),
    enabled: !!accessToken,
    refetchInterval: 10000,
  });

  const recentTasks: RecentTask[] = recentData?.items ?? [];

  // WebSocket for active recent tasks (with exponential backoff reconnect)
  useEffect(() => {
    if (!accessToken) return;

    const activeTasks = recentTasks.filter(
      (t) => t.status === "pending" || t.status === "processing"
    );

    const connectWs = (task: RecentTask) => {
      if (wsRefs.current.has(task.id)) return; // already connected

      const token = localStorage.getItem("access_token");
      const wsUrl = `${getWebSocketBaseUrl()}/api/v1/ws/tasks/${task.id}?token=${token}`;
      const ws = new WebSocket(wsUrl);
      wsRefs.current.set(task.id, ws);

      ws.onmessage = () => {
        queryClient.invalidateQueries({ queryKey: ["recent-tasks"] });
      };

      ws.onclose = () => {
        wsRefs.current.delete(task.id);
        // Check if the task is still active before reconnecting
        const retryCount = wsRetryRefs.current.get(task.id) || 0;
        const maxRetries = 5;
        if (retryCount < maxRetries) {
          const delay = Math.min(1000 * Math.pow(2, retryCount), 30000); // 1s, 2s, 4s, 8s, 16s, max 30s
          wsRetryRefs.current.set(task.id, retryCount + 1);
          setTimeout(() => {
            // Only reconnect if the task still appears active
            const stillActive = recentTasks.find(
              (t) => t.id === task.id && (t.status === "pending" || t.status === "processing")
            );
            if (stillActive && !wsRefs.current.has(task.id)) {
              connectWs(task);
            }
          }, delay);
        }
      };

      ws.onerror = () => {
        // onclose will fire after onerror, which handles reconnect
      };
    };

    for (const task of activeTasks) {
      connectWs(task);
      // Reset retry count on successful connect attempt
      wsRetryRefs.current.delete(task.id);
    }

    // Clean up closed/completed task WS
    for (const [id, ws] of wsRefs.current) {
      const stillActive = recentTasks.find((t) => t.id === id && (t.status === "pending" || t.status === "processing"));
      if (!stillActive) {
        ws.close();
        wsRefs.current.delete(id);
        wsRetryRefs.current.delete(id);
      }
    }
  }, [recentTasks, queryClient, accessToken]);

  // Cleanup all WS on unmount
  useEffect(() => {
    return () => {
      for (const [, ws] of wsRefs.current) {
        ws.close();
      }
      wsRefs.current.clear();
      wsRetryRefs.current.clear();
    };
  }, []);

  // Auth guard — wait for Zustand persist hydration before deciding
  useEffect(() => {
    if (!hasHydrated) return; // still loading from localStorage
    if (!accessToken) {
      router.replace("/login");
    }
  }, [hasHydrated, accessToken, router]);

  // ── Conditional return AFTER all hooks ──

  // Not yet hydrated or no token → show loading spinner (will redirect via effect above)
  if (!hasHydrated || !accessToken) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
      </div>
    );
  }

  const handleLogout = () => {
    logout();
    router.push("/login");
  };

  const sidebarW = collapsed ? "w-14" : "w-56";
  const mainMl = collapsed ? "ml-14" : "ml-56";

  // Active nav detection
  const isTaskDetail = pathname.startsWith("/dashboard/tasks/");
  const isUpload = pathname === "/dashboard" && !pathname.includes("/tasks");
  const isTaskList = pathname === "/dashboard" && !isTaskDetail;

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Sidebar */}
      <aside
        className={`fixed inset-y-0 left-0 ${sidebarW} bg-white border-r border-gray-100 flex flex-col z-10 transition-all duration-200`}
      >
        {/* Header with collapse toggle */}
        <div className="p-3 border-b border-gray-100 flex items-center gap-2">
          {!collapsed && (
            <>
              <Link href="/dashboard" className="flex items-center gap-2 flex-1 min-w-0 group">
                <LayoutDashboard className="h-5 w-5 text-blue-600 flex-shrink-0" />
                <div className="min-w-0 flex-1">
                  <h1 className="text-base font-bold text-gray-900 truncate group-hover:text-blue-600 transition-colors">MinerU</h1>
                </div>
              </Link>
              <button
                onClick={() => setCollapsed((c) => !c)}
                className="p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-colors flex-shrink-0"
                title={t("sidebar.collapse")}
              >
                <PanelLeftClose className="h-4 w-4" />
              </button>
            </>
          )}
          {collapsed && (
            <div className="w-full flex flex-col items-center gap-1">
              <Link href="/dashboard" className="p-2.5 text-blue-600 hover:bg-blue-50 rounded-lg transition-colors" title="MinerU">
                <LayoutDashboard className="h-4 w-4" />
              </Link>
              <button
                onClick={() => setCollapsed((c) => !c)}
                className="w-full flex items-center justify-center p-2.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
                title={t("sidebar.expand")}
              >
                <PanelLeftOpen className="h-4 w-4" />
              </button>
            </div>
          )}
        </div>

        {/* Nav */}
        <nav className={`p-2 space-y-0.5 ${collapsed ? "px-1.5" : ""}`}>
          <NavItem
            icon={<Plus className="h-4 w-4" />}
            label={t("sidebar.newParse")}
            collapsed={collapsed}
            active={pathname === "/dashboard"}
            href="/dashboard"
          />
          <NavItem
            icon={<FileText className="h-4 w-4" />}
            label={t("sidebar.taskMgmt")}
            collapsed={collapsed}
            active={pathname.startsWith("/dashboard/tasks") && !isTaskDetail}
            href="/dashboard?tab=tasks"
          />
          {/* Admin section — only for admins */}
          {(user?.role === "admin" || user?.is_superuser) && (
            <>
              <div className={`pt-3 pb-1 ${collapsed ? "px-0 text-center" : "px-3"}`}>
                {!collapsed && <span className="text-[10px] font-medium text-gray-400 uppercase tracking-wider">{t("sidebar.admin")}</span>}
                {collapsed && <div className="h-px bg-gray-100 mx-1" />}
              </div>
              <NavItem
                icon={<Shield className="h-4 w-4" />}
                label={t("sidebar.adminDashboard")}
                collapsed={collapsed}
                active={pathname === "/dashboard/admin"}
                href="/dashboard/admin"
              />
              <NavItem
                icon={<Users className="h-4 w-4" />}
                label={t("sidebar.userMgmt")}
                collapsed={collapsed}
                active={pathname === "/dashboard/admin/users"}
                href="/dashboard/admin/users"
              />
              <NavItem
                icon={<Clock4 className="h-4 w-4" />}
                label={t("sidebar.taskHistory")}
                collapsed={collapsed}
                active={pathname === "/dashboard/admin/tasks"}
                href="/dashboard/admin/tasks"
              />
            </>
          )}
        </nav>

        {/* Recent tasks — only when expanded */}
        {!collapsed && (
          <div className="flex-1 min-h-0 flex flex-col border-t border-gray-100">
            <div className="px-4 pt-3 pb-1">
              <span className="text-xs font-medium text-gray-500">{t("sidebar.recentTasks")}</span>
            </div>
            <div className="flex-1 overflow-y-auto px-2 pb-2">
              {recentTasks.length === 0 ? (
                <p className="text-xs text-gray-300 text-center py-4">{t("sidebar.noTasks")}</p>
              ) : (
                <div className="space-y-1">
                  {recentTasks.map((task) => {
                    const dot = STATUS_DOT[task.status] || STATUS_DOT.pending;
                    return (
                      <Link
                        key={task.id}
                        href={`/dashboard/tasks/${task.id}`}
                        className={`flex items-start gap-2.5 px-2.5 py-2.5 rounded-lg hover:bg-gray-50 transition-colors group ${
                          isTaskDetail && pathname.endsWith(task.id) ? "bg-blue-50" : ""
                        }`}
                      >
                        <span className={`mt-0.5 flex-shrink-0 ${dot.color}`}>{dot.icon}</span>
                        <div className="flex-1 min-w-0">
                          <p className="text-sm text-gray-700 truncate group-hover:text-gray-900 transition-colors">
                            {task.original_filename}
                          </p>
                          {task.status === "processing" && (
                            <div className="mt-1.5 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                              <div
                                className="h-full bg-blue-400 rounded-full transition-all duration-500"
                                style={{ width: `${task.progress}%` }}
                              />
                            </div>
                          )}
                        </div>
                      </Link>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        )}

        {/* Collapsed: reserved space, no count shown */}
        {collapsed && (
          <div className="flex-1 min-h-0 border-t border-gray-100" />
        )}

        {/* Bottom: user info */}
        <div className="border-t border-gray-100">
          {!collapsed && (
            <div className="p-2">
              <div className="flex items-center gap-2.5 px-3 py-2 mb-1">
                <div className="h-7 w-7 rounded-full bg-blue-100 flex items-center justify-center text-xs font-medium text-blue-700 flex-shrink-0">
                  {user?.full_name?.[0] || user?.username?.[0] || "U"}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-medium truncate">{user?.full_name || user?.username}</p>
                  <p className="text-[10px] text-gray-400 truncate">{user?.email}</p>
                </div>
              </div>
              <button
                onClick={handleLogout}
                className="w-full flex items-center gap-2.5 px-3 py-2 text-sm text-gray-500 hover:text-gray-700 hover:bg-gray-50 rounded-lg transition-colors"
              >
                <LogOut className="h-4 w-4" />
                {t("sidebar.logout")}
              </button>
            </div>
          )}
          {collapsed && (
            <div className="p-2 flex flex-col items-center gap-1">
              <div
                className="h-7 w-7 rounded-full bg-blue-100 flex items-center justify-center text-xs font-medium text-blue-700 cursor-pointer"
                title={`${user?.full_name || user?.username} · ${user?.email}`}
              >
                {user?.full_name?.[0] || user?.username?.[0] || "U"}
              </div>
              <button
                onClick={handleLogout}
                className="p-1.5 text-gray-400 hover:text-gray-600 rounded transition-colors"
                title={t("sidebar.logout")}
              >
                <LogOut className="h-3.5 w-3.5" />
              </button>
            </div>
          )}
        </div>
      </aside>

      {/* Main content */}
      <main className={`${mainMl} transition-all duration-200 min-h-screen`}>
        {children}
      </main>
    </div>
  );
}

function NavItem({ icon, label, collapsed, active, href }: {
  icon: React.ReactNode;
  label: string;
  collapsed: boolean;
  active: boolean;
  href: string;
}) {
  if (collapsed) {
    return (
      <Link
        href={href}
        title={label}
        className={`w-full flex items-center justify-center p-2.5 rounded-lg transition-colors ${
          active ? "bg-blue-50 text-blue-700" : "text-gray-500 hover:bg-gray-50 hover:text-gray-700"
        }`}
      >
        {icon}
      </Link>
    );
  }

  return (
    <Link
      href={href}
      className={`w-full flex items-center gap-2.5 px-3 py-2 text-sm rounded-lg transition-colors ${
        active ? "bg-blue-50 text-blue-700 font-medium" : "text-gray-600 hover:bg-gray-50"
      }`}
    >
      {icon}
      <span className="flex-1 text-left">{label}</span>
    </Link>
  );
}
