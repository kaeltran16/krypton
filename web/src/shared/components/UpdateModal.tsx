import { useRef, useEffect } from "react";

interface UpdateModalProps {
  onUpdate: () => void;
  onDismiss: () => void;
}

export function UpdateModal({ onUpdate, onDismiss }: UpdateModalProps) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    ref.current?.showModal();
  }, []);

  return (
    <dialog
      ref={ref}
      onClose={onDismiss}
      onClick={(e) => {
        if (e.target === ref.current) onDismiss();
      }}
      className="p-6"
    >
      <h2 className="text-foreground text-lg font-semibold mb-2">
        Update Available
      </h2>
      <p className="text-muted text-sm mb-6">
        A new version of Krypton is ready.
      </p>
      <div className="flex gap-3">
        <button
          onClick={onDismiss}
          className="flex-1 py-2.5 rounded-xl text-sm font-medium text-muted bg-surface border border-white/[0.06] active:scale-[0.97] transition-transform"
        >
          Later
        </button>
        <button
          onClick={onUpdate}
          className="flex-1 py-2.5 rounded-xl text-sm font-medium text-surface bg-accent active:scale-[0.97] transition-transform"
        >
          Update Now
        </button>
      </div>
    </dialog>
  );
}
