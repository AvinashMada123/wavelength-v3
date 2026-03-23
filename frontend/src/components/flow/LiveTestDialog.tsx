"use client";

import { useState } from "react";
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import { Loader2, Phone, Clock } from "lucide-react";
import { startLiveTest } from "@/lib/flows-api";

interface LiveTestDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  flowId: string;
  onTestStarted: (instanceId: string) => void;
}

const DELAY_PRESETS = [
  { label: "Real-time (no compression)", ratio: 1 },
  { label: "10x faster (1hr → 6min)", ratio: 10 },
  { label: "60x faster (1hr → 1min)", ratio: 60 },
  { label: "360x faster (1hr → 10s)", ratio: 360 },
];

export function LiveTestDialog({
  open,
  onOpenChange,
  flowId,
  onTestStarted,
}: LiveTestDialogProps) {
  const [phone, setPhone] = useState("");
  const [delayRatio, setDelayRatio] = useState(60);
  const [loading, setLoading] = useState(false);

  async function handleStart() {
    if (!phone.match(/^\+\d{10,15}$/)) {
      toast.error("Enter a valid phone number with country code (e.g. +919876543210)");
      return;
    }

    setLoading(true);
    try {
      const result = await startLiveTest(flowId, {
        phone_number: phone,
        delay_ratio: delayRatio,
      });
      toast.success(`Live test started! Calling ${phone}...`);
      onTestStarted(result.instance_id);
      onOpenChange(false);
    } catch (err: any) {
      toast.error(err.message || "Failed to start live test");
    } finally {
      setLoading(false);
    }
  }

  function formatCompression(ratio: number): string {
    if (ratio <= 1) return "No compression";
    if (ratio < 60) return `1 hour → ${Math.round(60 / ratio)} minutes`;
    if (ratio === 60) return "1 hour → 1 minute";
    return `1 hour → ${Math.round(3600 / ratio)} seconds`;
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Phone className="h-4 w-4" />
            Live Test
          </DialogTitle>
          <DialogDescription>
            Run the flow with real calls and messages to your phone.
            All delays will be compressed for faster testing.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-5">
          {/* Phone number */}
          <div className="space-y-2">
            <Label htmlFor="test-phone">Your Phone Number</Label>
            <Input
              id="test-phone"
              placeholder="+919876543210"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              Real calls and messages will be sent to this number.
            </p>
          </div>

          {/* Delay compression */}
          <div className="space-y-3">
            <Label className="flex items-center gap-1.5">
              <Clock className="h-3.5 w-3.5" />
              Delay Compression
            </Label>
            <Slider
              value={[delayRatio]}
              onValueChange={([v]) => setDelayRatio(v)}
              min={1}
              max={360}
              step={1}
              className="w-full"
            />
            <p className="text-sm font-medium">{formatCompression(delayRatio)}</p>
            <div className="flex flex-wrap gap-1.5">
              {DELAY_PRESETS.map((p) => (
                <Button
                  key={p.ratio}
                  size="sm"
                  variant={delayRatio === p.ratio ? "secondary" : "outline"}
                  onClick={() => setDelayRatio(p.ratio)}
                  className="text-xs"
                >
                  {p.label}
                </Button>
              ))}
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={handleStart} disabled={loading}>
            {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Start Live Test
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
