import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { Loader2 } from "lucide-react";

type Variant = "primary" | "solid" | "secondary" | "ghost" | "danger" | "long" | "short";
type Size = "xs" | "sm" | "md" | "lg";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  pill?: boolean;
  loading?: boolean;
  icon?: ReactNode;
  children?: ReactNode;
}

const variantStyles: Record<Variant, string> = {
  primary:
    "bg-primary/15 text-primary border border-primary/30 hover:bg-primary/25",
  solid:
    "bg-primary-container text-on-primary-fixed hover:brightness-110",
  secondary:
    "bg-surface-container text-on-surface border border-outline-variant/10 hover:bg-surface-container-highest",
  ghost:
    "text-on-surface-variant hover:text-on-surface hover:bg-surface-container-highest",
  danger:
    "text-error hover:text-error/80 hover:bg-error/10",
  long:
    "bg-long text-on-tertiary-fixed hover:brightness-110",
  short:
    "bg-short text-white hover:brightness-110",
};

const sizeStyles: Record<Size, string> = {
  xs: "px-2 py-1 text-[10px] min-h-[28px] gap-1",
  sm: "px-3 py-1.5 text-xs min-h-[36px] gap-1.5",
  md: "px-4 py-2.5 text-sm min-h-[44px] gap-2",
  lg: "w-full py-3 text-sm min-h-[48px] gap-2",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      variant = "primary",
      size = "md",
      pill = false,
      loading = false,
      icon,
      children,
      disabled,
      className = "",
      ...props
    },
    ref,
  ) => {
    const isDisabled = disabled || loading;
    const iconOnly = icon && !children;

    return (
      <button
        ref={ref}
        disabled={isDisabled}
        className={[
          "inline-flex items-center justify-center font-medium",
          "transition-all duration-150 ease-out",
          "active:scale-[0.97]",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-1 focus-visible:ring-offset-surface",
          "disabled:opacity-40 disabled:pointer-events-none",
          variantStyles[variant],
          sizeStyles[size],
          pill ? "rounded-full" : "rounded-lg",
          iconOnly && size === "md" ? "!px-2.5" : "",
          iconOnly && size === "sm" ? "!px-2" : "",
          className,
        ]
          .filter(Boolean)
          .join(" ")}
        {...props}
      >
        {loading ? (
          <Loader2
            size={size === "xs" ? 12 : size === "sm" ? 14 : 16}
            className="animate-spin shrink-0"
          />
        ) : icon ? (
          <span className="shrink-0 flex items-center">{icon}</span>
        ) : null}
        {children && <span>{children}</span>}
      </button>
    );
  },
);

Button.displayName = "Button";
