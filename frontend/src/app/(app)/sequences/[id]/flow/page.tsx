// frontend/src/app/(app)/sequences/[id]/flow/page.tsx
"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter, useParams } from "next/navigation";
import { ArrowLeft, Loader2, Workflow } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

import type { FlowDefinition, FlowVersion } from "@/lib/flow-types";
import { fetchFlow, fetchVersion, createDraftVersion } from "@/lib/flows-api";
import { fetchBots } from "@/lib/api";
import { FlowCanvas } from "@/components/flow/FlowCanvas";

export default function FlowCanvasPage() {
  const router = useRouter();
  const params = useParams();
  const flowId = params.id as string;

  const [flow, setFlow] = useState<FlowDefinition | null>(null);
  const [version, setVersion] = useState<FlowVersion | null>(null);
  const [bots, setBots] = useState<Array<{ id: string; name: string }>>([]);
  const [loading, setLoading] = useState(true);

  const loadFlow = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchFlow(flowId);
      setFlow(data);

      // Use draft version if available, otherwise published
      const activeVersion = data.draft_version || data.published_version;
      if (!activeVersion) {
        toast.error("No version found for this flow");
        router.push("/sequences");
        return;
      }

      // Fetch full version detail (with nodes and edges)
      const fullVersion = await fetchVersion(flowId, activeVersion.id);
      setVersion(fullVersion);
    } catch {
      toast.error("Failed to load flow");
      router.push("/sequences");
    } finally {
      setLoading(false);
    }
  }, [flowId, router]);

  const loadBots = useCallback(async () => {
    try {
      const data = await fetchBots();
      setBots(data.map((b: any) => ({ id: b.id, name: b.agent_name || b.company_name || "Unnamed" })));
    } catch {
      // non-critical
    }
  }, []);

  useEffect(() => {
    loadFlow();
    loadBots();
  }, [loadFlow, loadBots]);

  const handleEditDraft = useCallback(async () => {
    if (!flow) return;
    try {
      const newDraft = await createDraftVersion(flowId);
      // Fetch full version with nodes and edges
      const fullDraft = await fetchVersion(flowId, newDraft.id);
      setVersion(fullDraft);
      toast.success("Draft version created — you can now edit the flow");
    } catch (err: any) {
      toast.error(err.message || "Failed to create draft");
    }
  }, [flow, flowId]);

  const handlePublished = useCallback(() => {
    loadFlow(); // Reload to get updated version status
  }, [loadFlow]);

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!flow || !version) {
    return (
      <div className="flex h-screen flex-col items-center justify-center gap-4">
        <Workflow className="h-12 w-12 text-muted-foreground opacity-30" />
        <p className="text-muted-foreground">Flow not found</p>
        <Button variant="outline" onClick={() => router.push("/sequences")}>
          <ArrowLeft className="mr-2 h-4 w-4" />
          Back to Flows
        </Button>
      </div>
    );
  }

  return (
    <div className="flex h-screen flex-col">
      {/* Header */}
      <header className="flex h-14 items-center gap-3 border-b border-border/50 bg-background/80 px-4 backdrop-blur-md">
        <Button variant="ghost" size="sm" onClick={() => router.push("/sequences")} className="h-8 gap-1.5">
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div className="flex flex-1 items-center gap-2">
          <h1 className="text-lg font-semibold">{flow.name}</h1>
          <Badge variant={version.status === "draft" ? "secondary" : version.status === "published" ? "default" : "outline"}>
            {version.status} v{version.version_number}
          </Badge>
        </div>
        <div className="flex items-center gap-2">
          {version.status === "published" && (
            <Button size="sm" variant="outline" onClick={handleEditDraft}>
              Edit as Draft
            </Button>
          )}
        </div>
      </header>

      {/* Canvas — fills remaining space */}
      <div className="flex-1 overflow-hidden">
        <FlowCanvas
          flowId={flowId}
          flow={flow}
          version={version}
          bots={bots}
          onPublished={handlePublished}
        />
      </div>
    </div>
  );
}
