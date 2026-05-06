"use client";

import { useClerk } from "@clerk/nextjs";
import { Eye, Globe2, ListPlus, LogOut, PanelLeft } from "lucide-react";
import { useState } from "react";

import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandShortcut,
} from "@/components/ui/command";
import { useMissionStore, useRecentMissions } from "@/features/run-mission";
import { useT } from "@/shared/i18n";
import { useShortcut } from "@/shared/keyboard";

/**
 * Command palette — Cmd+K opens a single-input search-or-command surface
 * with sections in the spec's prescribed order: Recent / Actions / Account.
 *
 * `New mission` focuses the top-bar URL input (the input owns its own
 * shortcut for `/`); `Toggle reasoning` and `Toggle sidebar` are wired in
 * later specs that own the corresponding state.
 */
export function CommandPalette() {
  const t = useT();
  const [open, setOpen] = useState(false);
  const recent = useRecentMissions();
  const openMission = useMissionStore((s) => s.openMission);
  const openMultiUrl = useMissionStore((s) => s.openMultiUrl);
  const { signOut } = useClerk();

  useShortcut(["cmd+k", "ctrl+k"], () => setOpen((value) => !value), { allowInInput: true });

  function _focusUrlInput(): void {
    // The top-bar input is the only `type="url"` field in the shell.
    const input = document.querySelector<HTMLInputElement>('input[type="url"]');
    input?.focus();
  }

  return (
    <CommandDialog open={open} onOpenChange={setOpen}>
      <CommandInput placeholder={t("common", "searchOrCommand")} />
      <CommandList>
        <CommandEmpty>{t("common", "nothingFound")}</CommandEmpty>

        {recent.length > 0 ? (
          <CommandGroup heading={t("common", "recent")}>
            {recent.map((mission) => (
              <CommandItem
                key={mission.id}
                onSelect={() => {
                  openMission(mission.id);
                  setOpen(false);
                }}
              >
                <Globe2 className="h-3.5 w-3.5" />
                <span className="truncate font-mono text-[13px]">{mission.prompt}</span>
              </CommandItem>
            ))}
          </CommandGroup>
        ) : null}

        <CommandGroup heading={t("common", "actions")}>
          <CommandItem
            onSelect={() => {
              setOpen(false);
              _focusUrlInput();
            }}
          >
            <Globe2 className="h-3.5 w-3.5" />
            {t("mission", "newMission")}
            <CommandShortcut>⌘N</CommandShortcut>
          </CommandItem>
          <CommandItem
            onSelect={() => {
              setOpen(false);
              openMultiUrl();
            }}
          >
            <ListPlus className="h-3.5 w-3.5" />
            {t("mission", "newMultiUrlMission")}
            <CommandShortcut>⌘⇧N</CommandShortcut>
          </CommandItem>
          <CommandItem onSelect={() => setOpen(false)}>
            <Eye className="h-3.5 w-3.5" />
            {t("mission", "toggleReasoning")}
            <CommandShortcut>⌘.</CommandShortcut>
          </CommandItem>
          <CommandItem onSelect={() => setOpen(false)}>
            <PanelLeft className="h-3.5 w-3.5" />
            {t("common", "toggleSidebar")}
            <CommandShortcut>⌘B</CommandShortcut>
          </CommandItem>
        </CommandGroup>

        <CommandGroup heading={t("common", "account")}>
          <CommandItem
            onSelect={() => {
              setOpen(false);
              void signOut();
            }}
          >
            <LogOut className="h-3.5 w-3.5" />
            {t("common", "signOut")}
          </CommandItem>
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  );
}
