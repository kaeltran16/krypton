import type { ComponentProps } from "react";
import type { Badge } from "../components/Badge";

type BadgeColor = ComponentProps<typeof Badge>["color"];

export const OUTCOME_COLOR: Record<string, BadgeColor> = {
  TP1_HIT:   "long",
  TP2_HIT:   "long",
  TP1_TRAIL: "long",
  TP1_TP2:   "long",
  SL_HIT:    "short",
  EXPIRED:   "muted",
};

export const OUTCOME_LABEL: Record<string, string> = {
  TP1_HIT:   "TP1 Hit",
  TP2_HIT:   "TP2 Hit",
  TP1_TRAIL: "TP1 + Trail",
  TP1_TP2:   "TP1 + TP2",
  SL_HIT:    "SL Hit",
  EXPIRED:   "Expired",
};

export const OUTCOME_BADGE: Record<string, { label: string; color: BadgeColor }> = {
  PENDING:   { label: "PENDING",   color: "accent" },
  TP1_HIT:   { label: "TP1",       color: "long" },
  TP2_HIT:   { label: "TP2",       color: "long" },
  TP1_TRAIL: { label: "TP1+Trail", color: "long" },
  TP1_TP2:   { label: "TP1+TP2",   color: "long" },
  SL_HIT:    { label: "SL",        color: "short" },
  EXPIRED:   { label: "EXP",       color: "muted" },
};
