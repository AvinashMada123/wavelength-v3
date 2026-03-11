"use client";

import { useEffect, useState, useCallback, type FormEvent } from "react";
import {
  Plus,
  Search,
  Users,
  Loader2,
  Trash2,
  ChevronLeft,
  ChevronRight,
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
import {
  fetchLeads,
  createLead,
  updateLead,
  deleteLead,
  type Lead,
} from "@/lib/api";

const PAGE_SIZE = 50;

const STATUS_OPTIONS = [
  { value: "new", label: "New" },
  { value: "contacted", label: "Contacted" },
  { value: "qualified", label: "Qualified" },
  { value: "unqualified", label: "Unqualified" },
];

const STATUS_COLORS: Record<string, string> = {
  new: "bg-blue-500/15 text-blue-400 border-blue-500/25",
  contacted: "bg-yellow-500/15 text-yellow-400 border-yellow-500/25",
  qualified: "bg-green-500/15 text-green-400 border-green-500/25",
  unqualified: "bg-red-500/15 text-red-400 border-red-500/25",
};

export default function LeadsPage() {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");

  // Add dialog
  const [addOpen, setAddOpen] = useState(false);
  const [addSaving, setAddSaving] = useState(false);
  const [addForm, setAddForm] = useState({
    contact_name: "",
    phone_number: "",
    email: "",
    company: "",
    location: "",
  });

  // Edit dialog
  const [editOpen, setEditOpen] = useState(false);
  const [editSaving, setEditSaving] = useState(false);
  const [editLead, setEditLead] = useState<Lead | null>(null);
  const [editForm, setEditForm] = useState({
    contact_name: "",
    phone_number: "",
    email: "",
    company: "",
    location: "",
    status: "",
  });

  // Delete confirmation
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const loadLeads = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchLeads({
        status: statusFilter !== "all" ? statusFilter : undefined,
        search: search || undefined,
        page,
        page_size: PAGE_SIZE,
      });
      setLeads(data.items);
      setTotal(data.total);
    } catch {
      toast.error("Failed to load leads");
    } finally {
      setLoading(false);
    }
  }, [statusFilter, search, page]);

  useEffect(() => {
    loadLeads();
  }, [loadLeads]);

  // Debounced search: reset page when search/filter changes
  useEffect(() => {
    setPage(1);
  }, [search, statusFilter]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  // --- Add Lead ---
  function resetAddForm() {
    setAddForm({
      contact_name: "",
      phone_number: "",
      email: "",
      company: "",
      location: "",
    });
  }

  async function handleAddLead(e: FormEvent) {
    e.preventDefault();
    if (!addForm.contact_name.trim() || !addForm.phone_number.trim()) {
      toast.error("Name and phone number are required");
      return;
    }
    setAddSaving(true);
    try {
      await createLead({
        contact_name: addForm.contact_name.trim(),
        phone_number: addForm.phone_number.trim(),
        email: addForm.email.trim() || undefined,
        company: addForm.company.trim() || undefined,
        location: addForm.location.trim() || undefined,
      });
      toast.success("Lead created successfully");
      setAddOpen(false);
      resetAddForm();
      loadLeads();
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Failed to create lead";
      toast.error(message);
    } finally {
      setAddSaving(false);
    }
  }

  // --- Edit Lead ---
  function openEditDialog(lead: Lead) {
    setEditLead(lead);
    setEditForm({
      contact_name: lead.contact_name,
      phone_number: lead.phone_number,
      email: lead.email || "",
      company: lead.company || "",
      location: lead.location || "",
      status: lead.status,
    });
    setEditOpen(true);
  }

  async function handleEditLead(e: FormEvent) {
    e.preventDefault();
    if (!editLead) return;
    if (!editForm.contact_name.trim() || !editForm.phone_number.trim()) {
      toast.error("Name and phone number are required");
      return;
    }
    setEditSaving(true);
    try {
      await updateLead(editLead.id, {
        contact_name: editForm.contact_name.trim(),
        phone_number: editForm.phone_number.trim(),
        email: editForm.email.trim() || null,
        company: editForm.company.trim() || null,
        location: editForm.location.trim() || null,
        status: editForm.status,
      });
      toast.success("Lead updated successfully");
      setEditOpen(false);
      setEditLead(null);
      loadLeads();
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Failed to update lead";
      toast.error(message);
    } finally {
      setEditSaving(false);
    }
  }

  // --- Delete Lead ---
  async function handleDeleteLead() {
    if (!editLead) return;
    setDeleting(true);
    try {
      await deleteLead(editLead.id);
      toast.success("Lead deleted successfully");
      setDeleteOpen(false);
      setEditOpen(false);
      setEditLead(null);
      loadLeads();
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Failed to delete lead";
      toast.error(message);
    } finally {
      setDeleting(false);
    }
  }

  return (
    <>
      <Header title="Leads" />
      <PageTransition>
        <div className="space-y-6 p-6">
          {/* Page description */}
          <div>
            <p className="text-sm text-muted-foreground">
              Manage your contacts and leads
            </p>
          </div>

          {/* Top bar: Search + Filter + Add */}
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex flex-1 items-center gap-3">
              <div className="relative flex-1 max-w-sm">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  placeholder="Search leads..."
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="pl-9"
                />
              </div>
              <Select value={statusFilter} onValueChange={setStatusFilter}>
                <SelectTrigger className="w-40">
                  <SelectValue placeholder="All statuses" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All statuses</SelectItem>
                  {STATUS_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <Button
              onClick={() => {
                resetAddForm();
                setAddOpen(true);
              }}
              className="bg-gradient-to-r from-violet-500 to-indigo-600 text-white hover:from-violet-600 hover:to-indigo-700"
            >
              <Plus className="h-4 w-4" />
              Add Lead
            </Button>
          </div>

          {/* Table */}
          <Card>
            <CardContent className="p-0">
              {loading ? (
                <div className="space-y-3 p-6">
                  {Array.from({ length: 6 }).map((_, i) => (
                    <Skeleton key={i} className="h-12 w-full" />
                  ))}
                </div>
              ) : leads.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
                  <Users className="mb-3 h-10 w-10 opacity-30" />
                  <p className="text-sm font-medium">No leads found</p>
                  <p className="mt-1 text-xs">
                    {search || statusFilter !== "all"
                      ? "Try adjusting your search or filters"
                      : "Get started by adding your first lead"}
                  </p>
                  {!search && statusFilter === "all" && (
                    <Button
                      variant="link"
                      size="sm"
                      className="mt-2"
                      onClick={() => {
                        resetAddForm();
                        setAddOpen(true);
                      }}
                    >
                      Add your first lead
                    </Button>
                  )}
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Name</TableHead>
                      <TableHead>Phone</TableHead>
                      <TableHead className="hidden md:table-cell">
                        Email
                      </TableHead>
                      <TableHead className="hidden lg:table-cell">
                        Company
                      </TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead className="hidden sm:table-cell">
                        Calls
                      </TableHead>
                      <TableHead className="hidden lg:table-cell">
                        Source
                      </TableHead>
                      <TableHead className="hidden sm:table-cell">
                        Created
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {leads.map((lead) => (
                      <TableRow
                        key={lead.id}
                        className="cursor-pointer"
                        onClick={() => openEditDialog(lead)}
                      >
                        <TableCell className="font-medium">
                          {lead.contact_name}
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {lead.phone_number}
                        </TableCell>
                        <TableCell className="hidden md:table-cell text-muted-foreground">
                          {lead.email || "\u2014"}
                        </TableCell>
                        <TableCell className="hidden lg:table-cell text-muted-foreground">
                          {lead.company || "\u2014"}
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant="outline"
                            className={
                              STATUS_COLORS[lead.status] || "text-muted-foreground"
                            }
                          >
                            {lead.status}
                          </Badge>
                        </TableCell>
                        <TableCell className="hidden sm:table-cell text-muted-foreground">
                          {lead.call_count}
                        </TableCell>
                        <TableCell className="hidden lg:table-cell text-muted-foreground">
                          {lead.source || "\u2014"}
                        </TableCell>
                        <TableCell className="hidden sm:table-cell text-muted-foreground">
                          {format(new Date(lead.created_at), "MMM d, yyyy")}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>

          {/* Pagination */}
          {!loading && leads.length > 0 && (
            <div className="flex items-center justify-between">
              <p className="text-sm text-muted-foreground">
                Showing {(page - 1) * PAGE_SIZE + 1}&ndash;
                {Math.min(page * PAGE_SIZE, total)} of {total} leads
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

      {/* Add Lead Dialog */}
      <Dialog open={addOpen} onOpenChange={setAddOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add Lead</DialogTitle>
            <DialogDescription>
              Create a new lead by filling in the details below.
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleAddLead} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="add-name">
                Contact Name <span className="text-red-400">*</span>
              </Label>
              <Input
                id="add-name"
                placeholder="John Doe"
                value={addForm.contact_name}
                onChange={(e) =>
                  setAddForm((f) => ({ ...f, contact_name: e.target.value }))
                }
                disabled={addSaving}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="add-phone">
                Phone Number <span className="text-red-400">*</span>
              </Label>
              <Input
                id="add-phone"
                placeholder="+1 (555) 123-4567"
                value={addForm.phone_number}
                onChange={(e) =>
                  setAddForm((f) => ({ ...f, phone_number: e.target.value }))
                }
                disabled={addSaving}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="add-email">Email</Label>
              <Input
                id="add-email"
                type="email"
                placeholder="john@example.com"
                value={addForm.email}
                onChange={(e) =>
                  setAddForm((f) => ({ ...f, email: e.target.value }))
                }
                disabled={addSaving}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="add-company">Company</Label>
              <Input
                id="add-company"
                placeholder="Acme Inc."
                value={addForm.company}
                onChange={(e) =>
                  setAddForm((f) => ({ ...f, company: e.target.value }))
                }
                disabled={addSaving}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="add-location">Location</Label>
              <Input
                id="add-location"
                placeholder="New York, NY"
                value={addForm.location}
                onChange={(e) =>
                  setAddForm((f) => ({ ...f, location: e.target.value }))
                }
                disabled={addSaving}
              />
            </div>
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => setAddOpen(false)}
                disabled={addSaving}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={addSaving}
                className="bg-gradient-to-r from-violet-500 to-indigo-600 text-white hover:from-violet-600 hover:to-indigo-700"
              >
                {addSaving ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Creating...
                  </>
                ) : (
                  "Create Lead"
                )}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Edit Lead Dialog */}
      <Dialog
        open={editOpen}
        onOpenChange={(open) => {
          setEditOpen(open);
          if (!open) setEditLead(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit Lead</DialogTitle>
            <DialogDescription>
              Update the lead details or change their status.
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleEditLead} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="edit-name">
                Contact Name <span className="text-red-400">*</span>
              </Label>
              <Input
                id="edit-name"
                value={editForm.contact_name}
                onChange={(e) =>
                  setEditForm((f) => ({ ...f, contact_name: e.target.value }))
                }
                disabled={editSaving}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-phone">
                Phone Number <span className="text-red-400">*</span>
              </Label>
              <Input
                id="edit-phone"
                value={editForm.phone_number}
                onChange={(e) =>
                  setEditForm((f) => ({ ...f, phone_number: e.target.value }))
                }
                disabled={editSaving}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-email">Email</Label>
              <Input
                id="edit-email"
                type="email"
                value={editForm.email}
                onChange={(e) =>
                  setEditForm((f) => ({ ...f, email: e.target.value }))
                }
                disabled={editSaving}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-company">Company</Label>
              <Input
                id="edit-company"
                value={editForm.company}
                onChange={(e) =>
                  setEditForm((f) => ({ ...f, company: e.target.value }))
                }
                disabled={editSaving}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-location">Location</Label>
              <Input
                id="edit-location"
                value={editForm.location}
                onChange={(e) =>
                  setEditForm((f) => ({ ...f, location: e.target.value }))
                }
                disabled={editSaving}
              />
            </div>
            <div className="space-y-2">
              <Label>Status</Label>
              <Select
                value={editForm.status}
                onValueChange={(val) =>
                  setEditForm((f) => ({ ...f, status: val }))
                }
              >
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {STATUS_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <DialogFooter className="sm:justify-between">
              <Button
                type="button"
                variant="destructive"
                onClick={() => setDeleteOpen(true)}
                disabled={editSaving}
              >
                <Trash2 className="h-4 w-4" />
                Delete
              </Button>
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setEditOpen(false)}
                  disabled={editSaving}
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  disabled={editSaving}
                  className="bg-gradient-to-r from-violet-500 to-indigo-600 text-white hover:from-violet-600 hover:to-indigo-700"
                >
                  {editSaving ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Saving...
                    </>
                  ) : (
                    "Save Changes"
                  )}
                </Button>
              </div>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete Lead</DialogTitle>
            <DialogDescription>
              Are you sure you want to delete{" "}
              <span className="font-medium text-foreground">
                {editLead?.contact_name}
              </span>
              ? This action cannot be undone.
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
              onClick={handleDeleteLead}
              disabled={deleting}
            >
              {deleting ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Deleting...
                </>
              ) : (
                "Delete Lead"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
