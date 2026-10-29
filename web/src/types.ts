export interface Pokemon {
  id: string;
  species: string;
  dex: number;
  level: number | null;
  types: string[];
  nature: string | null;
  ability: string | null;
  game: string;
  shiny: boolean;
  trainer: string | null;
  summary?: string;
  legal?: boolean | null;
  home_tracker?: string;
}
export interface Box {
  kind?: "bank";
  id: number;
  name: string;
  slots: (Pokemon | null)[];
}
export type Page = "dashboard" | "boxes" | "trading" | "history" | "esp32" | "settings";
export function pageFromHash(): Page {
  const page = window.location.hash.slice(1);
  return ["dashboard", "boxes", "trading", "history", "esp32", "settings"].includes(page)
    ? (page as Page)
    : "dashboard";
}
export function matches(p: Pokemon, query: string, type: string) {
  return (
    (!query.trim() ||
      `${p.species} ${p.dex} ${p.game} ${p.nature} ${p.ability}`
        .toLowerCase()
        .includes(query.trim().toLowerCase())) &&
    (!type || p.types.includes(type) || p.game === type)
  );
}

export const GENERATED_PIKACHU_ID = "generated-pikachu";
export function isGeneratedPikachu(id: string) {
  return id === GENERATED_PIKACHU_ID || /^dummy-pikachu-(0[1-9]|[12][0-9]|30)$/.test(id);
}
