"use client";

import { useState } from "react";
import { formatDistanceToNow } from "date-fns";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import {
  Users,
  Search,
  Loader2,
  AlertTriangle,
  CheckCircle2,
  PlayCircle,
  PauseCircle,
  FlaskConical,
  ChevronRight,
} from "lucide-react";
import type { UseFlowJourneyReturn } from "@/hooks/use-flow-journey";

interface LeadsPanelProps {
  journey: UseFlowJourneyReturn;
}

const STATUS_CONFIG: Record<string, { icon: typeof CheckCircle2; color: string }> = {
  active: { icon: PlayCircle, color: "text-blue-500" },
  paused: { icon: PauseCircle, color: "text-yellow-500" },
  completed: { icon: CheckCircle2, color: "text-green-500" },
  error: { icon: AlertTriangle, color: "text-red-500" },
  cancelled: { icon: PauseCircle, color: "text-gray-500" },
};

export function LeadsPanel({ journey }: LeadsPanelProps) {
  const [search, setSearch] = useState("");

  const filtered = journey.instances.filter((inst) => {
    if (!search) return true;
    const q = search.toLowerCase();
    return (
      inst.lead_name?.toLowerCase().includes(q) ||
      inst.lead_phone?.includes(q)
    );
  });

  return (
    <Sheet>
      <SheetTrigger asChild>
        <Button size="sm" variant="outline" className="gap-1.5">
          <Users className="h-3.5 w-3.5" />
          Leads
          {journey.total > 0 && (
            <Badge variant="secondary" className="ml-1 text-xs">
              {journey.total}
            </Badge>
          )}
        </Button>
      </SheetTrigger>
      <SheetContent side="right" className="w-80 sm:w-96">
        <SheetHeader>
          <SheetTitle>Leads in Flow</SheetTitle>
        </SheetHeader>

        <div className="mt-4 space-y-3">
          {/* Search */}
          <div className="relative">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Search leads..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9"
            />
          </div>

          {/* Status filter */}
          <Select
            value={journey.statusFilter ?? "all"}
            onValueChange={(v) => journey.setStatusFilter(v === "all" ? null : v)}
          >
            <SelectTrigger className="h-8 text-xs">
              <SelectValue placeholder="All statuses" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Statuses</SelectItem>
              <SelectItem value="active">Active</SelectItem>
              <SelectItem value="completed">Completed</SelectItem>
              <SelectItem value="error">Error</SelectItem>
              <SelectItem value="paused">Paused</SelectItem>
              <SelectItem value="cancelled">Cancelled</SelectItem>
            </SelectContent>
          </Select>

          {/* Instance list */}
          <ScrollArea className="h-[calc(100vh-220px)]">
            {journey.loading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
              </div>
            ) : filtered.length === 0 ? (
              <p className="py-8 text-center text-sm text-muted-foreground">
                No leads in this flow yet.
              </p>
            ) : (
              <div className="space-y-1">
                {filtered.map((inst) => {
                  const statusCfg = STATUS_CONFIG[inst.status] ?? STATUS_CONFIG.active;
                  const StatusIcon = statusCfg.icon;
                  const isSelected = journey.selectedInstanceId === inst.id;

                  return (
                    <button
                      key={inst.id}
                      onClick={() =>
                        isSelected ? journey.clearSelection() : journey.selectInstance(inst.id)
                      }
                      className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition-colors hover:bg-muted/50 ${
                        isSelected ? "bg-muted ring-1 ring-primary" : ""
                      }`}
                    >
                      <StatusIcon className={`h-4 w-4 shrink-0 ${statusCfg.color}`} />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5">
                          <span className="truncate text-sm font-medium">
                            {inst.lead_name || "Unknown"}
                          </span>
                          {inst.is_test && (
                            <FlaskConical className="h-3 w-3 text-orange-500" />
                          )}
                        </div>
                        <div className="flex items-center gap-2 text-xs text-muted-foreground">
                          <span>{inst.lead_phone}</span>
                          <span>
                            {formatDistanceToNow(new Date(inst.started_at), { addSuffix: true })}
                          </span>
                        </div>
                        {inst.error_message && (
                          <p className="mt-0.5 truncate text-xs text-red-500">
                            {inst.error_message}
                          </p>
                        )}
                      </div>
                      <ChevronRight className={`h-4 w-4 shrink-0 text-muted-foreground transition-transform ${isSelected ? "rotate-90" : ""}`} />
                    </button>
                  );
                })}
              </div>
            )}
          </ScrollArea>
        </div>
      </SheetContent>
    </Sheet>
  );
}
