import { useState, useEffect, useCallback, useRef } from "react";
import { registerSW } from "virtual:pwa-register";

export function useServiceWorker() {
  const [updateAvailable, setUpdateAvailable] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const updateSWRef = useRef<((reloadPage?: boolean) => Promise<void>) | null>(null);
  const registered = useRef(false);

  useEffect(() => {
    if (registered.current) return;
    registered.current = true;

    const updateSW = registerSW({
      onNeedRefresh() {
        setUpdateAvailable(true);
      },
    });
    updateSWRef.current = updateSW;
  }, []);

  const applyUpdate = useCallback(() => {
    updateSWRef.current?.(true);
  }, []);

  const dismiss = useCallback(() => {
    setDismissed(true);
  }, []);

  return {
    showUpdateModal: updateAvailable && !dismissed,
    applyUpdate,
    dismiss,
  };
}
