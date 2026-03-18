"use client";

import { useEffect, useState, useCallback } from "react";
import {
  Loader2,
  Plus,
  Trash2,
  Star,
  MessageSquare,
  Pencil,
  Wifi,
} from "lucide-react";
import { toast } from "sonner";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
  fetchProviders,
  createProvider,
  updateProvider,
  deleteProvider,
  testProvider,
  type MessagingProvider,
} from "@/lib/messaging-api";

const PROVIDER_TYPES = [
  { value: "wati", label: "WATI" },
  { value: "aisensy", label: "AISensy" },
  { value: "twilio_whatsapp", label: "Twilio WhatsApp" },
  { value: "twilio_sms", label: "Twilio SMS" },
] as const;

type ProviderType = (typeof PROVIDER_TYPES)[number]["value"];

function typeBadge(type: string) {
  const map: Record<string, string> = {
    wati: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
    aisensy: "bg-blue-500/15 text-blue-400 border-blue-500/30",
    twilio_whatsapp: "bg-violet-500/15 text-violet-400 border-violet-500/30",
    twilio_sms: "bg-orange-500/15 text-orange-400 border-orange-500/30",
  };
  const label =
    PROVIDER_TYPES.find((p) => p.value === type)?.label ?? type.toUpperCase();
  const cls = map[type] ?? "bg-muted text-muted-foreground border-border";
  return (
    <Badge className={`text-[10px] border ${cls}`}>{label}</Badge>
  );
}

interface CredentialFields {
  api_url?: string;
  api_token?: string;
  api_key?: string;
  account_sid?: string;
  auth_token?: string;
  from_number?: string;
}

const emptyCredentials = (): CredentialFields => ({
  api_url: "",
  api_token: "",
  api_key: "",
  account_sid: "",
  auth_token: "",
  from_number: "",
});

function credentialsForType(
  type: ProviderType,
  fields: CredentialFields
): Record<string, string> {
  if (type === "wati") {
    return {
      api_url: fields.api_url ?? "",
      api_token: fields.api_token ?? "",
    };
  }
  if (type === "aisensy") {
    return {
      api_url: fields.api_url ?? "",
      api_token: fields.api_token ?? "",
      api_key: fields.api_key ?? "",
    };
  }
  // twilio_whatsapp or twilio_sms
  return {
    account_sid: fields.account_sid ?? "",
    auth_token: fields.auth_token ?? "",
    from_number: fields.from_number ?? "",
  };
}

function isTwilio(type: ProviderType) {
  return type === "twilio_whatsapp" || type === "twilio_sms";
}

interface FormState {
  name: string;
  providerType: ProviderType;
  credentials: CredentialFields;
  isDefault: boolean;
}

const defaultForm = (): FormState => ({
  name: "",
  providerType: "wati",
  credentials: emptyCredentials(),
  isDefault: false,
});

export default function MessagingProvidersPage() {
  const [providers, setProviders] = useState<MessagingProvider[]>([]);
  const [loading, setLoading] = useState(true);

  // Dialog state
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<FormState>(defaultForm());
  const [saving, setSaving] = useState(false);

  // Delete confirmation
  const [deleteTarget, setDeleteTarget] = useState<MessagingProvider | null>(null);
  const [deleting, setDeleting] = useState(false);

  // Test connection per-row
  const [testingId, setTestingId] = useState<string | null>(null);

  const loadProviders = useCallback(async () => {
    try {
      const data = await fetchProviders();
      setProviders(data);
    } catch {
      toast.error("Failed to load messaging providers");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadProviders();
  }, [loadProviders]);

  function openAdd() {
    setEditingId(null);
    setForm(defaultForm());
    setDialogOpen(true);
  }

  function openEdit(provider: MessagingProvider) {
    setEditingId(provider.id);
    setForm({
      name: provider.name,
      providerType: provider.provider_type as ProviderType,
      credentials: emptyCredentials(),
      isDefault: provider.is_default,
    });
    setDialogOpen(true);
  }

  function setField<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function setCredField(key: keyof CredentialFields, value: string) {
    setForm((prev) => ({
      ...prev,
      credentials: { ...prev.credentials, [key]: value },
    }));
  }

  function handleTypeChange(type: ProviderType) {
    setForm((prev) => ({
      ...prev,
      providerType: type,
      credentials: emptyCredentials(),
    }));
  }

  async function handleSave() {
    if (!form.name.trim()) {
      toast.error("Provider name is required");
      return;
    }
    const creds = credentialsForType(form.providerType, form.credentials);
    const missingCred = Object.entries(creds).find(
      ([, v]) => !v.trim() && !editingId
    );
    if (missingCred) {
      toast.error(`${missingCred[0].replace(/_/g, " ")} is required`);
      return;
    }

    setSaving(true);
    try {
      if (editingId) {
        const payload: Parameters<typeof updateProvider>[1] = {
          name: form.name.trim(),
          is_default: form.isDefault,
        };
        // Only include credentials if any field is non-empty
        const filledCreds = Object.fromEntries(
          Object.entries(creds).filter(([, v]) => v.trim())
        );
        if (Object.keys(filledCreds).length > 0) {
          payload.credentials = filledCreds;
        }
        const updated = await updateProvider(editingId, payload);
        setProviders((prev) =>
          prev.map((p) => (p.id === editingId ? updated : p))
        );
        toast.success("Provider updated");
      } else {
        const created = await createProvider({
          provider_type: form.providerType,
          name: form.name.trim(),
          credentials: creds,
          is_default: form.isDefault,
        });
        setProviders((prev) => [...prev, created]);
        toast.success("Provider added");
      }
      setDialogOpen(false);
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Failed to save provider");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await deleteProvider(deleteTarget.id);
      setProviders((prev) => prev.filter((p) => p.id !== deleteTarget.id));
      toast.success("Provider removed");
      setDeleteTarget(null);
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Failed to delete");
    } finally {
      setDeleting(false);
    }
  }

  async function handleTest(id: string) {
    setTestingId(id);
    try {
      const result = await testProvider(id);
      if (result.success) {
        toast.success(result.message || "Connection successful");
      } else {
        toast.error(result.message || "Connection failed");
      }
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Test failed");
    } finally {
      setTestingId(null);
    }
  }

  return (
    <>
      <Header title="Messaging Providers" />
      <PageTransition>
        <div className="space-y-6 p-6">
          <div className="flex items-center justify-between">
            <p className="text-sm text-muted-foreground">
              Connect WhatsApp and SMS providers for engagement sequences
            </p>
            <Button
              onClick={openAdd}
              className="bg-gradient-to-r from-violet-500 to-indigo-600 text-white hover:from-violet-600 hover:to-indigo-700"
              size="sm"
            >
              <Plus className="h-4 w-4" />
              Add Provider
            </Button>
          </div>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <MessageSquare className="h-5 w-5 text-violet-400" />
                Configured Providers
              </CardTitle>
              <CardDescription>
                Messaging providers available for sending WhatsApp and SMS
                messages in your sequences
              </CardDescription>
            </CardHeader>
            <CardContent>
              {loading ? (
                <div className="space-y-3">
                  {Array.from({ length: 3 }).map((_, i) => (
                    <Skeleton key={i} className="h-12 w-full" />
                  ))}
                </div>
              ) : providers.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
                  <MessageSquare className="mb-3 h-10 w-10 opacity-25" />
                  <p className="text-sm font-medium">No providers configured</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Add a provider to start sending messages in sequences
                  </p>
                  <Button
                    variant="outline"
                    size="sm"
                    className="mt-4"
                    onClick={openAdd}
                  >
                    <Plus className="h-4 w-4" />
                    Add your first provider
                  </Button>
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Name</TableHead>
                      <TableHead>Type</TableHead>
                      <TableHead>Default</TableHead>
                      <TableHead>Added</TableHead>
                      <TableHead className="text-right">Actions</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {providers.map((provider) => (
                      <TableRow key={provider.id}>
                        <TableCell className="font-medium">
                          {provider.name}
                        </TableCell>
                        <TableCell>{typeBadge(provider.provider_type)}</TableCell>
                        <TableCell>
                          {provider.is_default ? (
                            <Badge className="bg-violet-500/15 text-violet-400 border border-violet-500/30 text-[10px]">
                              <Star className="h-3 w-3 mr-0.5" />
                              default
                            </Badge>
                          ) : (
                            <span className="text-xs text-muted-foreground">—</span>
                          )}
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {new Date(provider.created_at).toLocaleDateString()}
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center justify-end gap-1">
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-7 px-2 text-xs text-muted-foreground hover:text-foreground"
                              onClick={() => handleTest(provider.id)}
                              disabled={testingId === provider.id}
                            >
                              {testingId === provider.id ? (
                                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                              ) : (
                                <Wifi className="h-3.5 w-3.5" />
                              )}
                              <span className="ml-1 hidden sm:inline">Test</span>
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-7 w-7 p-0 text-muted-foreground hover:text-foreground"
                              onClick={() => openEdit(provider)}
                            >
                              <Pencil className="h-3.5 w-3.5" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-7 w-7 p-0 text-muted-foreground hover:text-destructive"
                              onClick={() => setDeleteTarget(provider)}
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </div>
      </PageTransition>

      {/* Add / Edit Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>
              {editingId ? "Edit Provider" : "Add Messaging Provider"}
            </DialogTitle>
          </DialogHeader>

          <div className="space-y-4 pt-2">
            {/* Provider Type */}
            <div className="space-y-1.5">
              <Label>Provider Type</Label>
              <Select
                value={form.providerType}
                onValueChange={(v) => handleTypeChange(v as ProviderType)}
                disabled={!!editingId}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PROVIDER_TYPES.map((pt) => (
                    <SelectItem key={pt.value} value={pt.value}>
                      {pt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {editingId && (
                <p className="text-xs text-muted-foreground">
                  Provider type cannot be changed after creation
                </p>
              )}
            </div>

            {/* Name */}
            <div className="space-y-1.5">
              <Label htmlFor="provider-name">Name</Label>
              <Input
                id="provider-name"
                placeholder="e.g. Primary WhatsApp"
                value={form.name}
                onChange={(e) => setField("name", e.target.value)}
              />
            </div>

            {/* Credentials — conditional on type */}
            {!isTwilio(form.providerType) ? (
              <>
                <div className="space-y-1.5">
                  <Label htmlFor="api-url">API URL</Label>
                  <Input
                    id="api-url"
                    placeholder="https://live-mt-server.wati.io/..."
                    value={form.credentials.api_url ?? ""}
                    onChange={(e) => setCredField("api_url", e.target.value)}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="api-token">
                    API Token
                    {editingId && (
                      <span className="ml-1 text-[10px] text-muted-foreground font-normal">
                        (leave blank to keep existing)
                      </span>
                    )}
                  </Label>
                  <Input
                    id="api-token"
                    type="password"
                    placeholder={editingId ? "••••••••" : "Bearer token"}
                    value={form.credentials.api_token ?? ""}
                    onChange={(e) => setCredField("api_token", e.target.value)}
                  />
                </div>
                {form.providerType === "aisensy" && (
                  <div className="space-y-1.5">
                    <Label htmlFor="api-key">
                      API Key
                      {editingId && (
                        <span className="ml-1 text-[10px] text-muted-foreground font-normal">
                          (leave blank to keep existing)
                        </span>
                      )}
                    </Label>
                    <Input
                      id="api-key"
                      type="password"
                      placeholder={editingId ? "••••••••" : "AISensy API key"}
                      value={form.credentials.api_key ?? ""}
                      onChange={(e) => setCredField("api_key", e.target.value)}
                    />
                  </div>
                )}
              </>
            ) : (
              <>
                <div className="space-y-1.5">
                  <Label htmlFor="account-sid">Account SID</Label>
                  <Input
                    id="account-sid"
                    placeholder="ACxxxxxxxxxxxxxxxx"
                    value={form.credentials.account_sid ?? ""}
                    onChange={(e) =>
                      setCredField("account_sid", e.target.value)
                    }
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="auth-token">
                    Auth Token
                    {editingId && (
                      <span className="ml-1 text-[10px] text-muted-foreground font-normal">
                        (leave blank to keep existing)
                      </span>
                    )}
                  </Label>
                  <Input
                    id="auth-token"
                    type="password"
                    placeholder={editingId ? "••••••••" : "Twilio auth token"}
                    value={form.credentials.auth_token ?? ""}
                    onChange={(e) => setCredField("auth_token", e.target.value)}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="from-number">From Number</Label>
                  <Input
                    id="from-number"
                    placeholder="+1234567890"
                    value={form.credentials.from_number ?? ""}
                    onChange={(e) =>
                      setCredField("from_number", e.target.value)
                    }
                  />
                </div>
              </>
            )}

            {/* Set as default */}
            <div className="flex items-center justify-between rounded-lg border p-3">
              <div>
                <p className="text-sm font-medium">Set as default</p>
                <p className="text-xs text-muted-foreground">
                  Use this provider when no specific provider is configured in a
                  sequence
                </p>
              </div>
              <Switch
                checked={form.isDefault}
                onCheckedChange={(v) => setField("isDefault", v)}
              />
            </div>

            {/* Actions */}
            <div className="flex justify-end gap-2 pt-2">
              <Button
                variant="outline"
                onClick={() => setDialogOpen(false)}
                disabled={saving}
              >
                Cancel
              </Button>
              <Button
                onClick={handleSave}
                disabled={saving}
                className="bg-gradient-to-r from-violet-500 to-indigo-600 text-white hover:from-violet-600 hover:to-indigo-700"
              >
                {saving ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Saving...
                  </>
                ) : editingId ? (
                  "Save Changes"
                ) : (
                  "Add Provider"
                )}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <Dialog
        open={!!deleteTarget}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
      >
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Remove Provider</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            Are you sure you want to remove{" "}
            <span className="font-medium text-foreground">
              {deleteTarget?.name}
            </span>
            ? This cannot be undone and may break active sequences using this
            provider.
          </p>
          <div className="flex justify-end gap-2 pt-2">
            <Button
              variant="outline"
              onClick={() => setDeleteTarget(null)}
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
                  Removing...
                </>
              ) : (
                "Remove"
              )}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
