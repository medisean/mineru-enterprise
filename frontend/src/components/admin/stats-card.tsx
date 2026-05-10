"use client";

import { LucideIcon } from "lucide-react";

interface StatsCardProps {
  title: string;
  value: string | number;
  icon: LucideIcon;
  color: string;
}

export default function StatsCard({ title, value, icon: Icon, color }: StatsCardProps) {
  const colorMap: Record<string, { bg: string; text: string; iconBg: string }> = {
    blue: { bg: "bg-blue-50", text: "text-blue-700", iconBg: "bg-blue-100" },
    green: { bg: "bg-emerald-50", text: "text-emerald-700", iconBg: "bg-emerald-100" },
    amber: { bg: "bg-amber-50", text: "text-amber-700", iconBg: "bg-amber-100" },
    purple: { bg: "bg-purple-50", text: "text-purple-700", iconBg: "bg-purple-100" },
  };
  const c = colorMap[color] || colorMap.blue;

  return (
    <div className={`${c.bg} rounded-xl p-5`}>
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">{title}</p>
          <p className={`text-2xl font-semibold mt-1 ${c.text}`}>{value}</p>
        </div>
        <div className={`${c.iconBg} p-3 rounded-lg`}>
          <Icon className={`w-5 h-5 ${c.text}`} />
        </div>
      </div>
    </div>
  );
}
