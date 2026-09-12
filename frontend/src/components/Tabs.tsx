export type TabId = "network" | "stability" | "compare" | "validate";

const TABS: Array<{ id: TabId; label: string; implemented: boolean }> = [
  { id: "network", label: "Сеть", implemented: true },
  { id: "stability", label: "Устойчивость", implemented: true },
  { id: "compare", label: "Сравнение", implemented: true },
  { id: "validate", label: "Проверка", implemented: true },
];

// Адресация экранов через якорь (#сеть, #устойчивость, #сравнение,
// #проверка) — свои ссылки на конкретный вид и рабочие «назад»/«вперёд».
export const TAB_HASHES: Record<TabId, string> = {
  network: "сеть",
  stability: "устойчивость",
  compare: "сравнение",
  validate: "проверка",
};

const HASH_TO_TAB = Object.fromEntries(
  (Object.entries(TAB_HASHES) as Array<[TabId, string]>).map(([tab, hash]) => [
    hash,
    tab,
  ]),
) as Record<string, TabId>;

export function tabFromHash(hash: string): TabId | null {
  const clean = decodeURIComponent(hash.replace(/^#/, "")).trim().toLowerCase();
  return HASH_TO_TAB[clean] ?? null;
}

interface TabsProps {
  active: TabId;
  onChange: (tab: TabId) => void;
}

export function Tabs({ active, onChange }: TabsProps) {
  return (
    <div className="tabs" role="tablist" aria-label="Экраны проекта">
      {TABS.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          aria-selected={tab.id === active}
          aria-current={tab.id === active ? "page" : undefined}
          onClick={() => onChange(tab.id)}
        >
          {tab.label}
          {!tab.implemented ? " · скоро" : ""}
        </button>
      ))}
    </div>
  );
}
