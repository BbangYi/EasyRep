export type TemperatureStop = { value: number; color: string };

export type TemperatureProfile = {
  range: [number, number];
  label: string;
  boundary: string;
  stops: TemperatureStop[];
};

function kstHour(at: string | null | undefined) {
  if (!at || !Number.isFinite(Date.parse(at))) return null;
  return Number(new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Seoul", hour: "2-digit", hourCycle: "h23",
  }).format(new Date(at)));
}

// Royal Veterinary College and RSPCA care guidance: cool daytime 22–25°C,
// a 26–28°C upper heat area, and a cooler night period. This is a display
// profile for the registered species; a future enclosure override may replace it.
export function temperatureProfile(species: string | undefined, at: string | null | undefined): TemperatureProfile | null {
  if (!/크레스티드\s*게코|crested\s*gecko/i.test(species ?? "")) return null;
  const hour = kstHour(at);
  const night = hour === null || hour < 8 || hour >= 20;
  return night ? {
    range: [18, 30],
    label: "야간 기준 20–22°C",
    boundary: "18°C 미만 · 28°C 초과 확인",
    stops: [
      { value: 18, color: "#3f99ae" },
      { value: 20, color: "#3a7956" },
      { value: 22, color: "#3a7956" },
      { value: 28, color: "#d39b49" },
      { value: 30, color: "#cf4c3d" },
    ],
  } : {
    range: [18, 30],
    label: "주간 일반 구역 22–25°C",
    boundary: "상부 열구역 26–28°C · 28°C 초과 확인",
    stops: [
      { value: 18, color: "#3f99ae" },
      { value: 22, color: "#3a7956" },
      { value: 25, color: "#3a7956" },
      { value: 28, color: "#d39b49" },
      { value: 30, color: "#cf4c3d" },
    ],
  };
}

export function temperatureColor(value: number, range: [number, number], stops?: TemperatureStop[]) {
  const palette = stops ?? [
    { value: range[0], color: "#3f99ae" },
    { value: (range[0] + range[1]) / 2, color: "#cab94c" },
    { value: range[1], color: "#cf4c3d" },
  ];
  const bounded = Math.max(range[0], Math.min(range[1], value));
  const end = palette.find(stop => stop.value >= bounded) ?? palette.at(-1)!;
  const start = [...palette].reverse().find(stop => stop.value <= bounded) ?? palette[0];
  const parse = (color: string) => color.slice(1).match(/../g)!.map(part => Number.parseInt(part, 16));
  const from = parse(start.color), to = parse(end.color);
  const ratio = start.value === end.value ? 0 : (bounded - start.value) / (end.value - start.value);
  return from.map((channel, index) => Math.round(channel + (to[index] - channel) * ratio)).join(',');
}

export function temperatureGradient(profile: TemperatureProfile) {
  const [low, high] = profile.range;
  return `linear-gradient(90deg, ${profile.stops.map(stop => `${stop.color} ${((stop.value - low) / (high - low) * 100).toFixed(2)}%`).join(', ')})`;
}
