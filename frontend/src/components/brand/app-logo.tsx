"use client";

import { LayoutDashboard } from "lucide-react";

interface AppLogoProps {
  className?: string;
  iconClassName?: string;
}

export function AppLogo({ className = "h-5 w-5", iconClassName = "h-full w-full" }: AppLogoProps) {
  return (
    <span className={`inline-flex items-center justify-center text-blue-600 ${className}`}>
      <LayoutDashboard className={iconClassName} aria-hidden="true" strokeWidth={2.25} />
    </span>
  );
}
