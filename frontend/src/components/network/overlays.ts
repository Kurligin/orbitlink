export interface Overlays {
  labels: boolean;
  orbits: boolean;
  edges: boolean;
  route: boolean;
}

export const DEFAULT_OVERLAYS: Overlays = {
  // Подписи всех 40+ аппаратов разом на стандартном приближении читать
  // невозможно — по умолчанию подписан только выбранный аппарат и те, что
  // входят в текущий маршрут; галочка — осознанный переход в «показать все».
  // Наземные пункты и шлюз не подчиняются этому переключателю — они всегда
  // подписаны (см. Globe3D).
  labels: false,
  orbits: true,
  edges: true,
  route: true,
};

export const OVERLAY_LABELS: Record<keyof Overlays, string> = {
  labels: "Подписи аппаратов (все)",
  orbits: "Дуги орбит",
  edges: "Связи сети",
  route: "Выбранный маршрут",
};
