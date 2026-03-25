import { useRef, useEffect, useState, useCallback, type ReactNode } from "react";
import { X } from "lucide-react";
import { Button } from "../../../shared/components/Button";

interface Props {
  title: string;
  onClose: () => void;
  children: ReactNode;
}

export function ActionSheet({ title, onClose, children }: Props) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    dialogRef.current?.showModal();
    requestAnimationFrame(() => setVisible(true));
  }, []);

  const handleClose = useCallback(() => {
    setVisible(false);
    setTimeout(onClose, 200);
  }, [onClose]);

  return (
    <dialog
      ref={dialogRef}
      onClose={handleClose}
      onClick={(e) => { if (e.target === dialogRef.current) handleClose(); }}
      className="fixed inset-0 m-0 p-0 w-full max-w-full h-full max-h-full bg-transparent border-none flex items-end justify-center backdrop:bg-black/70 backdrop:backdrop-blur-sm backdrop:transition-opacity backdrop:duration-200"
    >
      <div
        className={`w-full max-w-md bg-surface-container-high rounded-t-xl transition-transform duration-200 ease-out ${
          visible ? "translate-y-0" : "translate-y-full"
        }`}
      >
        {/* Drag handle indicator */}
        <div className="flex justify-center pt-3 pb-1">
          <div className="w-8 h-1 rounded-full bg-outline-variant/40" />
        </div>

        <div className="px-4 pb-3 border-b border-outline-variant/10">
          <div className="flex items-center justify-between">
            <span className="text-lg font-headline font-bold">{title}</span>
            <Button variant="ghost" icon={<X size={20} />} onClick={handleClose} aria-label="Close" />
          </div>
        </div>

        <div className="p-4 space-y-4 safe-bottom">
          {children}
        </div>
      </div>
    </dialog>
  );
}
