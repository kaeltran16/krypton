import SourceBadge from "./SourceBadge";
import ParamInfoPopup from "./ParamInfoPopup";
import { ParamRow } from "../../../shared/components/ParamRow";

interface Props {
  name: string;
  value: unknown;
  source: "hardcoded" | "configurable";
  last?: boolean;
  descriptions?: Record<string, { description: string; pipeline_stage: string; range: string }>;
}

export default function ParameterRow({ name, value, source, last, descriptions }: Props) {
  const display = Array.isArray(value)
    ? value.join(", ")
    : typeof value === "object" && value !== null
      ? JSON.stringify(value)
      : String(value);

  return (
    <ParamRow
      label={
        <span className="flex items-center gap-1">
          <span>{name}</span>
          <ParamInfoPopup name={name} descriptions={descriptions} />
        </span>
      }
      value={
        <span className="flex items-center gap-2">
          <span>{display}</span>
          <SourceBadge source={source} />
        </span>
      }
      last={last}
    />
  );
}
