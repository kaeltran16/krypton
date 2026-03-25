import { useState, useRef, useEffect } from "react";
import { Pencil } from "lucide-react";
import SourceBadge from "./SourceBadge";
import ParamInfoPopup from "./ParamInfoPopup";
import { ParamRow } from "../../../shared/components/ParamRow";
import type { ParameterSource, ParamDescription } from "../types";

interface Props {
  name: string;
  value: unknown;
  source: ParameterSource;
  last?: boolean;
  descriptions?: Record<string, ParamDescription>;
  dotPath?: string;
  onEdit?: (dotPath: string, value: number) => void;
}

export default function ParameterRow({ name, value, source, last, descriptions, dotPath, onEdit }: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const submittedRef = useRef(false);
  const editable = source === "configurable" && !!dotPath && !!onEdit && typeof value === "number";

  useEffect(() => {
    if (editing) {
      submittedRef.current = false;
      inputRef.current?.focus();
    }
  }, [editing]);

  const display = Array.isArray(value)
    ? value.join(", ")
    : typeof value === "object" && value !== null
      ? JSON.stringify(value)
      : String(value);

  const handleSubmit = () => {
    if (submittedRef.current) return;
    submittedRef.current = true;
    const num = parseFloat(draft);
    if (!isNaN(num) && num !== value && dotPath && onEdit) {
      onEdit(dotPath, num);
    }
    setEditing(false);
  };

  return (
    <ParamRow
      label={
        <span className="flex items-center gap-1">
          <span>{name}</span>
          <ParamInfoPopup name={name} descriptions={descriptions} />
        </span>
      }
      value={
        editing ? (
          <input
            ref={inputRef}
            type="number"
            step="any"
            aria-label={`Edit ${name}`}
            className="w-24 bg-surface-container-high border border-primary/40 rounded px-1.5 py-0.5 text-xs font-mono text-on-surface text-right outline-none focus:border-primary"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={handleSubmit}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleSubmit();
              if (e.key === "Escape") { submittedRef.current = true; setEditing(false); }
            }}
          />
        ) : (
          <span
            className={`flex items-center gap-2 ${editable ? "cursor-pointer hover:text-primary transition-colors" : ""}`}
            onClick={editable ? () => { setDraft(String(value)); setEditing(true); } : undefined}
          >
            <span>{display}</span>
            <SourceBadge source={source} />
            {editable && <Pencil size={10} className="text-muted" />}
          </span>
        )
      }
      last={last}
    />
  );
}
