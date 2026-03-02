import { Layout } from "./shared/components/Layout";
import { Dashboard } from "./features/dashboard/components/Dashboard";
import { ChartView } from "./features/chart/components/ChartView";
import { SignalFeed } from "./features/signals/components/SignalFeed";
import { SettingsPage } from "./features/settings/components/SettingsPage";

export default function App() {
  return (
    <Layout
      dashboard={<Dashboard />}
      chart={<ChartView />}
      signals={<SignalFeed />}
      settings={<SettingsPage />}
    />
  );
}
