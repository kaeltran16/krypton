import { useState, useEffect } from "react";
import { Layout } from "./shared/components/Layout";
import { HomeView } from "./features/home/components/HomeView";
import { AgentView } from "./features/agent/components/AgentView";
import { SignalsView } from "./features/signals/components/SignalsView";
import { PositionsView } from "./features/positions/components/PositionsView";
import { NewsAlertToast } from "./features/news/components/NewsAlertToast";
import { AlertToast } from "./features/alerts/components/AlertToast";
import { MorePage } from "./features/more/components/MorePage";
import { useSignalWebSocket } from "./features/signals/hooks/useSignalWebSocket";
import { useLivePrice } from "./shared/hooks/useLivePrice";
import { AVAILABLE_PAIRS } from "./shared/lib/constants";
import { useSettingsStore } from "./features/settings/store";
import { useServiceWorker } from "./shared/hooks/useServiceWorker";
import { UpdateModal } from "./shared/components/UpdateModal";
import { SignalDetail } from "./features/signals/components/SignalDetail";
import { useSignalStore } from "./features/signals/store";
import { useAuth } from "./features/auth/hooks/useAuth";
import { LoginScreen } from "./features/auth/components/LoginScreen";
import { SplashScreen } from "./shared/components/SplashScreen";

export default function App() {
  const { isLoading, isAuthenticated, login } = useAuth();
  const [showSplash, setShowSplash] = useState(true);

  if (showSplash) {
    return (
      <SplashScreen
        onFinished={isLoading ? undefined : () => setShowSplash(false)}
      />
    );
  }

  if (!isAuthenticated) {
    return <LoginScreen onLogin={login} />;
  }

  return <AuthenticatedApp />;
}

function AuthenticatedApp() {
  const [selectedPair, setSelectedPair] = useState<string>(AVAILABLE_PAIRS[0]);
  const selectedSignal = useSignalStore((s) => s.selectedSignal);
  const clearSelection = useSignalStore((s) => s.clearSelection);
  useSignalWebSocket();

  useEffect(() => {
    useSettingsStore.getState().fetchFromServer();
  }, []);
  const { price, change24h } = useLivePrice(selectedPair);
  const { showUpdateModal, applyUpdate, dismiss } = useServiceWorker();

  return (
    <>
      <NewsAlertToast />
      <AlertToast />
      {showUpdateModal && <UpdateModal onUpdate={applyUpdate} onDismiss={dismiss} />}
      <Layout
        home={<HomeView />}
        agent={<AgentView pair={selectedPair} />}
        signals={<SignalsView />}
        positions={<PositionsView />}
        more={<MorePage />}
        price={price}
        change24h={change24h}
        selectedPair={selectedPair}
        onPairChange={setSelectedPair}
      />
      <SignalDetail signal={selectedSignal} onClose={clearSelection} />
    </>
  );
}
