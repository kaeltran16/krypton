import { useState, useEffect } from "react";
import { useAccount } from "../../dashboard/hooks/useAccount";
import { SegmentedControl } from "../../../shared/components/SegmentedControl";
import { OpenPositions } from "./OpenPositions";
import { HistorySegment } from "./HistorySegment";
import { useNavigationStore } from "../../../shared/stores/navigation";

type Segment = "open" | "history";

const SEGMENTS = [
  { value: "open" as Segment, label: "Open" },
  { value: "history" as Segment, label: "History" },
];

export function PositionsView() {
  const [segment, setSegment] = useState<Segment>("open");
  const { positions, loading, error, refresh } = useAccount();
  const positionTarget = useNavigationStore((s) => s.positionTarget);
  const clearPositionTarget = useNavigationStore((s) => s.clearPositionTarget);

  // Auto-switch to open segment and scroll when navigating from Home
  useEffect(() => {
    if (positionTarget) {
      setSegment("open");
      clearPositionTarget();
    }
  }, [positionTarget, clearPositionTarget]);

  return (
    <div className="flex flex-col gap-4 p-4">
      <SegmentedControl
        options={SEGMENTS}
        value={segment}
        onChange={setSegment}
        fullWidth
      />

      {segment === "open" ? (
        <OpenPositions
          positions={positions}
          loading={loading}
          error={error}
          onRefresh={refresh}
        />
      ) : (
        <HistorySegment />
      )}
    </div>
  );
}
