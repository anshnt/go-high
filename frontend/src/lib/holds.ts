// Whether a capability is held, given what is known. No imports, so node tests it (lib/capabilities.ts is the store).

export type Known = { ready: boolean; caps: ReadonlySet<string> };

/**
 * Held, or not known yet. Unknown means yes: the API refuses what a role may not do, and a button that appears and
 * then goes is better than a screen that flashes empty on every load. `can("channels.manage")` decides what to OFFER;
 * the server decides what to ALLOW.
 */
export const holds = (s: Known, capability: string): boolean => !s.ready || s.caps.has(capability);

/** Every one of them held. */
export const holdsAll = (s: Known, capabilities: string[]): boolean => capabilities.every((c) => holds(s, c));
