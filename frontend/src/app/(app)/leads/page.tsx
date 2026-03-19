"use client";

import React, { useEffect, useState, useCallback, useMemo, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import {
  Plus,
  Search,
  Users,
  Loader2,
  Trash2,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  Upload,
  Pencil,
  Phone,
  X,
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
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  fetchLeads,
  createLead,
  updateLead,
  deleteLead,
  importLeads,
  enqueueCall,
  createCampaign,
  fetchBots,
  type Lead,
  type BotConfig,
} from "@/lib/api";
import { LEAD_STATUS_COLORS, LEAD_QUALIFICATION_COLORS } from "@/lib/status-config";
import { DateRangePicker, type DateRange } from "@/components/date-range-picker";

const PAGE_SIZE = 50;

const STATUS_OPTIONS = [
  { value: "new", label: "New" },
  { value: "contacted", label: "Contacted" },
  { value: "qualified", label: "Qualified" },
  { value: "unqualified", label: "Unqualified" },
];

export default function LeadsPage() {
  const router = useRouter();
  const [leads, setLeads] = useState<Lead[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [dateRange, setDateRange] = useState<DateRange>({ from: null, to: null });

  // Client-side date filtering
  const filteredLeadsByDate = useMemo(() => {
    if (!dateRange.from && !dateRange.to) return leads;
    return leads.filter((l) => {
      const d = l.created_at.slice(0, 10);
      if (dateRange.from && d < dateRange.from) return false;
      if (dateRange.to && d > dateRange.to) return false;
      return true;
    });
  }, [leads, dateRange]);

  // Add dialog
  const [addOpen, setAddOpen] = useState(false);
  const [addSaving, setAddSaving] = useState(false);
  const [addForm, setAddForm] = useState({
    contact_name: "",
    phone_number: "",
    email: "",
    company: "",
    location: "",
    tags: "",
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
    tags: "",
  });

  // Delete confirmation
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);

  // Mobile expanded rows
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());

  // Lead selection
  const [selectedLeads, setSelectedLeads] = useState<Set<string>>(new Set());
  const [bots, setBots] = useState<BotConfig[]>([]);
  const [actionDialogOpen, setActionDialogOpen] = useState(false);
  const [actionType, setActionType] = useState<"campaign" | "call">("campaign");
  const [selectedBotId, setSelectedBotId] = useState("");
  const [campaignName, setCampaignName] = useState("");
  const [actionSaving, setActionSaving] = useState(false);

  // CSV Import
  const [importing, setImporting] = useState(false);
  const fileInputRef = React.useRef<HTMLInputElement>(null);

  function toggleRow(id: string, e: React.MouseEvent) {
    e.stopPropagation();
    setExpandedRows((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

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

  useEffect(() => {
    fetchBots().then(setBots).catch(() => {});
  }, []);

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
      tags: "",
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
        tags: addForm.tags.trim() ? addForm.tags.split(",").map((t) => t.trim()).filter(Boolean) : undefined,
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
      tags: (lead.tags || []).join(", "),
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
        tags: editForm.tags.trim() ? editForm.tags.split(",").map((t) => t.trim()).filter(Boolean) : [],
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

  // --- Lead Selection ---
  function toggleSelectLead(id: string) {
    setSelectedLeads((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleSelectAll() {
    const pageIds = filteredLeadsByDate.map((l) => l.id);
    const allPageSelected = pageIds.every((id) => selectedLeads.has(id));
    setSelectedLeads((prev) => {
      const next = new Set(prev);
      if (allPageSelected) {
        pageIds.forEach((id) => next.delete(id));
      } else {
        pageIds.forEach((id) => next.add(id));
      }
      return next;
    });
  }

  function openAction(type: "campaign" | "call") {
    setActionType(type);
    setSelectedBotId(bots[0]?.id || "");
    setCampaignName("");
    setActionDialogOpen(true);
  }

  async function handleAction() {
    if (!selectedBotId) {
      toast.error("Please select a bot");
      return;
    }
    setActionSaving(true);
    try {
      if (actionType === "campaign") {
        if (!campaignName.trim()) {
          toast.error("Please enter a campaign name");
          setActionSaving(false);
          return;
        }
        await createCampaign({
          name: campaignName.trim(),
          bot_config_id: selectedBotId,
          lead_ids: Array.from(selectedLeads),
        });
        toast.success(`Campaign created with ${selectedLeads.size} leads`);
      } else {
        // Single call - enqueue each selected lead
        const selectedLeadData = leads.filter((l) => selectedLeads.has(l.id));
        let queued = 0;
        for (const lead of selectedLeadData) {
          try {
            await enqueueCall({
              bot_id: selectedBotId,
              contact_name: lead.contact_name,
              contact_phone: lead.phone_number,
            });
            queued++;
          } catch {
            toast.error(`Failed to queue call for ${lead.contact_name}`);
          }
        }
        toast.success(`${queued} call(s) queued`);
      }
      setActionDialogOpen(false);
      setSelectedLeads(new Set());
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Action failed";
      toast.error(message);
    } finally {
      setActionSaving(false);
    }
  }

  // --- CSV Import ---
  async function handleCsvImport(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setImporting(true);
    try {
      const text = await file.text();
      const lines = text.split("\n").map((l) => l.trim()).filter(Boolean);
      if (lines.length < 2) {
        toast.error("CSV file must have a header row and at least one data row");
        return;
      }
      const headers = lines[0].split(",").map((h) => h.trim().toLowerCase().replace(/[^a-z0-9_]/g, "_"));
      const nameIdx = headers.findIndex((h) => h.includes("name"));
      const phoneIdx = headers.findIndex((h) => h.includes("phone"));
      const emailIdx = headers.findIndex((h) => h.includes("email"));
      const companyIdx = headers.findIndex((h) => h.includes("company"));
      const locationIdx = headers.findIndex((h) => h.includes("location") || h.includes("city"));
      const tagsIdx = headers.findIndex((h) => h.includes("tag"));

      if (nameIdx === -1 || phoneIdx === -1) {
        toast.error("CSV must have columns containing 'name' and 'phone' in headers");
        return;
      }

      const leads = [];
      for (let i = 1; i < lines.length; i++) {
        // Simple CSV parsing (handles quoted fields)
        const cols = lines[i].match(/(".*?"|[^",\s]+)(?=\s*,|\s*$)/g)?.map((c) =>
          c.replace(/^"|"$/g, "").trim()
        ) || lines[i].split(",").map((c) => c.trim());

        const name = cols[nameIdx] || "";
        const phone = cols[phoneIdx] || "";
        if (!name || !phone) continue;

        const lead: any = {
          contact_name: name,
          phone_number: phone,
          source: "import",
        };
        if (emailIdx !== -1 && cols[emailIdx]) lead.email = cols[emailIdx];
        if (companyIdx !== -1 && cols[companyIdx]) lead.company = cols[companyIdx];
        if (locationIdx !== -1 && cols[locationIdx]) lead.location = cols[locationIdx];
        if (tagsIdx !== -1 && cols[tagsIdx]) {
          lead.tags = cols[tagsIdx].split(";").map((t: string) => t.trim()).filter(Boolean);
        }
        leads.push(lead);
      }

      if (leads.length === 0) {
        toast.error("No valid leads found in CSV");
        return;
      }

      const result = await importLeads(leads);
      toast.success(`Imported ${result.imported} leads (${result.skipped} skipped)`);
      if (result.errors.length > 0) {
        toast.error(`${result.errors.length} errors during import`);
      }
      loadLeads();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Failed to import CSV";
      toast.error(message);
    } finally {
      setImporting(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
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
              <DateRangePicker value={dateRange} onChange={setDateRange} />
            </div>
            <div className="flex items-center gap-2">
              <input
                ref={fileInputRef}
                type="file"
                accept=".csv"
                className="hidden"
                onChange={handleCsvImport}
              />
              <Button
                variant="outline"
                onClick={() => fileInputRef.current?.click()}
                disabled={importing}
              >
                {importing ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Upload className="h-4 w-4" />
                )}
                {importing ? "Importing..." : "Import CSV"}
              </Button>
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
              ) : filteredLeadsByDate.length === 0 ? (
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
                      <TableHead className="w-10">
                        <input
                          type="checkbox"
                          checked={filteredLeadsByDate.length > 0 && filteredLeadsByDate.every((l) => selectedLeads.has(l.id))}
                          onChange={toggleSelectAll}
                          className="rounded border-muted-foreground/50"
                        />
                      </TableHead>
                      <TableHead>Name</TableHead>
                      <TableHead>Phone</TableHead>
                      <TableHead className="hidden md:table-cell">
                        Email
                      </TableHead>
                      <TableHead className="hidden lg:table-cell">
                        Company
                      </TableHead>
                      <TableHead className="hidden xl:table-cell">
                        Tags
                      </TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead className="hidden md:table-cell">
                        Qualification
                      </TableHead>
                      <TableHead className="hidden sm:table-cell">
                        Calls
                      </TableHead>
                      <TableHead className="hidden lg:table-cell">
                        Last Call
                      </TableHead>
                      <TableHead className="hidden sm:table-cell">
                        Created
                      </TableHead>
                      <TableHead className="w-10"></TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {filteredLeadsByDate.map((lead) => {
                      const isExpanded = expandedRows.has(lead.id);
                      return (
                        <React.Fragment key={lead.id}>
                      <TableRow
                        className="cursor-pointer hover:bg-muted/50"
                        onClick={() => router.push(`/leads/${lead.id}`)}
                      >
                        <TableCell className="w-10" onClick={(e) => e.stopPropagation()}>
                          <input
                            type="checkbox"
                            checked={selectedLeads.has(lead.id)}
                            onChange={() => toggleSelectLead(lead.id)}
                            className="rounded border-muted-foreground/50"
                          />
                        </TableCell>
                        <TableCell className="font-medium">
                          <div className="flex items-center gap-1">
                            <button
                              className="md:hidden p-0.5 -ml-1 text-muted-foreground hover:text-foreground"
                              onClick={(e) => toggleRow(lead.id, e)}
                              aria-label="Expand row details"
                            >
                              <ChevronDown
                                className={`h-4 w-4 transition-transform ${isExpanded ? "rotate-180" : ""}`}
                              />
                            </button>
                            {lead.contact_name}
                          </div>
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
                        <TableCell className="hidden xl:table-cell">
                          {lead.tags && lead.tags.length > 0 ? (
                            <div className="flex flex-wrap gap-1">
                              {lead.tags.slice(0, 2).map((tag: string) => (
                                <Badge key={tag} variant="secondary" className="text-xs px-1.5 py-0">
                                  {tag}
                                </Badge>
                              ))}
                              {lead.tags.length > 2 && (
                                <Badge variant="secondary" className="text-xs px-1.5 py-0">
                                  +{lead.tags.length - 2}
                                </Badge>
                              )}
                            </div>
                          ) : (
                            <span className="text-muted-foreground">{"\u2014"}</span>
                          )}
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant="outline"
                            className={
                              LEAD_STATUS_COLORS[lead.status] || "text-muted-foreground"
                            }
                          >
                            {lead.status}
                          </Badge>
                        </TableCell>
                        <TableCell className="hidden md:table-cell">
                          {lead.qualification_level ? (
                            <Badge
                              variant="outline"
                              className={
                                LEAD_QUALIFICATION_COLORS[lead.qualification_level.toLowerCase()] ||
                                "text-muted-foreground"
                              }
                            >
                              {lead.qualification_level}
                            </Badge>
                          ) : (
                            <span className="text-muted-foreground">{"\u2014"}</span>
                          )}
                        </TableCell>
                        <TableCell className="hidden sm:table-cell text-muted-foreground">
                          {lead.call_count}
                        </TableCell>
                        <TableCell className="hidden lg:table-cell text-muted-foreground">
                          {lead.last_call_date
                            ? format(new Date(lead.last_call_date), "MMM d, yyyy")
                            : "\u2014"}
                        </TableCell>
                        <TableCell className="hidden sm:table-cell text-muted-foreground">
                          {format(new Date(lead.created_at), "MMM d, yyyy")}
                        </TableCell>
                        <TableCell>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 w-7 p-0 text-muted-foreground hover:text-foreground"
                            onClick={(e) => {
                              e.stopPropagation();
                              openEditDialog(lead);
                            }}
                          >
                            <Pencil className="h-3.5 w-3.5" />
                          </Button>
                        </TableCell>
                      </TableRow>
                      {/* Mobile expanded detail row */}
                      {isExpanded && (
                        <TableRow className="md:hidden bg-muted/20">
                          <TableCell colSpan={10} className="py-3 px-4">
                            <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
                              <div>
                                <p className="text-xs text-muted-foreground">Email</p>
                                <p className="truncate">{lead.email || "\u2014"}</p>
                              </div>
                              <div>
                                <p className="text-xs text-muted-foreground">Company</p>
                                <p className="truncate">{lead.company || "\u2014"}</p>
                              </div>
                              <div>
                                <p className="text-xs text-muted-foreground">Qualification</p>
                                <p>{lead.qualification_level || "\u2014"}</p>
                              </div>
                              <div>
                                <p className="text-xs text-muted-foreground">Last Call</p>
                                <p>
                                  {lead.last_call_date
                                    ? format(new Date(lead.last_call_date), "MMM d, yyyy")
                                    : "\u2014"}
                                </p>
                              </div>
                              <div>
                                <p className="text-xs text-muted-foreground">Calls</p>
                                <p>{lead.call_count}</p>
                              </div>
                              <div>
                                <p className="text-xs text-muted-foreground">Created</p>
                                <p>{format(new Date(lead.created_at), "MMM d, yyyy")}</p>
                              </div>
                            </div>
                          </TableCell>
                        </TableRow>
                      )}
                        </React.Fragment>
                      );
                    })}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>

          {/* Selection Action Bar */}
          {selectedLeads.size > 0 && (
            <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 bg-background border rounded-lg shadow-lg px-4 py-3 flex items-center gap-3">
              <span className="text-sm font-medium">{selectedLeads.size} lead{selectedLeads.size > 1 ? "s" : ""} selected</span>
              <Button
                size="sm"
                variant="outline"
                onClick={() => openAction("campaign")}
              >
                <Users className="h-4 w-4 mr-1" />
                Start Campaign
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => openAction("call")}
              >
                <Phone className="h-4 w-4 mr-1" />
                Call Now
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setSelectedLeads(new Set())}
              >
                <X className="h-4 w-4" />
              </Button>
            </div>
          )}

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
            <div className="space-y-2">
              <Label htmlFor="add-tags">Tags</Label>
              <Input
                id="add-tags"
                placeholder="tag1, tag2, tag3"
                value={addForm.tags}
                onChange={(e) =>
                  setAddForm((f) => ({ ...f, tags: e.target.value }))
                }
                disabled={addSaving}
              />
              <p className="text-xs text-muted-foreground">Separate with commas</p>
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
            <div className="space-y-2">
              <Label htmlFor="edit-tags">Tags</Label>
              <Input
                id="edit-tags"
                placeholder="tag1, tag2, tag3"
                value={editForm.tags}
                onChange={(e) =>
                  setEditForm((f) => ({ ...f, tags: e.target.value }))
                }
                disabled={editSaving}
              />
              <p className="text-xs text-muted-foreground">Separate with commas</p>
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

      {/* Action Dialog (Campaign / Call) */}
      <Dialog open={actionDialogOpen} onOpenChange={setActionDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {actionType === "campaign" ? "Start Campaign" : "Queue Calls"}
            </DialogTitle>
            <DialogDescription>
              {actionType === "campaign"
                ? `Create a campaign with ${selectedLeads.size} selected lead(s)`
                : `Queue calls for ${selectedLeads.size} selected lead(s)`}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            {actionType === "campaign" && (
              <div className="space-y-2">
                <Label>Campaign Name</Label>
                <Input
                  placeholder="e.g. March Outreach"
                  value={campaignName}
                  onChange={(e) => setCampaignName(e.target.value)}
                  disabled={actionSaving}
                />
              </div>
            )}
            <div className="space-y-2">
              <Label>Select Bot</Label>
              <Select value={selectedBotId} onValueChange={setSelectedBotId}>
                <SelectTrigger>
                  <SelectValue placeholder="Choose a bot" />
                </SelectTrigger>
                <SelectContent>
                  {bots.map((bot) => (
                    <SelectItem key={bot.id} value={bot.id}>
                      {bot.agent_name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setActionDialogOpen(false)} disabled={actionSaving}>
              Cancel
            </Button>
            <Button
              onClick={handleAction}
              disabled={actionSaving}
              className="bg-gradient-to-r from-violet-500 to-indigo-600 text-white hover:from-violet-600 hover:to-indigo-700"
            >
              {actionSaving ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Processing...
                </>
              ) : actionType === "campaign" ? (
                "Create Campaign"
              ) : (
                "Queue Calls"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

    </>
  );
}
