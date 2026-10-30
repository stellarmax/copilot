import { type FormEvent, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { ErrorState } from "./Feedback";
import { updateDisplayName, type User } from "../lib/api";

export function DisplayNameDialog({ user, onClose }: { user: User; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(user.display_name);
  const save = useMutation({
    mutationFn: () => updateDisplayName(name.trim()),
    onSuccess: (updated) => {
      queryClient.setQueryData(["me"], updated);
      onClose();
    },
  });

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  return (
    <div
      className="dialog-scrim"
      onMouseDown={(event) => event.target === event.currentTarget && onClose()}
      onKeyDown={(event) => event.key === "Escape" && onClose()}
    >
      <form className="demo-info-dialog" role="dialog" aria-modal="true" aria-labelledby="display-name-title" onSubmit={handleSubmit}>
        <div className="dialog-heading">
          <div><span className="eyebrow">YOUR ACCOUNT</span><h2 id="display-name-title">Change display name</h2></div>
          <button className="icon-button" type="button" onClick={onClose} aria-label="Close"><X size={18} /></button>
        </div>
        <div className="demo-info-body auth-form">
          <label>Display name <small>shown in the sidebar and the Overview greeting</small>
            <input autoFocus required maxLength={60} value={name} onChange={(event) => setName(event.target.value)} />
          </label>
          {save.error && <ErrorState message={save.error.message} />}
        </div>
        <div className="dialog-actions dialog-actions-split">
          <button className="button button-secondary" type="button" onClick={onClose}>Cancel</button>
          <button className="button button-primary" type="submit" disabled={save.isPending || !name.trim() || name.trim() === user.display_name}>
            {save.isPending ? "Saving" : "Save"}
          </button>
        </div>
      </form>
    </div>
  );
}
