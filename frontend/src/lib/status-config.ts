import {
  Clock,
  PhoneCall,
  Activity,
  CheckCircle2,
  XCircle,
  Phone,
  FileEdit,
  Play,
  Pause,
  Ban,
} from "lucide-react";

// ---------- Call Status ----------

export const CALL_STATUS_CONFIG: Record<
  string,
  {
    variant: "default" | "secondary" | "destructive" | "outline";
    icon: typeof Clock;
    color: string;
  }
> = {
  initiated: { variant: "outline", icon: Clock, color: "text-muted-foreground" },
  ringing: { variant: "outline", icon: PhoneCall, color: "text-blue-400" },
  "in-progress": { variant: "default", icon: Activity, color: "text-green-400" },
  completed: { variant: "secondary", icon: CheckCircle2, color: "text-emerald-400" },
  failed: { variant: "destructive", icon: XCircle, color: "text-red-400" },
  error: { variant: "destructive", icon: XCircle, color: "text-red-400" },
  "no-answer": { variant: "secondary", icon: Phone, color: "text-amber-400" },
  busy: { variant: "secondary", icon: Phone, color: "text-amber-400" },
  voicemail: { variant: "secondary", icon: Phone, color: "text-amber-400" },
};

// ---------- Campaign Status ----------

export const CAMPAIGN_STATUS_CONFIG: Record<
  string,
  {
    label: string;
    variant: "default" | "secondary" | "destructive" | "outline";
    className: string;
    icon: typeof Clock;
  }
> = {
  draft: {
    label: "Draft",
    variant: "secondary",
    className: "bg-zinc-500/10 text-zinc-400 border-zinc-500/20",
    icon: FileEdit,
  },
  running: {
    label: "Running",
    variant: "default",
    className: "bg-blue-500/10 text-blue-400 border-blue-500/20",
    icon: Play,
  },
  paused: {
    label: "Paused",
    variant: "outline",
    className: "bg-yellow-500/10 text-yellow-400 border-yellow-500/20",
    icon: Pause,
  },
  completed: {
    label: "Completed",
    variant: "secondary",
    className: "bg-green-500/10 text-green-400 border-green-500/20",
    icon: CheckCircle2,
  },
  cancelled: {
    label: "Cancelled",
    variant: "destructive",
    className: "bg-red-500/10 text-red-400 border-red-500/20",
    icon: Ban,
  },
};

// ---------- Lead Status ----------

export const LEAD_STATUS_COLORS: Record<string, string> = {
  new: "bg-blue-500/15 text-blue-400 border-blue-500/25",
  contacted: "bg-yellow-500/15 text-yellow-400 border-yellow-500/25",
  qualified: "bg-green-500/15 text-green-400 border-green-500/25",
  unqualified: "bg-red-500/15 text-red-400 border-red-500/25",
};

export const LEAD_QUALIFICATION_COLORS: Record<string, string> = {
  hot: "bg-red-500/15 text-red-400 border-red-500/25",
  warm: "bg-orange-500/15 text-orange-400 border-orange-500/25",
  cold: "bg-blue-500/15 text-blue-400 border-blue-500/25",
  high: "bg-green-500/15 text-green-400 border-green-500/25",
  medium: "bg-yellow-500/15 text-yellow-400 border-yellow-500/25",
  low: "bg-zinc-500/15 text-zinc-400 border-zinc-500/25",
};

// ---------- Interest Level ----------

export const INTEREST_CONFIG: Record<string, { color: string; label: string }> = {
  high: { color: "bg-emerald-500/10 text-emerald-500 border-emerald-500/20", label: "High" },
  medium: { color: "bg-amber-500/10 text-amber-500 border-amber-500/20", label: "Medium" },
  low: { color: "bg-red-500/10 text-red-500 border-red-500/20", label: "Low" },
};

// ---------- Severity ----------

export const SEVERITY_COLORS: Record<string, string> = {
  critical: "bg-red-500/10 text-red-500 border-red-500/20",
  high: "bg-orange-500/10 text-orange-500 border-orange-500/20",
  medium: "bg-amber-500/10 text-amber-500 border-amber-500/20",
  low: "bg-blue-500/10 text-blue-500 border-blue-500/20",
};
