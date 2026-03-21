import { useState, useEffect } from "react";
import { Layout } from "./shared/components/Layout";
import { HomeView } from "./features/home/components/HomeView";
import { ChartView } from "./features/chart/components/ChartView";
import { SignalsView } from "./features/signals/components/SignalsView";
import { NewsView } from "./features/news/components/NewsView";
import { NewsAlertToast } from "./features/news/components/NewsAlertToast";
import { AlertToast } from "./features/alerts/components/AlertToast";
import { MorePage } from "./features/more/components/MorePage";
import { useSignalWebSocket } from "./features/signals/hooks/useSignalWebSocket";
import { useLivePrice } from "./shared/hooks/useLivePrice";
import { AVAILABLE_PAIRS } from "./shared/lib/constants";
import { useSettingsStore } from "./features/settings/store";
import { useServiceWorker } from "./shared/hooks/useServiceWorker";
import { UpdateModal } from "./shared/components/UpdateModal";
import { useAuth } from "./features/auth/hooks/useAuth";
import { LoginScreen } from "./features/auth/components/LoginScreen";

export default function App() {
  const { isLoading, isAuthenticated, login } = useAuth();

  if (isLoading) {
    return (
      <div className="min-h-dvh flex items-center justify-center bg-[#0a0f14]">
        <div className="w-8 h-8 border-2 border-[#69daff] border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!isAuthenticated) {
    return <LoginScreen onLogin={login} />;
  }

  return <AuthenticatedApp />;
}

function AuthenticatedApp() {
  const [selectedPair, setSelectedPair] = useState<string>(AVAILABLE_PAIRS[0]);
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
        chart={<ChartView pair={selectedPair} />}
        signals={<SignalsView />}
        news={<NewsView />}
        more={<MorePage />}
        price={price}
        change24h={change24h}
        selectedPair={selectedPair}
        onPairChange={setSelectedPair}
      />
    </>
  );
}
