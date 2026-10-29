import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import {
  ImportTools,
  BoxExports,
  MoveTools,
  StorageSettings,
  RenameBox,
} from "./BankTools";
import type { Box, Pokemon } from "./types";
const pokemon: Pokemon = {
  id: "pika",
  species: "Pikachu",
  dex: 25,
  level: 28,
  types: [],
  nature: "Jolly",
  ability: "Static",
  trainer: "ASH",
  game: "Sword / Shield",
  shiny: false,
};
const boxes: Box[] = [
  { id: 1, name: "Arrival", slots: [pokemon, ...Array(29).fill(null)] },
  {
    id: 2,
    name: "Other",
    slots: [{ ...pokemon, id: "other" }, ...Array(29).fill(null)],
  },
];
beforeEach(() =>
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) }),
  ),
);
it("uploads bytes and shows banked, duplicate, refused and conversion notes", async () => {
  const user = userEvent.setup(),
    changed = vi.fn();
  vi.mocked(fetch).mockResolvedValue({
    ok: true,
    json: async () => ({
      name: "party.sav",
      save: "Black 2",
      pokemon: [
        {
          species: "Patrat",
          where: "Party 1",
          state: "banked",
          detail: "Left its Oran Berry behind",
        },
        { species: "Lillipup", where: "Box 1", state: "already", detail: "" },
        {
          species: "Patrat",
          where: "Box 2",
          state: "refused",
          detail: "Invalid move",
        },
      ],
    }),
  } as Response);
  render(<ImportTools ready onChange={changed} />);
  await user.upload(
    screen.getByLabelText("Pokémon file or save"),
    new File(["test bytes"], "party.sav"),
  );
  expect(
    await screen.findByText("1 banked · 1 already imported · 1 refused"),
  ).toBeInTheDocument();
  expect(screen.getByText(/Oran Berry/)).toBeInTheDocument();
  expect(screen.getByText(/Invalid move/)).toBeInTheDocument();
  expect(changed).toHaveBeenCalledOnce();
  expect(vi.mocked(fetch).mock.calls[0][1]?.body).toBeInstanceOf(File);
});
it("reports a stale destination without hiding the move failure", async () => {
  const user = userEvent.setup(),
    close = vi.fn(),
    changed = vi.fn();
  vi.mocked(fetch).mockResolvedValue({
    ok: false,
    json: async () => ({
      detail: "Destination changed. Refresh your boxes before moving.",
    }),
  } as Response);
  render(
    <MoveTools
      pokemon={pokemon}
      boxes={boxes}
      onChange={changed}
      onClose={close}
    />,
  );
  await user.selectOptions(screen.getByLabelText("Destination box"), "2");
  await user.click(screen.getByRole("button", { name: "Move / swap Pokémon" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Destination changed",
  );
  expect(close).not.toHaveBeenCalled();
  expect(changed).not.toHaveBeenCalled();
  expect(JSON.parse(vi.mocked(fetch).mock.calls[0][1]?.body as string)).toEqual(
    { box_id: 2, slot: 0, expected: "other" },
  );
});
it("loads trainer and backups, then saves trainer settings", async () => {
  const user = userEvent.setup(),
    changed = vi.fn();
  vi.mocked(fetch).mockImplementation(
    async (input) =>
      ({
        ok: true,
        json: async () =>
          String(input) === "/api/settings"
            ? { trainer: { ot: "ASH", tid: 1, sid: 2, language: 2, gender: 0 } }
            : String(input) === "/api/backups"
              ? [{ id: "abc", time: 1, action: "Imported", current: true }]
              : {},
      }) as Response,
  );
  render(<StorageSettings onChange={changed} />);
  expect(await screen.findByDisplayValue("ASH")).toBeInTheDocument();
  await user.clear(screen.getByLabelText("Trainer name"));
  await user.type(screen.getByLabelText("Trainer name"), "TYLER");
  await user.click(
    screen.getByRole("button", { name: "Save receiving trainer" }),
  );
  expect(await screen.findByRole("status")).toHaveTextContent(
    "Receiving trainer saved",
  );
  const put = vi.mocked(fetch).mock.calls.find((c) => c[1]?.method === "PUT");
  expect(JSON.parse(put?.[1]?.body as string).ot).toBe("TYLER");
  await waitFor(() => expect(changed).toHaveBeenCalledOnce());
});
it("renames a box", async () => {
  const user = userEvent.setup(),
    changed = vi.fn();
  render(<RenameBox box={boxes[0]} onChange={changed} />);
  await user.clear(screen.getByLabelText("Box name"));
  await user.type(screen.getByLabelText("Box name"), "Travel");
  await user.click(screen.getByRole("button", { name: "Rename box" }));
  await waitFor(() => expect(changed).toHaveBeenCalledOnce());
});


it("downloads selected and all box ZIPs, and disables an empty box", async () => {
  const create=vi.fn().mockReturnValue('blob:zip'), revoke=vi.fn();
  vi.stubGlobal('URL',Object.assign(URL,{createObjectURL:create,revokeObjectURL:revoke}));
  const downloads: string[] = [];
  const click=vi.spyOn(HTMLAnchorElement.prototype,'click').mockImplementation(function (this: HTMLAnchorElement) { downloads.push(this.download); });
  vi.mocked(fetch).mockResolvedValue({ok:true,blob:async()=>new Blob(['zip'])} as Response);
  const user=userEvent.setup();
  const {rerender}=render(<BoxExports box={boxes[0]} boxes={boxes}/>);
  await user.click(screen.getByRole('button',{name:'Export this box'}));
  await waitFor(()=>expect(revoke).toHaveBeenCalledWith('blob:zip'));
  expect(fetch).toHaveBeenLastCalledWith('/api/boxes/1/export');
  expect(downloads[0]).toBe('pkmn-ownbank-box-01.zip');
  await user.click(screen.getByRole('button',{name:'Export all boxes'}));
  expect(fetch).toHaveBeenLastCalledWith('/api/boxes/export');
  await waitFor(()=>expect(revoke).toHaveBeenCalledTimes(2));
  expect(downloads[1]).toBe('pkmn-ownbank-boxes.zip');
  rerender(<BoxExports box={{...boxes[0],slots:Array(30).fill(null)}} boxes={boxes}/>);
  expect(screen.getByRole('button',{name:'Export this box'})).toBeDisabled();
  expect(screen.getByRole('button',{name:'Export all boxes'})).toBeEnabled();
  click.mockRestore();
});

it("shows ZIP export failures and lets the user retry", async () => {
  vi.mocked(fetch).mockResolvedValue({ok:false,json:async()=>({detail:'Bank integrity check failed.'})} as Response);
  render(<BoxExports box={boxes[0]} boxes={boxes}/>);
  await userEvent.click(screen.getByRole('button',{name:'Export all boxes'}));
  expect(await screen.findByRole('alert')).toHaveTextContent('Bank integrity check failed.');
  expect(screen.getByRole('button',{name:'Export all boxes'})).toBeEnabled();
});
