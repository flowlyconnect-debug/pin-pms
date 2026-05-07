import { useState, type MouseEvent, type ReactNode } from "react";
import { Check, Copy } from "lucide-react";
import { toast } from "sonner";

interface CopyableProps {
  value: string;
  children?: ReactNode;
  silent?: boolean;
}

export function Copyable({ value, children, silent }: CopyableProps) {
  const [copied, setCopied] = useState(false);

  const onCopy = async (event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      if (!silent) toast.success("Kopioitu leikepoydalle");
      setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error("Kopiointi epaonnistui");
    }
  };

  return (
    <button type="button" className="copyable" onClick={onCopy} title="Kopioi leikepoydalle">
      <span>{children ?? value}</span>
      <span className="copyable-icon" aria-hidden>
        {copied ? <Check size={14} /> : <Copy size={14} />}
      </span>
    </button>
  );
}
