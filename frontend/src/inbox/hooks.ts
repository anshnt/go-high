import { useCallback, useEffect, useState } from "react";
import { listChannels, listConsents, listTeams, setDnd } from "./api";
import type { Channel, ChannelKind, Consent, Team } from "./types.ts";

/** The workspace's channels (to pick a sender, name a message's channel, and list per-channel views). Null until loaded. */
export function useChannels(workspace: string | null) {
  const [channels, setChannels] = useState<Channel[] | null>(null);
  const reload = useCallback(() => {
    listChannels().then(setChannels, () => setChannels((c) => c ?? []));
  }, []);
  useEffect(() => {
    setChannels(null);
    if (workspace) reload();
  }, [workspace, reload]);
  return { channels, reload };
}

/** Teams for the assign menu, when the role may read them. */
export function useTeams(workspace: string | null, allowed: boolean) {
  const [teams, setTeams] = useState<Team[]>([]);
  useEffect(() => {
    if (!workspace || !allowed) return setTeams([]);
    let live = true;
    listTeams().then((t) => live && setTeams(t), () => undefined);
    return () => {
      live = false;
    };
  }, [workspace, allowed]);
  return teams;
}

/** What the contact has agreed to, per channel kind. Null while loading. `reload` after a change. */
export function useConsents(contactId: string | null, version: number) {
  const [consents, setConsents] = useState<Consent[] | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!contactId) return setConsents(null);
    let live = true;
    listConsents(contactId).then(
      (c) => live && setConsents(c),
      () => live && setConsents([]),
    );
    return () => {
      live = false;
    };
  }, [contactId, version, tick]);
  const setSwitch = useCallback(
    async (kind: ChannelKind, on: boolean) => {
      if (!contactId) return;
      await setDnd(contactId, kind, on);
      setTick((n) => n + 1);
    },
    [contactId],
  );
  return { consents, setSwitch, reload: () => setTick((n) => n + 1) };
}
