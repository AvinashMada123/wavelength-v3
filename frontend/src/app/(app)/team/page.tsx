"use client";

import { useEffect, useState, useCallback, type FormEvent } from "react";
import { Loader2, Send, ShieldAlert, Mail, Clock, UserPlus } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "@/contexts/auth-context";
import { createInvite, fetchInvites, type Invite } from "@/lib/api";
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

export default function TeamPage() {
  const { user } = useAuth();
  const [invites, setInvites] = useState<Invite[]>([]);
  const [loading, setLoading] = useState(true);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("client_user");
  const [sending, setSending] = useState(false);

  const isAdmin = user?.role === "client_admin" || user?.role === "super_admin";

  const loadInvites = useCallback(async () => {
    try {
      const data = await fetchInvites();
      setInvites(data);
    } catch {
      // silent — empty state will show
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isAdmin) {
      loadInvites();
    }
  }, [isAdmin, loadInvites]);

  async function handleSendInvite(e: FormEvent) {
    e.preventDefault();
    if (!inviteEmail) {
      toast.error("Please enter an email address");
      return;
    }
    setSending(true);
    try {
      await createInvite(inviteEmail, inviteRole);
      toast.success(`Invite sent to ${inviteEmail}`);
      setInviteEmail("");
      setInviteRole("client_user");
      loadInvites();
    } catch (err: unknown) {
      const message =
        err instanceof Error
          ? err.message
          : "Failed to send invite. Please try again.";
      toast.error(message);
    } finally {
      setSending(false);
    }
  }

  if (!isAdmin) {
    return (
      <>
        <Header title="Team" />
        <PageTransition>
          <div className="flex flex-col items-center justify-center py-24 px-6">
            <div className="flex h-14 w-14 items-center justify-center rounded-full bg-muted mb-4">
              <ShieldAlert className="h-7 w-7 text-muted-foreground" />
            </div>
            <h2 className="text-lg font-semibold">Access restricted</h2>
            <p className="mt-1 text-sm text-muted-foreground text-center max-w-sm">
              You don&apos;t have permission to manage the team. Contact your
              administrator for access.
            </p>
          </div>
        </PageTransition>
      </>
    );
  }

  return (
    <>
      <Header title="Team" />
      <PageTransition>
        <div className="space-y-6 p-6">
          {/* Page description */}
          <div>
            <p className="text-sm text-muted-foreground">
              Manage your team members and invitations
            </p>
          </div>

          {/* Invite Team Member */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <UserPlus className="h-5 w-5 text-violet-400" />
                Invite Team Member
              </CardTitle>
              <CardDescription>
                Send an invitation link to add a new member to your team
              </CardDescription>
            </CardHeader>
            <CardContent>
              <form
                onSubmit={handleSendInvite}
                className="flex flex-col gap-4 sm:flex-row sm:items-end"
              >
                <div className="flex-1 space-y-2">
                  <Label htmlFor="inviteEmail">Email address</Label>
                  <Input
                    id="inviteEmail"
                    type="email"
                    placeholder="teammate@example.com"
                    value={inviteEmail}
                    onChange={(e) => setInviteEmail(e.target.value)}
                    disabled={sending}
                  />
                </div>
                <div className="w-full sm:w-44 space-y-2">
                  <Label>Role</Label>
                  <Select value={inviteRole} onValueChange={setInviteRole}>
                    <SelectTrigger className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="client_user">User</SelectItem>
                      <SelectItem value="client_admin">Admin</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <Button
                  type="submit"
                  disabled={sending}
                  className="bg-gradient-to-r from-violet-500 to-indigo-600 text-white hover:from-violet-600 hover:to-indigo-700"
                >
                  {sending ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Sending...
                    </>
                  ) : (
                    <>
                      <Send className="h-4 w-4" />
                      Send Invite
                    </>
                  )}
                </Button>
              </form>
            </CardContent>
          </Card>

          {/* Pending Invitations */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Mail className="h-5 w-5 text-violet-400" />
                Pending Invitations
              </CardTitle>
              <CardDescription>
                Invitations that have been sent but not yet accepted
              </CardDescription>
            </CardHeader>
            <CardContent>
              {loading ? (
                <div className="space-y-3">
                  {Array.from({ length: 3 }).map((_, i) => (
                    <Skeleton key={i} className="h-14 w-full" />
                  ))}
                </div>
              ) : invites.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
                  <Mail className="mb-3 h-10 w-10 opacity-30" />
                  <p className="text-sm">No pending invitations</p>
                </div>
              ) : (
                <div className="space-y-2">
                  {invites.map((invite) => (
                    <div
                      key={invite.id}
                      className="flex items-center justify-between rounded-lg border p-3 transition-colors hover:bg-muted/50"
                    >
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium">
                          {invite.email}
                        </p>
                        <div className="mt-0.5 flex items-center gap-2">
                          <Badge variant="outline" className="text-xs">
                            {invite.role === "client_admin" ? "Admin" : "User"}
                          </Badge>
                          <span className="flex items-center gap-1 text-xs text-muted-foreground">
                            <Clock className="h-3 w-3" />
                            Sent{" "}
                            {new Date(invite.created_at).toLocaleDateString()}
                          </span>
                        </div>
                      </div>
                      <div className="text-xs text-muted-foreground whitespace-nowrap">
                        Expires{" "}
                        {new Date(invite.expires_at).toLocaleDateString()}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </PageTransition>
    </>
  );
}
