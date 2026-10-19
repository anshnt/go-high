import { MessageSquare } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router";
import { useCan } from "../lib/capabilities";
import { whatWentWrong } from "../lib/errors";
import { Button, useToast } from "../ui";
import { startConversation } from "./api";

/** "Message" on a contact: opens their conversation in the inbox (starting one if they have none), ready for the first message. */
export function MessageButton({ contactId }: { contactId: string }) {
  const navigate = useNavigate();
  const toast = useToast();
  const { can } = useCan();
  const [busy, setBusy] = useState(false);
  if (!can("conversations.read") || !can("conversations.write") || !can("messages.send")) return null;
  const open = async () => {
    setBusy(true);
    try {
      const conv = await startConversation(contactId);
      navigate(`/inbox/${conv.id}`);
    } catch (e) {
      toast({ title: "Could not open the conversation", description: whatWentWrong(e), tone: "danger" });
      setBusy(false);
    }
  };
  return (
    <Button size="sm" variant="secondary" loading={busy} onClick={() => void open()}>
      <MessageSquare size={14} aria-hidden /> <span className="rec-hide-sm">Message</span>
    </Button>
  );
}
