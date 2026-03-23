"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { CheckCircle2, Target, Route } from "lucide-react";
import type { JourneySummary } from "@/lib/flow-simulation";

interface SimulationSummaryProps {
  summary: JourneySummary;
}

export function SimulationSummary({ summary }: SimulationSummaryProps) {
  if (summary.endReason === "active") return null;

  return (
    <Card className="w-80 shadow-xl">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <CheckCircle2 className="h-4 w-4 text-green-500" />
          Simulation Complete
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* End reason */}
        <div className="flex items-center gap-2">
          <Badge variant={summary.endReason === "goal_met" ? "default" : "secondary"}>
            {summary.endReason === "goal_met" ? "Goal Reached" : "Flow Ended"}
          </Badge>
          <span className="text-sm text-muted-foreground">
            {summary.totalSteps} nodes visited
          </span>
        </div>

        {/* Goals hit */}
        {summary.goalsHit.length > 0 && (
          <div className="space-y-1">
            <div className="flex items-center gap-1 text-xs font-medium text-muted-foreground">
              <Target className="h-3 w-3" /> Goals Hit
            </div>
            <div className="flex flex-wrap gap-1">
              {summary.goalsHit.map((g) => (
                <Badge key={g} variant="outline" className="border-green-500 text-green-700">
                  {g}
                </Badge>
              ))}
            </div>
          </div>
        )}

        {/* Path */}
        <div className="space-y-1">
          <div className="flex items-center gap-1 text-xs font-medium text-muted-foreground">
            <Route className="h-3 w-3" /> Path Taken
          </div>
          <ol className="space-y-0.5">
            {summary.path.map((step, i) => (
              <li key={step.nodeId} className="flex items-center gap-2 text-sm">
                <span className="flex h-5 w-5 items-center justify-center rounded-full bg-muted text-xs font-medium">
                  {i + 1}
                </span>
                <span>{step.nodeName}</span>
                {step.outcome && (
                  <span className="text-xs text-muted-foreground">({step.outcome})</span>
                )}
              </li>
            ))}
          </ol>
        </div>
      </CardContent>
    </Card>
  );
}
