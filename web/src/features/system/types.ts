export interface ServiceStatus {
  status: "up" | "down";
  latency_ms: number | null;
}

export interface OkxWsStatus {
  status: "up" | "down";
  connected_pairs: number;
}

export interface SystemHealthResponse {
  status: "healthy" | "degraded" | "unhealthy";
  timestamp: string;
  services: {
    redis: ServiceStatus;
    postgres: ServiceStatus;
    okx_ws: OkxWsStatus;
  };
  pipeline: {
    signals_today: number;
    last_cycle_seconds_ago: number | null;
    active_pairs: number;
    candle_buffer: Record<string, number>;
  };
  resources: {
    memory_mb: number | null;
    db_pool_active: number;
    db_pool_size: number;
    ws_clients: number;
    uptime_seconds: number;
  };
  freshness: {
    technicals_seconds_ago: number | null;
    order_flow_seconds_ago: number | null;
    onchain_seconds_ago: number | null;
    ml_models_loaded: number;
  };
}

export interface MLHealthResponse {
  ml_health: {
    ensemble: {
      pairs_loaded: number;
      members_loaded: number;
      members_stale: number;
      oldest_member_days: number;
    };
    regime_classifier: {
      active: boolean;
      age_days: number | null;
      fallback: boolean;
    };
  };
}
