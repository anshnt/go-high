// What the UI offers a role. The server is the authority (it answers 403 with the capability it wanted); this only
// decides what to hide or disable up front, from the key of the workspace role that /api/me gives. A role we do not know
// (a custom one) is offered everything, and the 403 it may meet is explained where it happens.
export type Can = { writeDeals: boolean; managePipelines: boolean };

export function canOf(role: string | null | undefined): Can {
  switch (role) {
    case "admin":
    case "owner":
    case "manager":
      return { writeDeals: true, managePipelines: true };
    case "member":
    case "automation":
      return { writeDeals: true, managePipelines: false };
    case "viewer":
      return { writeDeals: false, managePipelines: false };
    default:
      return { writeDeals: true, managePipelines: true };
  }
}
