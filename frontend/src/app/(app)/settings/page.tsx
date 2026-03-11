"use client";

import { useEffect, useState, useCallback, type FormEvent } from "react";
import { Loader2, Plus, Trash2, Star, Phone, Shield, Key } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "@/contexts/auth-context";
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
  fetchTelephonyConfig,
  updateTelephonyConfig,
  fetchPhoneNumbers,
  createPhoneNumber,
  updatePhoneNumber,
  deletePhoneNumber,
  type TelephonyConfig,
  type PhoneNumberEntry,
} from "@/lib/api";

export default function SettingsPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "client_admin" || user?.role === "super_admin";

  const [config, setConfig] = useState<TelephonyConfig | null>(null);
  const [phones, setPhones] = useState<PhoneNumberEntry[]>([]);
  const [loading, setLoading] = useState(true);

  // Credential form state
  const [plivoAuthId, setPlivoAuthId] = useState("");
  const [plivoAuthToken, setPlivoAuthToken] = useState("");
  const [twilioSid, setTwilioSid] = useState("");
  const [twilioToken, setTwilioToken] = useState("");
  const [ghlApiKey, setGhlApiKey] = useState("");
  const [ghlLocationId, setGhlLocationId] = useState("");
  const [savingCreds, setSavingCreds] = useState(false);

  // Phone number form
  const [newProvider, setNewProvider] = useState("plivo");
  const [newNumber, setNewNumber] = useState("");
  const [newLabel, setNewLabel] = useState("");
  const [addingPhone, setAddingPhone] = useState(false);

  const loadData = useCallback(async () => {
    try {
      const [c, p] = await Promise.all([fetchTelephonyConfig(), fetchPhoneNumbers()]);
      setConfig(c);
      setPhones(p);
      setPlivoAuthId(c.plivo_auth_id || "");
      setTwilioSid(c.twilio_account_sid || "");
      setGhlLocationId(c.ghl_location_id || "");
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isAdmin) loadData();
    else setLoading(false);
  }, [isAdmin, loadData]);

  async function handleSaveCredentials(e: FormEvent) {
    e.preventDefault();
    setSavingCreds(true);
    try {
      const updates: Record<string, string> = {};
      if (plivoAuthId) updates.plivo_auth_id = plivoAuthId;
      if (plivoAuthToken) updates.plivo_auth_token = plivoAuthToken;
      if (twilioSid) updates.twilio_account_sid = twilioSid;
      if (twilioToken) updates.twilio_auth_token = twilioToken;
      if (ghlApiKey) updates.ghl_api_key = ghlApiKey;
      if (ghlLocationId) updates.ghl_location_id = ghlLocationId;

      if (Object.keys(updates).length === 0) {
        toast.error("No changes to save");
        return;
      }

      const updated = await updateTelephonyConfig(updates);
      setConfig(updated);
      // Clear sensitive fields after save
      setPlivoAuthToken("");
      setTwilioToken("");
      setGhlApiKey("");
      toast.success("Credentials saved");
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSavingCreds(false);
    }
  }

  async function handleAddPhone(e: FormEvent) {
    e.preventDefault();
    if (!newNumber.trim()) {
      toast.error("Enter a phone number");
      return;
    }
    setAddingPhone(true);
    try {
      const phone = await createPhoneNumber({
        provider: newProvider,
        phone_number: newNumber.trim(),
        label: newLabel.trim() || undefined,
        is_default: phones.filter((p) => p.provider === newProvider).length === 0,
      });
      setPhones((prev) => [...prev, phone]);
      setNewNumber("");
      setNewLabel("");
      toast.success("Phone number added");
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Failed to add");
    } finally {
      setAddingPhone(false);
    }
  }

  async function handleSetDefault(id: string) {
    try {
      const updated = await updatePhoneNumber(id, { is_default: true });
      setPhones((prev) =>
        prev.map((p) =>
          p.provider === updated.provider
            ? { ...p, is_default: p.id === id }
            : p
        )
      );
      toast.success("Default phone number updated");
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Failed to update");
    }
  }

  async function handleDeletePhone(id: string) {
    try {
      await deletePhoneNumber(id);
      setPhones((prev) => prev.filter((p) => p.id !== id));
      toast.success("Phone number removed");
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Failed to delete");
    }
  }

  if (!isAdmin) {
    return (
      <>
        <Header title="Settings" />
        <PageTransition>
          <div className="flex flex-col items-center justify-center py-24 px-6">
            <Shield className="mb-4 h-10 w-10 text-muted-foreground opacity-30" />
            <h2 className="text-lg font-semibold">Access restricted</h2>
            <p className="mt-1 text-sm text-muted-foreground text-center max-w-sm">
              Only admins can manage organization settings.
            </p>
          </div>
        </PageTransition>
      </>
    );
  }

  return (
    <>
      <Header title="Settings" />
      <PageTransition>
        <div className="space-y-6 p-6">
          <div>
            <p className="text-sm text-muted-foreground">
              Manage your organization&apos;s telephony and integration credentials
            </p>
          </div>

          {/* Telephony Credentials */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Key className="h-5 w-5 text-violet-400" />
                API Credentials
              </CardTitle>
              <CardDescription>
                These credentials are shared across all bots in your organization
              </CardDescription>
            </CardHeader>
            <CardContent>
              {loading ? (
                <div className="space-y-4">
                  {Array.from({ length: 3 }).map((_, i) => (
                    <Skeleton key={i} className="h-10 w-full" />
                  ))}
                </div>
              ) : (
                <form onSubmit={handleSaveCredentials} className="space-y-6">
                  {/* Plivo */}
                  <div className="space-y-3">
                    <h4 className="text-sm font-semibold flex items-center gap-2">
                      Plivo
                      {config?.plivo_auth_token_set && (
                        <Badge variant="secondary" className="text-[10px]">configured</Badge>
                      )}
                    </h4>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      <div className="space-y-1">
                        <Label htmlFor="plivo_auth_id">Auth ID</Label>
                        <Input
                          id="plivo_auth_id"
                          value={plivoAuthId}
                          onChange={(e) => setPlivoAuthId(e.target.value)}
                          placeholder="Your Plivo Auth ID"
                        />
                      </div>
                      <div className="space-y-1">
                        <Label htmlFor="plivo_auth_token">Auth Token</Label>
                        <Input
                          id="plivo_auth_token"
                          type="password"
                          value={plivoAuthToken}
                          onChange={(e) => setPlivoAuthToken(e.target.value)}
                          placeholder={config?.plivo_auth_token_set ? "••••••••" : "Your Plivo Auth Token"}
                        />
                      </div>
                    </div>
                  </div>

                  {/* Twilio */}
                  <div className="space-y-3">
                    <h4 className="text-sm font-semibold flex items-center gap-2">
                      Twilio
                      {config?.twilio_auth_token_set && (
                        <Badge variant="secondary" className="text-[10px]">configured</Badge>
                      )}
                    </h4>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      <div className="space-y-1">
                        <Label htmlFor="twilio_sid">Account SID</Label>
                        <Input
                          id="twilio_sid"
                          value={twilioSid}
                          onChange={(e) => setTwilioSid(e.target.value)}
                          placeholder="Your Twilio Account SID"
                        />
                      </div>
                      <div className="space-y-1">
                        <Label htmlFor="twilio_token">Auth Token</Label>
                        <Input
                          id="twilio_token"
                          type="password"
                          value={twilioToken}
                          onChange={(e) => setTwilioToken(e.target.value)}
                          placeholder={config?.twilio_auth_token_set ? "••••••••" : "Your Twilio Auth Token"}
                        />
                      </div>
                    </div>
                  </div>

                  {/* GHL */}
                  <div className="space-y-3">
                    <h4 className="text-sm font-semibold flex items-center gap-2">
                      GoHighLevel
                      {config?.ghl_api_key_set && (
                        <Badge variant="secondary" className="text-[10px]">configured</Badge>
                      )}
                    </h4>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      <div className="space-y-1">
                        <Label htmlFor="ghl_api_key">API Key</Label>
                        <Input
                          id="ghl_api_key"
                          type="password"
                          value={ghlApiKey}
                          onChange={(e) => setGhlApiKey(e.target.value)}
                          placeholder={config?.ghl_api_key_set ? "••••••••" : "Your GHL API Key"}
                        />
                      </div>
                      <div className="space-y-1">
                        <Label htmlFor="ghl_location_id">Location ID</Label>
                        <Input
                          id="ghl_location_id"
                          value={ghlLocationId}
                          onChange={(e) => setGhlLocationId(e.target.value)}
                          placeholder="Your GHL Location ID"
                        />
                      </div>
                    </div>
                  </div>

                  <Button
                    type="submit"
                    disabled={savingCreds}
                    className="bg-gradient-to-r from-violet-500 to-indigo-600 text-white hover:from-violet-600 hover:to-indigo-700"
                  >
                    {savingCreds ? (
                      <>
                        <Loader2 className="h-4 w-4 animate-spin" />
                        Saving...
                      </>
                    ) : (
                      "Save Credentials"
                    )}
                  </Button>
                </form>
              )}
            </CardContent>
          </Card>

          {/* Phone Numbers */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Phone className="h-5 w-5 text-violet-400" />
                Phone Numbers
              </CardTitle>
              <CardDescription>
                Manage caller IDs for Plivo and Twilio. Set a default number per provider.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {loading ? (
                <div className="space-y-3">
                  {Array.from({ length: 2 }).map((_, i) => (
                    <Skeleton key={i} className="h-14 w-full" />
                  ))}
                </div>
              ) : (
                <>
                  {/* Existing numbers */}
                  {phones.length === 0 ? (
                    <div className="flex flex-col items-center justify-center py-8 text-muted-foreground">
                      <Phone className="mb-3 h-8 w-8 opacity-30" />
                      <p className="text-sm">No phone numbers configured</p>
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {phones.map((phone) => (
                        <div
                          key={phone.id}
                          className="flex items-center justify-between rounded-lg border p-3 transition-colors hover:bg-muted/50"
                        >
                          <div className="flex items-center gap-3 min-w-0">
                            <Badge variant="outline" className="text-xs shrink-0">
                              {phone.provider}
                            </Badge>
                            <div className="min-w-0">
                              <p className="text-sm font-medium font-mono">
                                {phone.phone_number}
                              </p>
                              {phone.label && (
                                <p className="text-xs text-muted-foreground">{phone.label}</p>
                              )}
                            </div>
                          </div>
                          <div className="flex items-center gap-1.5 shrink-0">
                            {phone.is_default ? (
                              <Badge className="bg-violet-500/20 text-violet-400 border-violet-500/30 text-[10px]">
                                <Star className="h-3 w-3 mr-0.5" />
                                default
                              </Badge>
                            ) : (
                              <Button
                                variant="ghost"
                                size="sm"
                                className="text-xs h-7"
                                onClick={() => handleSetDefault(phone.id)}
                              >
                                Set default
                              </Button>
                            )}
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-7 w-7 p-0 text-muted-foreground hover:text-destructive"
                              onClick={() => handleDeletePhone(phone.id)}
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </Button>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Add phone form */}
                  <form
                    onSubmit={handleAddPhone}
                    className="flex flex-col gap-3 sm:flex-row sm:items-end pt-2 border-t"
                  >
                    <div className="w-full sm:w-32 space-y-1">
                      <Label>Provider</Label>
                      <Select value={newProvider} onValueChange={setNewProvider}>
                        <SelectTrigger className="w-full">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="plivo">Plivo</SelectItem>
                          <SelectItem value="twilio">Twilio</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="flex-1 space-y-1">
                      <Label>Phone Number</Label>
                      <Input
                        value={newNumber}
                        onChange={(e) => setNewNumber(e.target.value)}
                        placeholder="+1234567890"
                        disabled={addingPhone}
                      />
                    </div>
                    <div className="w-full sm:w-36 space-y-1">
                      <Label>Label</Label>
                      <Input
                        value={newLabel}
                        onChange={(e) => setNewLabel(e.target.value)}
                        placeholder="e.g. Sales"
                        disabled={addingPhone}
                      />
                    </div>
                    <Button type="submit" disabled={addingPhone} size="sm">
                      {addingPhone ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <>
                          <Plus className="h-4 w-4" />
                          Add
                        </>
                      )}
                    </Button>
                  </form>
                </>
              )}
            </CardContent>
          </Card>
        </div>
      </PageTransition>
    </>
  );
}
