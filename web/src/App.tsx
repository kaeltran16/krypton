import { useState } from "react";
import { Layout } from "./shared/components/Layout";
import { HomeView } from "./features/home/components/HomeView";
import { ChartView } from "./features/chart/components/ChartView";
import { SignalsView } from "./features/signals/components/SignalsView";
import { NewsView } from "./features/news/components/NewsView";
import { NewsAlertToast } from "./features/news/components/NewsAlertToast";
import { MorePage } from "./features/more/components/MorePage";
import { useSignalWebSocket } from "./features/signals/hooks/useSignalWebSocket";
import { useLivePrice } from "./shared/hooks/useLivePrice";
import { AVAILABLE_PAIRS } from "./shared/lib/constants";

export default function App() {
  const [selectedPair, setSelectedPair] = useState<string>(AVAILABLE_PAIRS[0]);
  useSignalWebSocket();
  const { price, change24h } = useLivePrice(selectedPair);

  return (
    <>
      <NewsAlertToast />
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
