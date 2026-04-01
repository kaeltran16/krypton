import { useEffect, useRef, useState, useCallback } from "react";
import { WS_BASE_URL } from "../../../shared/lib/constants";
import { api } from "../../../shared/lib/api";
import type { MLTrainJob, MLTrainProgress, MLTrainingWSEvent } from "../../../shared/lib/api";

export type LossEntry = { epoch: number; train_loss: number; val_loss: number | null };

interface UseMLTrainingSocketReturn {
  status: MLTrainJob["status"] | null;
  progress: Record<string, MLTrainProgress>;
  lossHistory: Record<string, LossEntry[]>;
  error: string | null;
  connected: boolean;
}

const MAX_WS_RETRIES = 5;
const POLL_INTERVAL_MS = 3000;

export function useMLTrainingSocket(jobId: string | null): UseMLTrainingSocketReturn {
  const [status, setStatus] = useState<MLTrainJob["status"] | null>(null);
  const [progress, setProgress] = useState<Record<string, MLTrainProgress>>({});
  const [lossHistory, setLossHistory] = useState<Record<string, LossEntry[]>>({});
  const [error, setError] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const retriesRef = useRef(0);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const cancelledRef = useRef(false);

  const stopPolling = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
  }, []);

  const startPolling = useCallback(
    (jid: string) => {
      stopPolling();
      setError("Live updates unavailable — refreshing every 3s");
      pollingRef.current = setInterval(async () => {
        try {
          const job = await api.getMLTrainingStatus(jid);
          const prog = (job.progress ?? {}) as Record<string, MLTrainProgress>;
          setProgress(prog);
          setLossHistory((prev) => {
            const next = { ...prev };
            let changed = false;
            for (const [pair, p] of Object.entries(prog)) {
              const existing = next[pair] || [];
              const lastEpoch = existing.length > 0 ? existing[existing.length - 1].epoch : 0;
              if (p.epoch > lastEpoch) {
                next[pair] = [...existing, { epoch: p.epoch, train_loss: p.train_loss, val_loss: p.val_loss }];
                changed = true;
              }
            }
            return changed ? next : prev;
          });
          if (job.status !== "running") {
            setStatus(job.status);
            stopPolling();
          }
        } catch {
          /* ignore, will retry */
        }
      }, POLL_INTERVAL_MS);
    },
    [stopPolling],
  );

  useEffect(() => {
    if (!jobId) {
      setStatus(null);
      setProgress({});
      setLossHistory({});
      setError(null);
      setConnected(false);
      return;
    }

    const currentJobId = jobId;
    cancelledRef.current = false;
    retriesRef.current = 0;

    function handleEvent(data: MLTrainingWSEvent) {
      switch (data.type) {
        case "snapshot":
          setConnected(true);
          setError(null);
          retriesRef.current = 0;
          if (data.progress) setProgress(data.progress as Record<string, MLTrainProgress>);
          if (data.loss_history) setLossHistory(data.loss_history);
          setStatus(data.status || "running");
          break;
        case "epoch_update":
          if (data.pair) {
            setProgress((prev) => ({
              ...prev,
              [data.pair!]: {
                epoch: data.epoch!,
                total_epochs: data.total_epochs!,
                train_loss: data.train_loss!,
                val_loss: data.val_loss!,
                direction_acc: data.direction_acc ?? undefined,
              },
            }));
            setLossHistory((prev) => {
              const existing = prev[data.pair!] || [];
              if (existing.length > 0 && existing[existing.length - 1].epoch >= data.epoch!) return prev;
              return {
                ...prev,
                [data.pair!]: [...existing, { epoch: data.epoch!, train_loss: data.train_loss!, val_loss: data.val_loss ?? null }],
              };
            });
          }
          break;
        case "job_completed":
          setStatus("completed");
          break;
        case "job_failed":
          setStatus("failed");
          setError(data.error || "Training failed");
          break;
      }
    }

    async function connect() {
      if (cancelledRef.current) return;
      try {
        const { token } = await api.getWSToken();
        if (cancelledRef.current) return;

        const ws = new WebSocket(`${WS_BASE_URL}/ws/ml-training/${currentJobId}`);
        wsRef.current = ws;

        ws.onopen = () => {
          ws.send(JSON.stringify({ type: "auth", token }));
        };

        ws.onmessage = (event) => {
          try {
            handleEvent(JSON.parse(event.data));
          } catch { /* ignore malformed */ }
        };

        ws.onclose = () => {
          setConnected(false);
          if (cancelledRef.current) return;
          if (retriesRef.current < MAX_WS_RETRIES) {
            const delay = Math.min(1000 * 2 ** retriesRef.current, 16000);
            retriesRef.current++;
            setTimeout(connect, delay);
          } else {
            startPolling(currentJobId);
          }
        };

        ws.onerror = () => {
          ws.close();
        };
      } catch {
        if (cancelledRef.current) return;
        if (retriesRef.current < 3) {
          const delay = 2000 * 2 ** retriesRef.current;
          retriesRef.current++;
          setTimeout(connect, delay);
        } else {
          startPolling(currentJobId);
        }
      }
    }

    connect();

    return () => {
      cancelledRef.current = true;
      wsRef.current?.close();
      wsRef.current = null;
      stopPolling();
    };
  }, [jobId, startPolling, stopPolling]);

  return { status, progress, lossHistory, error, connected };
}
