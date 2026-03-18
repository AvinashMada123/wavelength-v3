"use client";

import { useEffect, useState, useCallback, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  Plus,
  Workflow,
  Loader2,
  ChevronLeft,
  ChevronRight,
  Upload,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";
import { format } from "date-fns";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  fetchTemplates,
  createTemplate,
  deleteTemplate,
  importTemplate,
  updateTemplate,
  type SequenceTemplate,
} from "@/lib/sequences-api";

const PAGE_SIZE = 50;

const TRIGGER_TYPE_OPTIONS = [
  { value: "post_call", label: "Post Call" },
  { value: "manual", label: "Manual" },
  { value: "campaign_complete", label: "Campaign Complete" },
];

const NAV_LINKS = [
  { href: "/sequences", label: "Templates" },
  { href: "/sequences/monitor", label: "Monitor" },
  { href: "/sequences/analytics", label: "Analytics" },
];

function triggerLabel(value: string): string {
  return TRIGGER_TYPE_OPTIONS.find((o) => o.value === value)?.label ?? value;
}

export default function SequencesPage() {
  const router = useRouter();
  const [templates, setTemplates] = useState<SequenceTemplate[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);

  // Create dialog
  const [createOpen, setCreateOpen] = useState(false);
  const [createSaving, setCreateSaving] = useState(false);
  const [createForm, setCreateForm] = useState({
    name: "",
    trigger_type: "post_call",
  });

  // Import dialog
  const [importOpen, setImportOpen] = useState(false);
  const [importSaving, setImportSaving] = useState(false);
  const [importJson, setImportJson] = useState("");

  // Delete confirmation
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<SequenceTemplate | null>(null);
  const [deleting, setDeleting] = useState(false);

  // Active toggle
  const [togglingId, setTogglingId] = useState<string | null>(null);

  const loadTemplates = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchTemplates(page, PAGE_SIZE);
      setTemplates(data.items);
      setTotal(data.total);
    } catch {
      toast.error("Failed to load sequence templates");
    } finally {
      setLoading(false);
    }
  }, [page]);

  useEffect(() => {
    loadTemplates();
  }, [loadTemplates]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  // --- Create ---
  function resetCreateForm() {
    setCreateForm({ name: "", trigger_type: "post_call" });
  }

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    if (!createForm.name.trim()) {
      toast.error("Template name is required");
      return;
    }
    setCreateSaving(true);
    try {
      const created = await createTemplate({
        name: createForm.name.trim(),
        trigger_type: createForm.trigger_type,
      });
      toast.success("Sequence template created");
      setCreateOpen(false);
      resetCreateForm();
      router.push(`/sequences/${created.id}`);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Failed to create template";
      toast.error(message);
    } finally {
      setCreateSaving(false);
    }
  }

  // --- Import ---
  async function handleImport(e: FormEvent) {
    e.preventDefault();
    if (!importJson.trim()) {
      toast.error("Please paste a JSON template");
      return;
    }
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(importJson.trim());
    } catch {
      toast.error("Invalid JSON — please check the format");
      return;
    }
    setImportSaving(true);
    try {
      const created = await importTemplate(parsed);
      toast.success("Template imported successfully");
      setImportOpen(false);
      setImportJson("");
      router.push(`/sequences/${created.id}`);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Failed to import template";
      toast.error(message);
    } finally {
      setImportSaving(false);
    }
  }

  // --- Toggle Active ---
  async function handleToggleActive(template: SequenceTemplate, e: React.MouseEvent) {
    e.stopPropagation();
    if (togglingId) return;
    setTogglingId(template.id);
    try {
      await updateTemplate(template.id, { is_active: !template.is_active });
      setTemplates((prev) =>
        prev.map((t) =>
          t.id === template.id ? { ...t, is_active: !t.is_active } : t
        )
      );
    } catch {
      toast.error("Failed to update template");
    } finally {
      setTogglingId(null);
    }
  }

  // --- Delete ---
  function openDeleteDialog(template: SequenceTemplate, e: React.MouseEvent) {
    e.stopPropagation();
    setDeleteTarget(template);
    setDeleteOpen(true);
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await deleteTemplate(deleteTarget.id);
      toast.success("Template deleted");
      setDeleteOpen(false);
      setDeleteTarget(null);
      loadTemplates();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Failed to delete template";
      toast.error(message);
    } finally {
      setDeleting(false);
    }
  }

  return (
    <>
      <Header title="Sequence Templates" />
      <PageTransition>
        <div className="space-y-6 p-6">
          {/* Nav links */}
          <div className="flex items-center gap-1 border-b border-border pb-3">
            {NAV_LINKS.map((link) => (
              <Link key={link.href} href={link.href}>
                <Button
                  variant={link.href === "/sequences" ? "secondary" : "ghost"}
                  size="sm"
                >
                  {link.label}
                </Button>
              </Link>
            ))}
          </div>

          {/* Description + Actions */}
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-sm text-muted-foreground">
                Automated multi-step outreach sequences triggered by call outcomes or events
              </p>
            </div>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                onClick={() => setImportOpen(true)}
              >
                <Upload className="h-4 w-4" />
                Import JSON
              </Button>
              <Button
                onClick={() => {
                  resetCreateForm();
                  setCreateOpen(true);
                }}
                className="bg-gradient-to-r from-violet-500 to-indigo-600 text-white hover:from-violet-600 hover:to-indigo-700"
              >
                <Plus className="h-4 w-4" />
                Create New
              </Button>
            </div>
          </div>

          {/* Table */}
          <Card>
            <CardContent className="p-0">
              {loading ? (
                <div className="space-y-3 p-6">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <Skeleton key={i} className="h-12 w-full" />
                  ))}
                </div>
              ) : templates.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
                  <Workflow className="mb-3 h-10 w-10 opacity-30" />
                  <p className="text-sm font-medium">No sequence templates yet</p>
                  <p className="mt-1 text-xs">
                    Create your first template to start automating follow-ups
                  </p>
                  <Button
                    variant="link"
                    size="sm"
                    className="mt-2"
                    onClick={() => {
                      resetCreateForm();
                      setCreateOpen(true);
                    }}
                  >
                    Create your first template
                  </Button>
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Name</TableHead>
                      <TableHead>Trigger Type</TableHead>
                      <TableHead>Steps</TableHead>
                      <TableHead>Active</TableHead>
                      <TableHead className="hidden sm:table-cell">Created</TableHead>
                      <TableHead className="w-10"></TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {templates.map((template) => (
                      <TableRow
                        key={template.id}
                        className="cursor-pointer hover:bg-muted/50"
                        onClick={() => router.push(`/sequences/${template.id}`)}
                      >
                        <TableCell className="font-medium">
                          {template.name}
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline" className="text-muted-foreground">
                            {triggerLabel(template.trigger_type)}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {template.step_count ?? 0}
                        </TableCell>
                        <TableCell>
                          <Switch
                            checked={template.is_active}
                            disabled={togglingId === template.id}
                            onCheckedChange={() => {}}
                            onClick={(e) => handleToggleActive(template, e)}
                          />
                        </TableCell>
                        <TableCell className="hidden sm:table-cell text-muted-foreground">
                          {format(new Date(template.created_at), "MMM d, yyyy")}
                        </TableCell>
                        <TableCell>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 w-7 p-0 text-muted-foreground hover:text-destructive"
                            onClick={(e) => openDeleteDialog(template, e)}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>

          {/* Pagination */}
          {!loading && templates.length > 0 && (
            <div className="flex items-center justify-between">
              <p className="text-sm text-muted-foreground">
                Showing {(page - 1) * PAGE_SIZE + 1}&ndash;
                {Math.min(page * PAGE_SIZE, total)} of {total} templates
              </p>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                >
                  <ChevronLeft className="h-4 w-4" />
                  Previous
                </Button>
                <span className="text-sm text-muted-foreground">
                  Page {page} of {totalPages}
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page >= totalPages}
                  onClick={() => setPage((p) => p + 1)}
                >
                  Next
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </div>
            </div>
          )}
        </div>
      </PageTransition>

      {/* Create Dialog */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create Sequence Template</DialogTitle>
            <DialogDescription>
              Define a new automated outreach sequence.
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleCreate} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="create-name">
                Name <span className="text-red-400">*</span>
              </Label>
              <Input
                id="create-name"
                placeholder="e.g. Post-Call Follow Up"
                value={createForm.name}
                onChange={(e) =>
                  setCreateForm((f) => ({ ...f, name: e.target.value }))
                }
                disabled={createSaving}
              />
            </div>
            <div className="space-y-2">
              <Label>Trigger Type</Label>
              <Select
                value={createForm.trigger_type}
                onValueChange={(val) =>
                  setCreateForm((f) => ({ ...f, trigger_type: val }))
                }
              >
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {TRIGGER_TYPE_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => setCreateOpen(false)}
                disabled={createSaving}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={createSaving}
                className="bg-gradient-to-r from-violet-500 to-indigo-600 text-white hover:from-violet-600 hover:to-indigo-700"
              >
                {createSaving ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Creating...
                  </>
                ) : (
                  "Create Template"
                )}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Import Dialog */}
      <Dialog open={importOpen} onOpenChange={setImportOpen}>
        <DialogContent className="max-w-lg max-h-[85vh] flex flex-col">
          <DialogHeader>
            <DialogTitle>Import Sequence Template</DialogTitle>
            <DialogDescription>
              Upload a .json file or paste template JSON to import a sequence.
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleImport} className="flex flex-col gap-4 flex-1 min-h-0">
            {/* File upload zone */}
            <div
              onClick={() => {
                const input = document.getElementById("import-file-input") as HTMLInputElement;
                input?.click();
              }}
              className="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-muted-foreground/25 hover:border-violet-500/50 cursor-pointer p-4 transition-colors"
            >
              <Upload className="h-6 w-6 text-muted-foreground mb-1" />
              <p className="text-sm font-medium">Upload .json file</p>
              <p className="text-xs text-muted-foreground">Click to browse or paste JSON below</p>
              <input
                id="import-file-input"
                type="file"
                accept=".json,application/json"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (!file) return;
                  const reader = new FileReader();
                  reader.onload = (ev) => setImportJson((ev.target?.result as string) || "");
                  reader.readAsText(file);
                  e.target.value = "";
                }}
              />
            </div>

            <div className="space-y-2 flex-1 min-h-0">
              <Label htmlFor="import-json">
                Template JSON <span className="text-red-400">*</span>
              </Label>
              <Textarea
                id="import-json"
                placeholder='{ "name": "...", "trigger_type": "...", "steps": [...] }'
                value={importJson}
                onChange={(e) => setImportJson(e.target.value)}
                disabled={importSaving}
                className="font-mono text-xs min-h-[120px] max-h-[250px] resize-none overflow-y-auto"
              />
            </div>
            <DialogFooter className="shrink-0 border-t pt-3">
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  setImportOpen(false);
                  setImportJson("");
                }}
                disabled={importSaving}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={importSaving}
                className="bg-gradient-to-r from-violet-500 to-indigo-600 text-white hover:from-violet-600 hover:to-indigo-700"
              >
                {importSaving ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Importing...
                  </>
                ) : (
                  "Import Template"
                )}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete Template</DialogTitle>
            <DialogDescription>
              Are you sure you want to delete{" "}
              <span className="font-medium text-foreground">
                {deleteTarget?.name}
              </span>
              ? This action cannot be undone and will remove all associated steps.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDeleteOpen(false)}
              disabled={deleting}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={handleDelete}
              disabled={deleting}
            >
              {deleting ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Deleting...
                </>
              ) : (
                "Delete Template"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
