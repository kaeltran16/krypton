import type { ReactNode } from "react";

type BadgeColor = "long" | "short" | "error" | "primary" | "tertiary" | "accent" | "muted";

interface BadgeProps {
  color: BadgeColor;
  border?: boolean;
  pill?: boolean;
  weight?: "medium" | "bold";
  children: ReactNode;
  "aria-label"?: string;
  className?: string;
}

const colorMap: Record<BadgeColor, { bg: string; text: string; border: string }> = {
  long:     { bg: "bg-long/15",                       text: "text-long",               border: "border-long/30" },
  short:    { bg: "bg-short/15",                      text: "text-short",              border: "border-short/30" },
  error:    { bg: "bg-error/15",                      text: "text-error",              border: "border-error/30" },
  primary:  { bg: "bg-primary/15",                    text: "text-primary",            border: "border-primary/30" },
  tertiary: { bg: "bg-tertiary-dim/15",               text: "text-tertiary-dim",       border: "border-tertiary-dim/30" },
  accent:   { bg: "bg-accent/15",                     text: "text-primary",            border: "border-accent/30" },
  muted:    { bg: "bg-surface-container-highest",     text: "text-on-surface-variant", border: "border-outline-variant/30" },
};

export function Badge({
  color,
  border = false,
  pill = false,
  weight = "bold",
  children,
  "aria-label": ariaLabel,
  className = "",
}: BadgeProps) {
  const c = colorMap[color];
  return (
    <span
      aria-label={ariaLabel}
      className={[
        "inline-flex items-center text-xs px-1.5 py-0.5",
        weight === "medium" ? "font-medium" : "font-bold",
        c.bg,
        c.text,
        pill ? "rounded-full" : "rounded",
        border ? `border ${c.border}` : "",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {children}
    </span>
  );
}
