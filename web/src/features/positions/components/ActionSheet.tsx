import { useRef, useEffect, type ReactNode } from "react";
import { X } from "lucide-react";
import { Button } from "../../../shared/components/Button";

interface Props {
  title: string;
  onClose: () => void;
  children: ReactNode;
}

export function ActionSheet({ title, onClose, children }: Props) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    ref.current?.showModal();
  }, []);

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onClick={(e) => { if (e.target === ref.current) onClose(); }}
    >
      <div className="p-4 border-b border-outline-variant/10">
        <div className="flex items-center justify-between">
          <span className="text-lg font-headline font-bold">{title}</span>
          <Button variant="ghost" icon={<X size={20} />} onClick={onClose} aria-label="Close" />
        </div>
      </div>
      <div className="p-4 space-y-4">
        {children}
      </div>
    </dialog>
  );
}
