import type { ReactNode } from "react";

interface SectionLabelProps {
  children: ReactNode;
  as?: "h2" | "h3" | "h4";
  color?: "default" | "primary";
  className?: string;
}

export function SectionLabel({ children, as: Tag = "h3", color = "default", className = "" }: SectionLabelProps) {
  const colorClass = color === "primary" ? "text-primary" : "text-on-surface-variant";
  return (
    <Tag
      className={`text-[10px] font-headline font-bold uppercase tracking-wider ${colorClass} px-1 mb-2 ${className}`}
    >
      {children}
    </Tag>
  );
}
