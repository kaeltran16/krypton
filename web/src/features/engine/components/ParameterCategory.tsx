import { useState } from "react";
import ParameterRow from "./ParameterRow";
import type { ParameterSource, ParamDescription } from "../types";

type Variant = "hero" | "standard" | "sub";

const VARIANT_STYLES: Record<Variant, { container: string; header: string; indent: string }> = {
  hero: {
    container: "border-l-2 border-primary bg-surface-container",
    header: "text-on-surface font-semibold",
    indent: "",
  },
  standard: {
    container: "border border-outline-variant/50 bg-surface-container-low",
    header: "text-on-surface font-medium",
    indent: "",
  },
  sub: {
    container: "border border-outline-variant/30 bg-surface-container/30",
    header: "text-on-surface-variant text-sm",
    indent: "ml-2",
  },
};

interface Props {
  title: string;
  variant?: Variant;
  defaultOpen?: boolean;
  children?: React.ReactNode;
  params?: Record<string, { value: unknown; source: ParameterSource }>;
  descriptions?: Record<string, ParamDescription>;
  onEdit?: (dotPath: string, value: number) => void;
  dotPathPrefix?: string;
}

export default function ParameterCategory({
  title,
  variant = "standard",
  defaultOpen = false,
  children,
  params,
  descriptions,
  onEdit,
  dotPathPrefix,
}: Props) {
  const [open, setOpen] = useState(defaultOpen);
  const styles = VARIANT_STYLES[variant];
  const entries = params ? Object.entries(params) : [];

  return (
    <div className={`rounded-lg overflow-hidden ${styles.indent} ${styles.container}`}>
      <button
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className={`w-full flex items-center justify-between px-3 py-3 hover:bg-surface-container-high/30 transition-colors text-sm ${styles.header}`}
      >
        <span>{title}</span>
        <span className="text-on-surface-variant text-xs">{open ? "\u2212" : "+"}</span>
      </button>
      <div
        className={`grid transition-all duration-200 ${open ? "grid-rows-[1fr]" : "grid-rows-[0fr]"}`}
      >
        <div className="overflow-hidden">
          {params &&
            entries.map(([key, param], i) => (
              <ParameterRow
                key={key}
                name={key}
                value={param.value}
                source={param.source}
                descriptions={descriptions}
                dotPath={dotPathPrefix ? `${dotPathPrefix}.${key}` : undefined}
                onEdit={onEdit}
                last={i === entries.length - 1 && !children}
              />
            ))}
          {children}
        </div>
      </div>
    </div>
  );
}
