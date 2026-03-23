"use client";

import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { MockLead } from "@/lib/flow-simulation";

// Preset mock profiles for quick selection
const PRESETS: { label: string; lead: MockLead }[] = [
  {
    label: "Interested Lead",
    lead: { name: "Rahul Sharma", phone: "+919876543210", interest_level: 9, sentiment: "positive", goal_outcome: "meeting_booked" },
  },
  {
    label: "Cold Lead",
    lead: { name: "Priya Patel", phone: "+919123456780", interest_level: 3, sentiment: "negative", goal_outcome: "not_interested" },
  },
  {
    label: "No Answer Lead",
    lead: { name: "Amit Kumar", phone: "+919555555555", interest_level: 5, sentiment: "neutral", goal_outcome: "" },
  },
];

interface MockLeadDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onStart: (lead: MockLead) => void;
}

export function MockLeadDialog({ open, onOpenChange, onStart }: MockLeadDialogProps) {
  const [lead, setLead] = useState<MockLead>(PRESETS[0].lead);
  const [selectedPreset, setSelectedPreset] = useState<string>("0");

  function handlePresetChange(value: string) {
    setSelectedPreset(value);
    if (value !== "custom") {
      setLead(PRESETS[parseInt(value)].lead);
    }
  }

  function handleFieldChange(field: string, value: string | number) {
    setSelectedPreset("custom");
    setLead((prev) => ({ ...prev, [field]: value }));
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Configure Mock Lead</DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          {/* Preset selector */}
          <div className="space-y-2">
            <Label>Profile Preset</Label>
            <Select value={selectedPreset} onValueChange={handlePresetChange}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PRESETS.map((p, i) => (
                  <SelectItem key={i} value={String(i)}>{p.label}</SelectItem>
                ))}
                <SelectItem value="custom">Custom</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Editable fields */}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label htmlFor="mock-name">Name</Label>
              <Input
                id="mock-name"
                value={lead.name}
                onChange={(e) => handleFieldChange("name", e.target.value)}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="mock-phone">Phone</Label>
              <Input
                id="mock-phone"
                value={lead.phone}
                onChange={(e) => handleFieldChange("phone", e.target.value)}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="mock-interest">Interest (1-10)</Label>
              <Input
                id="mock-interest"
                type="number"
                min={1}
                max={10}
                value={lead.interest_level ?? 5}
                onChange={(e) => handleFieldChange("interest_level", parseInt(e.target.value) || 5)}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="mock-sentiment">Sentiment</Label>
              <Select
                value={lead.sentiment ?? "neutral"}
                onValueChange={(v) => handleFieldChange("sentiment", v)}
              >
                <SelectTrigger id="mock-sentiment">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="positive">Positive</SelectItem>
                  <SelectItem value="neutral">Neutral</SelectItem>
                  <SelectItem value="negative">Negative</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="space-y-1">
            <Label htmlFor="mock-goal">Goal Outcome</Label>
            <Input
              id="mock-goal"
              value={lead.goal_outcome ?? ""}
              onChange={(e) => handleFieldChange("goal_outcome", e.target.value)}
              placeholder="e.g. meeting_booked, callback, not_interested"
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={() => { onStart(lead); onOpenChange(false); }}>
            Start Simulation
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
