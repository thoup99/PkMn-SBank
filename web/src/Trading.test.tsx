import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import Trading from "./Trading";
import type { Box, Pokemon } from "./types";
const pikachu: Pokemon = {
  id: "pika",
  species: "Pikachu",
  dex: 25,
  level: 28,
  game: "Sword / Shield",
  types: [],
  nature: "Jolly",
  ability: "Static",
  trainer: "ASH",
  shiny: false,
};
const boxes: Box[] = [
  { id: 1, name: "Arrival", slots: [pikachu, ...Array(29).fill(null)] },
];
const games = [
  { key: "swsh", name: "Sword / Shield" },
  { key: "bdsp", name: "Brilliant Diamond / Shining Pearl" },
];
const queue = [
  {
    id: "pika",
    species: "Pikachu",
    source_game: "Sword / Shield",
    compatible: true,
    reason: "",
    warnings: ["Missing HOME tracker"],
  },
];
const staged = {
  id: "session1",
  mode: "simulation",
  version: 1,
  game: "swsh",
  status: "ready",
  completed: 0,
  invalidated: false,
  queue,
  events: [],
};
function reply(data: unknown, ok = true) {
  return Promise.resolve({ ok, json: async () => data } as Response);
}
beforeEach(() =>
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation(() => reply({ games, session: null })),
  ),
);
it("checks compatibility, stages and starts a simulated session with preserved-record messaging", async () => {
  const user = userEvent.setup();
  vi.mocked(fetch).mockImplementation((input, options) => {
    const path = String(input);
    if (path.endsWith("/preview"))
      return reply({
        game: "swsh",
        queue,
        compatible: true,
        token: "a".repeat(64),
      });
    if (path.endsWith("/stage")) return reply(staged);
    if (path.endsWith("/start"))
      return reply({ ...staged, status: "connecting", version: 2 });
    if (path.endsWith("/advance"))
      return reply({
        ...staged,
        status: "completed",
        version: 3,
        completed: 1,
        events: [
          { time: 1, message: "Simulation completed; original retained." },
        ],
      });
    return reply({ games, session: null });
  });
  render(<Trading boxes={boxes} ready />);
  await screen.findByRole("option", { name: "Sword / Shield" });
  expect(
    screen.getByRole("button", { name: "Stage simulation queue" }),
  ).toBeDisabled();
  await user.click(screen.getByRole("checkbox", { name: /Pikachu/ }));
  await user.click(screen.getByRole("button", { name: "Check compatibility" }));
  expect(await screen.findByText("Pikachu — Compatible")).toBeInTheDocument();
  expect(screen.getByText("Missing HOME tracker")).toBeInTheDocument();
  await user.click(
    screen.getByRole("button", { name: "Stage simulation queue" }),
  );
  await user.selectOptions(
    await screen.findByLabelText("Simulation scenario"),
    "disconnect",
  );
  await user.click(screen.getByRole("button", { name: "Start simulation" }));
  const start = vi
    .mocked(fetch)
    .mock.calls.find((c) => String(c[0]).endsWith("/start"));
  expect(JSON.parse(start?.[1]?.body as string)).toEqual({
    version: 1,
    scenario: "disconnect",
    fault_after: 0,
  });
  await user.click(
    await screen.findByRole("button", { name: "Advance simulation" }),
  );
  expect(await screen.findByRole("status")).toHaveTextContent(
    "Simulation completed. All original Bank records remain unchanged.",
  );
  expect(screen.getByText(/Real transfers: 0/)).toBeInTheDocument();
});
it("shows a concrete refusal and never enables staging incompatible Pokémon", async () => {
  const user = userEvent.setup();
  vi.mocked(fetch).mockImplementation((input) =>
    String(input).endsWith("/preview")
      ? reply({
          game: "bdsp",
          queue: [
            {
              ...queue[0],
              compatible: false,
              reason: "This species is not in that game.",
            },
          ],
          compatible: false,
          token: "b".repeat(64),
        })
      : reply({ games, session: null }),
  );
  render(<Trading boxes={boxes} ready />);
  await screen.findByRole("option", { name: "Sword / Shield" });
  await user.selectOptions(screen.getByLabelText("Destination game"), "bdsp");
  await user.click(screen.getByRole("checkbox", { name: /Pikachu/ }));
  await user.click(screen.getByRole("button", { name: "Check compatibility" }));
  expect(
    await screen.findByText("This species is not in that game."),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Stage simulation queue" }),
  ).toBeDisabled();
});
it("restores an interrupted session and resumes only on explicit input", async () => {
  const user = userEvent.setup();
  let resumed = false;
  vi.mocked(fetch).mockImplementation((input) => {
    if (String(input).endsWith("/resume")) {
      resumed = true;
      return reply({ ...staged, status: "connecting", version: 5 });
    }
    return reply({
      games,
      session: { ...staged, status: "interrupted", version: 4 },
    });
  });
  render(<Trading boxes={boxes} ready />);
  const button = await screen.findByRole("button", {
    name: "Resume simulation",
  });
  expect(resumed).toBe(false);
  expect(screen.getByRole("checkbox", { name: /Pikachu/ })).toBeChecked();
  await user.click(button);
  await waitFor(() => expect(resumed).toBe(true));
  expect(
    await screen.findByRole("button", { name: "Advance simulation" }),
  ).toBeInTheDocument();
  expect(screen.getByRole("checkbox", { name: /Pikachu/ })).toBeDisabled();
});
it("keeps an invalidated backup session from resuming and offers fresh staging", async () => {
  const user = userEvent.setup();
  vi.mocked(fetch).mockImplementation(() =>
    reply({
      games,
      session: { ...staged, status: "interrupted", invalidated: true },
    }),
  );
  render(<Trading boxes={boxes} ready />);
  expect(
    await screen.findByText(/Bank recovery invalidated/),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Resume simulation" }),
  ).not.toBeInTheDocument();
  expect(screen.getByRole("checkbox", { name: /Pikachu/ })).not.toBeChecked();
  expect(screen.getByRole("button", { name: "Check compatibility" })).toBeDisabled();
  await user.click(screen.getByRole("checkbox", { name: /Pikachu/ }));
  expect(screen.getByRole("button", { name: "Check compatibility" })).toBeEnabled();
  await user.click(screen.getByRole("button", { name: "Clear selection" }));
  expect(screen.getByRole("checkbox", { name: /Pikachu/ })).not.toBeChecked();
});
it("recovers from an initial API failure with an explicit retry", async () => {
  const user = userEvent.setup();
  vi.mocked(fetch).mockRejectedValueOnce(new Error("Connection lost"));
  render(<Trading boxes={boxes} ready />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Connection lost");
  await user.click(
    screen.getByRole("button", { name: "Retry loading trading" }),
  );
  expect(
    await screen.findByRole("option", { name: "Sword / Shield" }),
  ).toBeInTheDocument();
});
