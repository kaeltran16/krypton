import type { ReactNode } from "react";

interface EmptyStateProps {
  icon: ReactNode;
  title: string;
  subtitle: string;
}

export function EmptyState({ icon, title, subtitle }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center gap-3 mt-12 text-center">
      <div className="text-outline">{icon}</div>
      <p className="text-on-surface-variant text-sm">{title}</p>
      <p className="text-outline text-xs">{subtitle}</p>
    </div>
  );
}
