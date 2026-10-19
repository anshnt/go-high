import { Mail, MessageCircle, MessageSquare, MessagesSquare, type LucideIcon } from "lucide-react";
import { CHANNEL_LABEL } from "./views.ts";
import type { ChannelKind } from "./types.ts";

export const CHANNEL_ICON: Record<ChannelKind, LucideIcon> = { sms: MessageSquare, email: Mail, whatsapp: MessageCircle, webchat: MessagesSquare };

/** The small channel mark: a glyph in the channel's own tint (SMS blue, email indigo, WhatsApp green, web chat amber). */
export function ChannelIcon({ kind, size = 14, label }: { kind: ChannelKind | null | undefined; size?: number; label?: boolean }) {
  if (!kind) return null;
  const Icon = CHANNEL_ICON[kind];
  return (
    <span className="ib-ch" data-kind={kind} title={CHANNEL_LABEL[kind]}>
      <Icon size={size} aria-hidden />
      {label ? <span>{CHANNEL_LABEL[kind]}</span> : <span className="sr-only">{CHANNEL_LABEL[kind]}</span>}
    </span>
  );
}
