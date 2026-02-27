import { Layout } from "./shared/components/Layout";
import { SignalFeed } from "./features/signals/components/SignalFeed";
import { SettingsPage } from "./features/settings/components/SettingsPage";

export default function App() {
  return <Layout feed={<SignalFeed />} settings={<SettingsPage />} />;
}
