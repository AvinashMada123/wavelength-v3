"use client";

import { useState, useRef } from "react";
import { Copy, Download, Upload, Eye, Check, AlertCircle } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import { importTemplate, previewImport } from "@/lib/sequences-api";

interface ImportExportDialogProps {
  isOpen: boolean;
  onClose: () => void;
  mode: "import" | "export";
  exportData?: Record<string, any>;
  onImportSuccess?: (template: any) => void;
}

export function ImportExportDialog({
  isOpen,
  onClose,
  mode,
  exportData,
  onImportSuccess,
}: ImportExportDialogProps) {
  const [copied, setCopied] = useState(false);
  const [pastedJson, setPastedJson] = useState("");
  const [previewResult, setPreviewResult] = useState<{
    valid: boolean;
    errors: string[];
    template: any | null;
  } | null>(null);
  const [isPreviewing, setIsPreviewing] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const formattedExport = exportData
    ? JSON.stringify(exportData, null, 2)
    : "";

  function handleCopy() {
    navigator.clipboard.writeText(formattedExport).then(() => {
      setCopied(true);
      toast.success("Copied to clipboard");
      setTimeout(() => setCopied(false), 2000);
    });
  }

  function handleDownload() {
    const name =
      exportData?.name
        ? exportData.name.toLowerCase().replace(/\s+/g, "_")
        : "sequence_template";
    const blob = new Blob([formattedExport], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${name}.json`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success("Downloaded template JSON");
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      setPastedJson((ev.target?.result as string) || "");
      setPreviewResult(null);
    };
    reader.readAsText(file);
    // Reset input so same file can be re-selected
    e.target.value = "";
  }

  async function handlePreview() {
    if (!pastedJson.trim()) {
      toast.error("Paste or upload a JSON file first");
      return;
    }
    let parsed: Record<string, any>;
    try {
      parsed = JSON.parse(pastedJson);
    } catch {
      toast.error("Invalid JSON — could not parse");
      return;
    }
    setIsPreviewing(true);
    try {
      const result = await previewImport(parsed);
      setPreviewResult(result);
    } catch (err: any) {
      toast.error(err?.message || "Preview failed");
    } finally {
      setIsPreviewing(false);
    }
  }

  async function handleImport() {
    if (!pastedJson.trim()) {
      toast.error("Paste or upload a JSON file first");
      return;
    }
    let parsed: Record<string, any>;
    try {
      parsed = JSON.parse(pastedJson);
    } catch {
      toast.error("Invalid JSON — could not parse");
      return;
    }
    setIsImporting(true);
    try {
      const template = await importTemplate(parsed);
      toast.success(`Imported "${template.name}" successfully`);
      onImportSuccess?.(template);
      onClose();
      setPastedJson("");
      setPreviewResult(null);
    } catch (err: any) {
      toast.error(err?.message || "Import failed");
    } finally {
      setIsImporting(false);
    }
  }

  function handleClose() {
    setPastedJson("");
    setPreviewResult(null);
    onClose();
  }

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && handleClose()}>
      <DialogContent className="max-w-2xl max-h-[85vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>
            {mode === "export" ? "Export Template" : "Import Template"}
          </DialogTitle>
          <DialogDescription>
            {mode === "export"
              ? "Copy or download the template JSON to share or back up this sequence."
              : "Upload a .json file or paste template JSON to import a sequence."}
          </DialogDescription>
        </DialogHeader>

        {mode === "export" ? (
          <div className="flex flex-col gap-4 min-h-0 flex-1">
            <div className="flex gap-2 justify-end">
              <Button variant="outline" size="sm" onClick={handleCopy} className="gap-2">
                {copied ? (
                  <Check className="h-4 w-4 text-green-400" />
                ) : (
                  <Copy className="h-4 w-4" />
                )}
                {copied ? "Copied!" : "Copy to Clipboard"}
              </Button>
              <Button variant="outline" size="sm" onClick={handleDownload} className="gap-2">
                <Download className="h-4 w-4" />
                Download .json
              </Button>
            </div>
            <Textarea
              value={formattedExport}
              readOnly
              className="font-mono text-xs min-h-[400px] resize-none flex-1 bg-muted/30"
            />
          </div>
        ) : (
          <div className="flex flex-col gap-4 min-h-0 flex-1">
            {/* File upload */}
            <div>
              <Label className="text-sm text-muted-foreground mb-2 block">
                Upload a .json file
              </Label>
              <div className="flex items-center gap-3">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => fileInputRef.current?.click()}
                  className="gap-2"
                >
                  <Upload className="h-4 w-4" />
                  Choose File
                </Button>
                <span className="text-xs text-muted-foreground">
                  or paste JSON below
                </span>
              </div>
              <input
                ref={fileInputRef}
                type="file"
                accept=".json,application/json"
                className="hidden"
                onChange={handleFileChange}
              />
            </div>

            {/* Paste area */}
            <Textarea
              placeholder='{ "name": "My Sequence", "steps": [...] }'
              value={pastedJson}
              onChange={(e) => {
                setPastedJson(e.target.value);
                setPreviewResult(null);
              }}
              className="font-mono text-xs min-h-[200px] resize-none bg-muted/30"
            />

            {/* Preview result */}
            {previewResult && (
              <div
                className={`rounded-lg border p-4 text-sm space-y-2 ${
                  previewResult.valid
                    ? "border-green-500/30 bg-green-500/5"
                    : "border-red-500/30 bg-red-500/5"
                }`}
              >
                {previewResult.valid && previewResult.template ? (
                  <>
                    <div className="flex items-center gap-2 text-green-400 font-medium">
                      <Check className="h-4 w-4" />
                      Valid template
                    </div>
                    <div className="grid grid-cols-3 gap-3 text-xs mt-2">
                      <div>
                        <p className="text-muted-foreground">Name</p>
                        <p className="font-medium truncate">
                          {previewResult.template.name}
                        </p>
                      </div>
                      <div>
                        <p className="text-muted-foreground">Trigger</p>
                        <Badge variant="outline" className="text-xs mt-0.5">
                          {previewResult.template.trigger_type}
                        </Badge>
                      </div>
                      <div>
                        <p className="text-muted-foreground">Steps</p>
                        <p className="font-medium">
                          {previewResult.template.step_count ?? "—"}
                        </p>
                      </div>
                    </div>
                  </>
                ) : (
                  <>
                    <div className="flex items-center gap-2 text-red-400 font-medium">
                      <AlertCircle className="h-4 w-4" />
                      Validation errors
                    </div>
                    <ul className="list-disc pl-4 space-y-1 text-red-400 text-xs">
                      {previewResult.errors.map((err, i) => (
                        <li key={i}>{err}</li>
                      ))}
                    </ul>
                  </>
                )}
              </div>
            )}

            {/* Actions */}
            <div className="flex gap-2 justify-end pt-1">
              <Button
                variant="outline"
                size="sm"
                onClick={handlePreview}
                disabled={isPreviewing || !pastedJson.trim()}
                className="gap-2"
              >
                <Eye className="h-4 w-4" />
                {isPreviewing ? "Checking..." : "Preview"}
              </Button>
              <Button
                size="sm"
                onClick={handleImport}
                disabled={isImporting || !pastedJson.trim()}
                className="gap-2 bg-violet-600 hover:bg-violet-700"
              >
                <Upload className="h-4 w-4" />
                {isImporting ? "Importing..." : "Import"}
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
