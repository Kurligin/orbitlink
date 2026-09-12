import { useEffect, useState } from "react";
import { Tabs, TAB_HASHES, tabFromHash, type TabId } from "./components/Tabs";
import { NetworkScreen } from "./components/network/NetworkScreen";
import { StabilityScreen } from "./components/stability/StabilityScreen";
import { CompareScreen } from "./components/compare/CompareScreen";
import { SelftestScreen } from "./components/selftest/SelftestScreen";
import { WorkspaceProvider } from "./store/workspace";

const DEFAULT_TAB: TabId = "network";

export function App() {
  const [activeTab, setActiveTab] = useState<TabId>(
    () => tabFromHash(window.location.hash) ?? DEFAULT_TAB,
  );

  // Якорь — источник истины для текущего экрана: ссылка на конкретный вид
  // работает при открытии, а «назад»/«вперёд» браузера просто меняют якорь,
  // что мы здесь и слушаем. Без внешнего роутера — только hashchange.
  useEffect(() => {
    const onHashChange = () => {
      setActiveTab(tabFromHash(window.location.hash) ?? DEFAULT_TAB);
    };
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const changeTab = (tab: TabId) => {
    setActiveTab(tab);
    const hash = `#${TAB_HASHES[tab]}`;
    if (window.location.hash !== hash) {
      window.location.hash = hash;
    }
  };

  return (
    <WorkspaceProvider>
      <div className="app-shell">
        <Tabs active={activeTab} onChange={changeTab} />
        {activeTab === "network" && <NetworkScreen />}
        {activeTab === "stability" && <StabilityScreen />}
        {activeTab === "compare" && <CompareScreen />}
        {activeTab === "validate" && <SelftestScreen />}
      </div>
    </WorkspaceProvider>
  );
}
