import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import App from "./App";
import type { Box, Pokemon } from "./types";
const pikachu: Pokemon = {
  id: "demo-25",
  species: "Pikachu",
  dex: 25,
  level: 28,
  types: ["Electric"],
  nature: "Jolly",
  ability: "Static",
  game: "Sword / Shield",
  trainer: "DEMO",
  shiny: true,
};
const boxes: Box[] = [
  { id: 1, name: "Arrival box", slots: [pikachu, ...Array(29).fill(null)] },
  { id: 2, name: "Empty box", slots: Array(30).fill(null) },
];
beforeEach(() => {
  window.location.hash = "#boxes";
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation(async (path: string) => ({
      ok: true,
      json: async () =>
        path === "/api/health"
          ? { mode: "demo", pkhex_available: false }
          : boxes,
    })),
  );
});
it("shows exactly 30 slots, opens details, filters and changes boxes", async () => {
  const user = userEvent.setup();
  render(<App />);
  const pokemon = await screen.findByRole("button", { name: /View Pikachu/ });
  expect(screen.getAllByLabelText(/Empty slot/)).toHaveLength(29);
  await user.click(pokemon);
  const dialog = screen.getByRole("dialog");
  expect(within(dialog).getByText("Static")).toBeInTheDocument();
  await user.click(
    within(dialog).getByRole("button", { name: "Close Pokémon details" }),
  );
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  await user.type(
    screen.getByRole("textbox", { name: "Search Pokémon" }),
    "missing",
  );
  expect(pokemon).toBeDisabled();
  expect(screen.getByText(/No matching Pokémon/)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Clear filters" }));
  await user.selectOptions(
    screen.getByRole("combobox", { name: "Filter by type" }),
    "Fire",
  );
  expect(pokemon).toBeDisabled();
  await user.selectOptions(
    screen.getByRole("combobox", { name: "Filter by type" }),
    "Electric",
  );
  expect(pokemon).toBeEnabled();
  await user.click(screen.getByRole("button", { name: "Next box" }));
  expect(screen.getAllByLabelText(/Empty slot/)).toHaveLength(30);
  expect(screen.getByRole("button", { name: "Next box" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "Previous box" }));
  expect(screen.getByRole("button", { name: "Previous box" })).toBeDisabled();
});
it("supports hash navigation and session appearance settings", async () => {
  const user = userEvent.setup();
  render(<App />);
  await screen.findByRole("button", { name: /View Pikachu/ });
  for (const [page, heading] of [
    ["dashboard", "Dashboard"],
    ["trading", "Trading"],
    ["history", "History"],
    ["settings", "Settings"],
  ]) {
    window.location.hash = `#${page}`;
    fireEvent(window, new HashChangeEvent("hashchange"));
    expect(
      await screen.findByRole("heading", { level: 1, name: heading }),
    ).toBeInTheDocument();
  }
  await user.click(screen.getByRole("checkbox", { name: /Compact boxes/ }));
  expect(document.querySelector(".app")).toHaveClass("compact");
});
it("shows API failure and retries successfully without fabricated fallback data", async () => {
  vi.mocked(fetch).mockRejectedValueOnce(new Error("offline"));
  const user = userEvent.setup();
  render(<App />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Couldn’t load the boxes",
  );
  await user.click(screen.getByRole("button", { name: "Retry" }));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: /View Pikachu/ })).toBeEnabled(),
  );
});

it('places ESP32 between History and Settings and supports its direct URL',async()=>{
 window.location.hash='#esp32';
 vi.mocked(fetch).mockImplementation(async (input)=>({ok:true,json:async()=>String(input)==='/api/health'?{mode:'demo',pkhex_available:false}:String(input)==='/api/esp32/status'?{supported_host:false,esptool_available:false,release:null,image:null,devices:[],job:null}:boxes} as Response));
 render(<App/>);
 expect(await screen.findByRole('heading',{name:'ESP32-S3 wireless firmware'})).toBeInTheDocument();
 const nav=screen.getByRole('navigation',{name:'Main navigation'});
 const links=within(nav).getAllByRole('link').map(link=>link.textContent);
 expect(links.slice(-3)).toEqual(['◷History','▣ESP32','⚙Settings']);
 expect(screen.getByRole('link',{name:'ESP32'})).toHaveAttribute('aria-current','page');
});
