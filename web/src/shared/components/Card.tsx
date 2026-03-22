import type { ReactNode } from "react";

type Variant = "default" | "low" | "high" | "highest" | "lowest";
type Padding = "none" | "sm" | "md" | "lg";
type Accent = "primary" | "long" | "short" | "error" | "tertiary";

interface CardProps {
  children: ReactNode;
  variant?: Variant;
  padding?: Padding;
  accent?: Accent;
  border?: boolean;
  asSection?: boolean;
  className?: string;
}

const variantMap: Record<Variant, string> = {
  default: "bg-surface-container",
  low: "bg-surface-container-low",
  high: "bg-surface-container-high",
  highest: "bg-surface-container-highest",
  lowest: "bg-surface-container-lowest",
};

const paddingMap: Record<Padding, string> = {
  none: "",
  sm: "p-3",
  md: "p-4",
  lg: "p-5",
};

const accentMap: Record<Accent, string> = {
  primary: "border-l-primary",
  long: "border-l-long",
  short: "border-l-short",
  error: "border-l-error",
  tertiary: "border-l-tertiary-dim",
};

export function Card({
  children,
  variant = "default",
  padding = "md",
  accent,
  border = true,
  asSection = false,
  className = "",
}: CardProps) {
  const Tag = asSection ? "section" : "div";
  return (
    <Tag
      className={[
        variantMap[variant],
        "rounded-lg",
        border ? "border border-outline-variant/10" : "",
        paddingMap[padding],
        accent ? `border-l-2 ${accentMap[accent]}` : "",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {children}
    </Tag>
  );
}
