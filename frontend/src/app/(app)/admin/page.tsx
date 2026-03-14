"use client";

import { useEffect, useState, useCallback, Fragment, type FormEvent } from "react";
import { motion } from "framer-motion";
import {
  Building2,
  Users,
  Bot,
  Phone,
  PhoneCall,
  ShieldAlert,
  Shield,
  Plus,
  Loader2,
  UserCog,
  Wallet,
  Pencil,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { useAuth } from "@/contexts/auth-context";
import {
  fetchAdminStats,
  fetchAdminOrgs,
  fetchAdminUsers,
  createAdminOrg,
  createAdminUser,
  updateAdminUser,
  impersonateUser,
  fetchOrgBalances,
  addCredits,
  fetchOrgSettings,
  updateOrgSettings,
  type AdminStats,
  type OrgSummary,
  type AdminUser,
} from "@/lib/api";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
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
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const STAT_GRADIENTS = [
  "from-violet-500 to-indigo-500",
  "from-emerald-500 to-green-500",
  "from-amber-500 to-orange-500",
  "from-rose-500 to-pink-500",
  "from-cyan-500 to-blue-500",
];

function StatusBadge({ status }: { status: string }) {
  const variant =
    status === "active"
      ? "default"
      : status === "inactive"
      ? "destructive"
      : "secondary";
  const className =
    status === "active"
      ? "bg-green-500/15 text-green-400 border-green-500/30 hover:bg-green-500/25"
      : status === "inactive"
      ? "bg-red-500/15 text-red-400 border-red-500/30 hover:bg-red-500/25"
      : "";
  return (
    <Badge variant={variant} className={className}>
      {status}
    </Badge>
  );
}

function PlanBadge({ plan }: { plan: string }) {
  const className =
    plan === "free"
      ? "bg-gray-500/15 text-gray-400 border-gray-500/30 hover:bg-gray-500/25"
      : plan === "pro"
      ? "bg-blue-500/15 text-blue-400 border-blue-500/30 hover:bg-blue-500/25"
      : plan === "enterprise"
      ? "bg-violet-500/15 text-violet-400 border-violet-500/30 hover:bg-violet-500/25"
      : "bg-gray-500/15 text-gray-400 border-gray-500/30 hover:bg-gray-500/25";
  return (
    <Badge variant="outline" className={className}>
      {plan}
    </Badge>
  );
}

function RoleBadge({ role }: { role: string }) {
  const className =
    role === "super_admin"
      ? "bg-red-500/15 text-red-400 border-red-500/30 hover:bg-red-500/25"
      : role === "client_admin"
      ? "bg-blue-500/15 text-blue-400 border-blue-500/30 hover:bg-blue-500/25"
      : "bg-gray-500/15 text-gray-400 border-gray-500/30 hover:bg-gray-500/25";
  return (
    <Badge variant="outline" className={className}>
      {role.replace("_", " ")}
    </Badge>
  );
}

// ── Overview Tab ──

function OverviewTab({
  stats,
  loading,
}: {
  stats: AdminStats | null;
  loading: boolean;
}) {
  const statCards = stats
    ? [
        { title: "Total Orgs", value: stats.total_orgs, icon: Building2 },
        { title: "Total Users", value: stats.total_users, icon: Users },
        { title: "Total Bots", value: stats.total_bots, icon: Bot },
        { title: "Total Calls", value: stats.total_calls, icon: Phone },
        { title: "Calls Today", value: stats.calls_today, icon: PhoneCall },
      ]
    : Array.from({ length: 5 }, (_, i) => ({
        title: ["Total Orgs", "Total Users", "Total Bots", "Total Calls", "Calls Today"][i],
        value: 0,
        icon: [Building2, Users, Bot, Phone, PhoneCall][i],
      }));

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
        {statCards.map((stat, i) => (
          <motion.div
            key={stat.title}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.08 }}
          >
            <Card>
              <CardContent className="flex items-center gap-4 pt-6">
                <div
                  className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br ${STAT_GRADIENTS[i]} text-white shadow-lg`}
                >
                  <stat.icon className="h-5 w-5" />
                </div>
                <div>
                  {loading ? (
                    <Skeleton className="h-7 w-16" />
                  ) : (
                    <p className="text-2xl font-bold">{stat.value}</p>
                  )}
                  <p className="text-sm text-muted-foreground">{stat.title}</p>
                </div>
              </CardContent>
            </Card>
          </motion.div>
        ))}
      </div>

      {stats && Array.isArray(stats.calls_by_status) && stats.calls_by_status.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Calls by Status</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-3">
              {stats.calls_by_status.map((item: { status: string; count: number }) => (
                <div
                  key={item.status}
                  className="flex items-center gap-2 rounded-lg border px-4 py-2"
                >
                  <StatusBadge status={item.status} />
                  <span className="text-lg font-semibold">{item.count}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ── Organizations Tab ──

function OrganizationsTab({
  orgs,
  loading,
  onOrgCreated,
}: {
  orgs: OrgSummary[];
  loading: boolean;
  onOrgCreated: () => void;
}) {
  const [dialogOpen, setDialogOpen] = useState(false);
  const [orgName, setOrgName] = useState("");
  const [orgPlan, setOrgPlan] = useState("free");
  const [creating, setCreating] = useState(false);
  const [expandedOrg, setExpandedOrg] = useState<string | null>(null);
  const [orgUsers, setOrgUsers] = useState<AdminUser[]>([]);
  const [loadingUsers, setLoadingUsers] = useState(false);
  const [maxConcurrent, setMaxConcurrent] = useState(15);
  const [savingConcurrent, setSavingConcurrent] = useState(false);

  async function handleCreateOrg(e: FormEvent) {
    e.preventDefault();
    if (!orgName.trim()) {
      toast.error("Please enter an organization name");
      return;
    }
    setCreating(true);
    try {
      await createAdminOrg({ name: orgName.trim(), plan: orgPlan });
      toast.success(`Organization "${orgName}" created`);
      setOrgName("");
      setOrgPlan("free");
      setDialogOpen(false);
      onOrgCreated();
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Failed to create organization";
      toast.error(message);
    } finally {
      setCreating(false);
    }
  }

  async function toggleOrgExpand(orgId: string) {
    if (expandedOrg === orgId) {
      setExpandedOrg(null);
      return;
    }
    setExpandedOrg(orgId);
    setLoadingUsers(true);
    try {
      const [users, settings] = await Promise.all([
        fetchAdminUsers(orgId),
        fetchOrgSettings(orgId),
      ]);
      setOrgUsers(users);
      setMaxConcurrent(settings.max_concurrent_calls);
    } catch {
      setOrgUsers([]);
    } finally {
      setLoadingUsers(false);
    }
  }

  async function handleSaveConcurrency(orgId: string) {
    setSavingConcurrent(true);
    try {
      await updateOrgSettings(orgId, { max_concurrent_calls: maxConcurrent });
      toast.success("Concurrency limit updated");
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Failed to update");
    } finally {
      setSavingConcurrent(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <p className="text-sm text-muted-foreground">
          All organizations on the platform
        </p>
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button className="bg-gradient-to-r from-violet-500 to-indigo-600 text-white hover:from-violet-600 hover:to-indigo-700">
              <Plus className="h-4 w-4" />
              Create Org
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Create Organization</DialogTitle>
              <DialogDescription>
                Add a new organization to the platform
              </DialogDescription>
            </DialogHeader>
            <form onSubmit={handleCreateOrg} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="orgName">Organization Name</Label>
                <Input
                  id="orgName"
                  placeholder="Acme Corp"
                  value={orgName}
                  onChange={(e) => setOrgName(e.target.value)}
                  disabled={creating}
                />
              </div>
              <div className="space-y-2">
                <Label>Plan</Label>
                <Select value={orgPlan} onValueChange={setOrgPlan}>
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="free">Free</SelectItem>
                    <SelectItem value="pro">Pro</SelectItem>
                    <SelectItem value="enterprise">Enterprise</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <DialogFooter>
                <Button type="submit" disabled={creating} className="bg-gradient-to-r from-violet-500 to-indigo-600 text-white hover:from-violet-600 hover:to-indigo-700">
                  {creating ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Creating...
                    </>
                  ) : (
                    "Create"
                  )}
                </Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
      </div>

      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="space-y-3 p-6">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : orgs.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
              <Building2 className="mb-3 h-10 w-10 opacity-30" />
              <p className="text-sm">No organizations found</p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Slug</TableHead>
                  <TableHead>Plan</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Users</TableHead>
                  <TableHead className="text-right">Bots</TableHead>
                  <TableHead className="text-right">Calls</TableHead>
                  <TableHead>Created</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {orgs.map((org) => (
                  <Fragment key={org.id}>
                    <TableRow
                      className="cursor-pointer"
                      onClick={() => toggleOrgExpand(org.id)}
                    >
                      <TableCell className="font-medium">{org.name}</TableCell>
                      <TableCell className="text-muted-foreground">
                        {org.slug}
                      </TableCell>
                      <TableCell>
                        <PlanBadge plan={org.plan} />
                      </TableCell>
                      <TableCell>
                        <StatusBadge status={org.status} />
                      </TableCell>
                      <TableCell className="text-right">{org.user_count}</TableCell>
                      <TableCell className="text-right">{org.bot_count}</TableCell>
                      <TableCell className="text-right">{org.call_count}</TableCell>
                      <TableCell className="text-muted-foreground">
                        {new Date(org.created_at).toLocaleDateString()}
                      </TableCell>
                    </TableRow>
                    {expandedOrg === org.id && (
                      <TableRow>
                        <TableCell colSpan={8} className="bg-muted/30 p-4">
                          {loadingUsers ? (
                            <div className="space-y-2">
                              {Array.from({ length: 3 }).map((_, i) => (
                                <Skeleton key={i} className="h-8 w-full" />
                              ))}
                            </div>
                          ) : orgUsers.length === 0 ? (
                            <p className="text-sm text-muted-foreground text-center py-4">
                              No users in this organization
                            </p>
                          ) : (
                            <div className="space-y-2">
                              <p className="text-sm font-medium mb-2">
                                Users in {org.name}
                              </p>
                              {orgUsers.map((u) => (
                                <div
                                  key={u.id}
                                  className="flex items-center justify-between rounded-md border p-2 bg-background"
                                >
                                  <div className="flex items-center gap-3">
                                    <div className="flex h-7 w-7 items-center justify-center rounded-full bg-violet-500/20 text-xs font-medium text-violet-400">
                                      {u.display_name.charAt(0).toUpperCase()}
                                    </div>
                                    <div>
                                      <p className="text-sm font-medium">
                                        {u.display_name}
                                      </p>
                                      <p className="text-xs text-muted-foreground">
                                        {u.email}
                                      </p>
                                    </div>
                                  </div>
                                  <RoleBadge role={u.role} />
                                </div>
                              ))}
                            </div>
                          )}
                          <div className="mt-4 pt-4 border-t">
                            <p className="text-sm font-medium mb-2">
                              Call Concurrency Limit
                            </p>
                            <div className="flex items-center gap-3">
                              <Input
                                type="number"
                                value={maxConcurrent}
                                onChange={(e) =>
                                  setMaxConcurrent(
                                    Math.max(1, Math.min(100, parseInt(e.target.value) || 1))
                                  )
                                }
                                min={1}
                                max={100}
                                className="w-24 text-center"
                              />
                              <span className="text-xs text-muted-foreground">
                                max concurrent calls
                              </span>
                              <Button
                                size="sm"
                                variant="outline"
                                disabled={savingConcurrent}
                                onClick={() => handleSaveConcurrency(org.id)}
                              >
                                {savingConcurrent ? (
                                  <Loader2 className="h-3 w-3 animate-spin" />
                                ) : (
                                  "Save"
                                )}
                              </Button>
                            </div>
                            <p className="text-xs text-muted-foreground mt-1">
                              Limits how many calls can be active at the same time across all bots in this org.
                            </p>
                          </div>
                        </TableCell>
                      </TableRow>
                    )}
                  </Fragment>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// ── Users Tab ──

function UsersTab({
  users,
  orgs,
  loading,
  onUserCreated,
}: {
  users: AdminUser[];
  orgs: OrgSummary[];
  loading: boolean;
  onUserCreated: () => void;
}) {
  const router = useRouter();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [filterOrgId, setFilterOrgId] = useState<string>("all");
  const [creating, setCreating] = useState(false);
  const [updating, setUpdating] = useState(false);
  const [impersonating, setImpersonating] = useState<string | null>(null);

  // Create user form
  const [newEmail, setNewEmail] = useState("");
  const [newDisplayName, setNewDisplayName] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newRole, setNewRole] = useState("client_user");
  const [newOrgId, setNewOrgId] = useState("");

  // Edit user form
  const [editingUser, setEditingUser] = useState<AdminUser | null>(null);
  const [editEmail, setEditEmail] = useState("");
  const [editDisplayName, setEditDisplayName] = useState("");
  const [editPassword, setEditPassword] = useState("");
  const [editRole, setEditRole] = useState("");

  const filteredUsers =
    filterOrgId === "all"
      ? users
      : users.filter((u) => u.org_id === filterOrgId);

  async function handleCreateUser(e: FormEvent) {
    e.preventDefault();
    if (!newEmail || !newDisplayName || !newPassword || !newOrgId) {
      toast.error("Please fill in all required fields");
      return;
    }
    setCreating(true);
    try {
      await createAdminUser({
        email: newEmail,
        display_name: newDisplayName,
        password: newPassword,
        role: newRole,
        org_id: newOrgId,
      });
      toast.success(`User "${newDisplayName}" created`);
      setNewEmail("");
      setNewDisplayName("");
      setNewPassword("");
      setNewRole("client_user");
      setNewOrgId("");
      setDialogOpen(false);
      onUserCreated();
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Failed to create user";
      toast.error(message);
    } finally {
      setCreating(false);
    }
  }

  async function handleImpersonate(userId: string, displayName: string) {
    setImpersonating(userId);
    try {
      const tokens = await impersonateUser(userId);
      localStorage.setItem("access_token", tokens.access_token);
      localStorage.setItem("refresh_token", tokens.refresh_token);

      // Fetch user info with new token
      const res = await fetch("/api/auth/me", {
        headers: { Authorization: `Bearer ${tokens.access_token}` },
      });
      if (res.ok) {
        const userData = await res.json();
        localStorage.setItem("auth_user", JSON.stringify(userData));
        toast.success(`Switched to ${userData.display_name}'s account`);
      } else {
        toast.success(`Switched to ${displayName}'s account`);
      }

      router.push("/dashboard");
      // Force a full page reload so auth context re-initializes
      window.location.href = "/dashboard";
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Failed to impersonate user";
      toast.error(message);
      setImpersonating(null);
    }
  }

  function openEditDialog(u: AdminUser) {
    setEditingUser(u);
    setEditEmail(u.email);
    setEditDisplayName(u.display_name);
    setEditPassword("");
    setEditRole(u.role);
    setEditDialogOpen(true);
  }

  async function handleUpdateUser(e: FormEvent) {
    e.preventDefault();
    if (!editingUser) return;
    const data: { email?: string; password?: string; display_name?: string; role?: string } = {};
    if (editEmail !== editingUser.email) data.email = editEmail;
    if (editDisplayName !== editingUser.display_name) data.display_name = editDisplayName;
    if (editPassword) data.password = editPassword;
    if (editRole !== editingUser.role) data.role = editRole;
    if (Object.keys(data).length === 0) {
      toast.info("No changes to save");
      return;
    }
    setUpdating(true);
    try {
      await updateAdminUser(editingUser.id, data);
      toast.success(`User "${editDisplayName}" updated`);
      setEditDialogOpen(false);
      setEditingUser(null);
      onUserCreated();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Failed to update user";
      toast.error(message);
    } finally {
      setUpdating(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3">
        <div className="flex items-center gap-3">
          <p className="text-sm text-muted-foreground">All platform users</p>
          <Select value={filterOrgId} onValueChange={setFilterOrgId}>
            <SelectTrigger className="w-48">
              <SelectValue placeholder="Filter by org" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Organizations</SelectItem>
              {orgs.map((org) => (
                <SelectItem key={org.id} value={org.id}>
                  {org.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button className="bg-gradient-to-r from-violet-500 to-indigo-600 text-white hover:from-violet-600 hover:to-indigo-700">
              <Plus className="h-4 w-4" />
              Create User
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Create User</DialogTitle>
              <DialogDescription>
                Add a new user to the platform
              </DialogDescription>
            </DialogHeader>
            <form onSubmit={handleCreateUser} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="newEmail">Email</Label>
                <Input
                  id="newEmail"
                  type="email"
                  placeholder="user@example.com"
                  value={newEmail}
                  onChange={(e) => setNewEmail(e.target.value)}
                  disabled={creating}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="newDisplayName">Display Name</Label>
                <Input
                  id="newDisplayName"
                  placeholder="John Doe"
                  value={newDisplayName}
                  onChange={(e) => setNewDisplayName(e.target.value)}
                  disabled={creating}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="newPassword">Password</Label>
                <Input
                  id="newPassword"
                  type="password"
                  placeholder="Enter password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  disabled={creating}
                />
              </div>
              <div className="space-y-2">
                <Label>Role</Label>
                <Select value={newRole} onValueChange={setNewRole}>
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="client_user">Client User</SelectItem>
                    <SelectItem value="client_admin">Client Admin</SelectItem>
                    <SelectItem value="super_admin">Super Admin</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>Organization</Label>
                <Select value={newOrgId} onValueChange={setNewOrgId}>
                  <SelectTrigger className="w-full">
                    <SelectValue placeholder="Select organization" />
                  </SelectTrigger>
                  <SelectContent>
                    {orgs.map((org) => (
                      <SelectItem key={org.id} value={org.id}>
                        {org.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <DialogFooter>
                <Button type="submit" disabled={creating} className="bg-gradient-to-r from-violet-500 to-indigo-600 text-white hover:from-violet-600 hover:to-indigo-700">
                  {creating ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Creating...
                    </>
                  ) : (
                    "Create"
                  )}
                </Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
      </div>

      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="space-y-3 p-6">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : filteredUsers.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
              <Users className="mb-3 h-10 w-10 opacity-30" />
              <p className="text-sm">No users found</p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Email</TableHead>
                  <TableHead>Role</TableHead>
                  <TableHead>Organization</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Last Login</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredUsers.map((user) => (
                  <TableRow key={user.id}>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <div className="flex h-7 w-7 items-center justify-center rounded-full bg-violet-500/20 text-xs font-medium text-violet-400">
                          {user.display_name.charAt(0).toUpperCase()}
                        </div>
                        <span className="font-medium">{user.display_name}</span>
                      </div>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {user.email}
                    </TableCell>
                    <TableCell>
                      <RoleBadge role={user.role} />
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {user.org_name}
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={user.status} />
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {user.last_login_at
                        ? new Date(user.last_login_at).toLocaleDateString()
                        : "Never"}
                    </TableCell>
                    <TableCell className="text-right space-x-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => openEditDialog(user)}
                        className="text-xs"
                      >
                        <Pencil className="h-3 w-3" />
                        Edit
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={impersonating === user.id}
                        onClick={() =>
                          handleImpersonate(user.id, user.display_name)
                        }
                        className="text-xs"
                      >
                        {impersonating === user.id ? (
                          <Loader2 className="h-3 w-3 animate-spin" />
                        ) : (
                          <UserCog className="h-3 w-3" />
                        )}
                        Impersonate
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Dialog open={editDialogOpen} onOpenChange={setEditDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit User</DialogTitle>
            <DialogDescription>
              Update {editingUser?.display_name}&apos;s account details
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleUpdateUser} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="editEmail">Email</Label>
              <Input
                id="editEmail"
                type="email"
                value={editEmail}
                onChange={(e) => setEditEmail(e.target.value)}
                disabled={updating}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="editDisplayName">Display Name</Label>
              <Input
                id="editDisplayName"
                value={editDisplayName}
                onChange={(e) => setEditDisplayName(e.target.value)}
                disabled={updating}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="editPassword">
                New Password{" "}
                <span className="text-muted-foreground">(leave blank to keep current)</span>
              </Label>
              <Input
                id="editPassword"
                type="password"
                placeholder="Enter new password"
                value={editPassword}
                onChange={(e) => setEditPassword(e.target.value)}
                disabled={updating}
              />
            </div>
            <div className="space-y-2">
              <Label>Role</Label>
              <Select value={editRole} onValueChange={setEditRole}>
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="client_user">Client User</SelectItem>
                  <SelectItem value="client_admin">Client Admin</SelectItem>
                  <SelectItem value="super_admin">Super Admin</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <DialogFooter>
              <Button type="submit" disabled={updating} className="bg-gradient-to-r from-violet-500 to-indigo-600 text-white hover:from-violet-600 hover:to-indigo-700">
                {updating ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Saving...
                  </>
                ) : (
                  "Save Changes"
                )}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}

// ── Billing Tab ──

function BillingTab() {
  const [balances, setBalances] = useState<
    Array<{ org_id: string; org_name: string; credit_balance: number }>
  >([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [selectedOrg, setSelectedOrg] = useState<{
    org_id: string;
    org_name: string;
  } | null>(null);
  const [creditAmount, setCreditAmount] = useState("");
  const [creditDescription, setCreditDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const loadBalances = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchOrgBalances();
      setBalances(data);
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadBalances();
  }, [loadBalances]);

  function openAddCredits(org: { org_id: string; org_name: string }) {
    setSelectedOrg(org);
    setCreditAmount("");
    setCreditDescription("");
    setDialogOpen(true);
  }

  async function handleAddCredits(e: FormEvent) {
    e.preventDefault();
    const amount = parseFloat(creditAmount);
    if (!selectedOrg || isNaN(amount) || amount <= 0) {
      toast.error("Please enter a valid amount greater than 0");
      return;
    }
    setSubmitting(true);
    try {
      await addCredits(
        selectedOrg.org_id,
        amount,
        creditDescription.trim() || undefined
      );
      toast.success(
        `Added ${amount.toFixed(2)} credits to ${selectedOrg.org_name}`
      );
      setDialogOpen(false);
      loadBalances();
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Failed to add credits";
      toast.error(message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Manage credit balances for all organizations
      </p>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add Credits</DialogTitle>
            <DialogDescription>
              Add credits to{" "}
              <span className="font-medium text-foreground">
                {selectedOrg?.org_name}
              </span>
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleAddCredits} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="creditAmount">Amount</Label>
              <Input
                id="creditAmount"
                type="number"
                step="0.01"
                min="0.01"
                placeholder="100.00"
                value={creditAmount}
                onChange={(e) => setCreditAmount(e.target.value)}
                disabled={submitting}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="creditDescription">
                Description{" "}
                <span className="text-muted-foreground">(optional)</span>
              </Label>
              <Input
                id="creditDescription"
                placeholder="Manual top-up"
                value={creditDescription}
                onChange={(e) => setCreditDescription(e.target.value)}
                disabled={submitting}
              />
            </div>
            <DialogFooter>
              <Button
                type="submit"
                disabled={submitting}
                className="bg-gradient-to-r from-violet-500 to-indigo-600 text-white hover:from-violet-600 hover:to-indigo-700"
              >
                {submitting ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Adding...
                  </>
                ) : (
                  "Add Credits"
                )}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="space-y-3 p-6">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : balances.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
              <Wallet className="mb-3 h-10 w-10 opacity-30" />
              <p className="text-sm">No organizations found</p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Organization</TableHead>
                  <TableHead className="text-right">Credit Balance</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {balances.map((org) => (
                  <TableRow key={org.org_id}>
                    <TableCell className="font-medium">
                      {org.org_name}
                    </TableCell>
                    <TableCell className="text-right">
                      <span
                        className={`font-semibold ${
                          org.credit_balance > 0
                            ? "text-green-400"
                            : org.credit_balance === 0
                            ? "text-muted-foreground"
                            : "text-red-400"
                        }`}
                      >
                        {new Intl.NumberFormat("en-IN", {
                          minimumFractionDigits: 2,
                          maximumFractionDigits: 2,
                        }).format(org.credit_balance)}
                      </span>
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => openAddCredits(org)}
                        className="gap-1"
                      >
                        <Plus className="h-3 w-3" />
                        Add Credits
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// ── Main Admin Page ──

export default function AdminPage() {
  const { user } = useAuth();
  const isSuperAdmin = user?.role === "super_admin";

  const [stats, setStats] = useState<AdminStats | null>(null);
  const [orgs, setOrgs] = useState<OrgSummary[]>([]);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loadingStats, setLoadingStats] = useState(true);
  const [loadingOrgs, setLoadingOrgs] = useState(true);
  const [loadingUsers, setLoadingUsers] = useState(true);

  const loadStats = useCallback(async () => {
    setLoadingStats(true);
    try {
      const data = await fetchAdminStats();
      setStats(data);
    } catch {
      // silent
    } finally {
      setLoadingStats(false);
    }
  }, []);

  const loadOrgs = useCallback(async () => {
    setLoadingOrgs(true);
    try {
      const data = await fetchAdminOrgs();
      setOrgs(data);
    } catch {
      // silent
    } finally {
      setLoadingOrgs(false);
    }
  }, []);

  const loadUsers = useCallback(async () => {
    setLoadingUsers(true);
    try {
      const data = await fetchAdminUsers();
      setUsers(data);
    } catch {
      // silent
    } finally {
      setLoadingUsers(false);
    }
  }, []);

  useEffect(() => {
    if (isSuperAdmin) {
      loadStats();
      loadOrgs();
      loadUsers();
    }
  }, [isSuperAdmin, loadStats, loadOrgs, loadUsers]);

  if (!isSuperAdmin) {
    return (
      <>
        <Header title="Admin" />
        <PageTransition>
          <div className="flex flex-col items-center justify-center py-24 px-6">
            <div className="flex h-14 w-14 items-center justify-center rounded-full bg-muted mb-4">
              <ShieldAlert className="h-7 w-7 text-muted-foreground" />
            </div>
            <h2 className="text-lg font-semibold">Access restricted</h2>
            <p className="mt-1 text-sm text-muted-foreground text-center max-w-sm">
              Super admin only. You don&apos;t have permission to access the
              admin panel.
            </p>
          </div>
        </PageTransition>
      </>
    );
  }

  return (
    <>
      <Header title="Admin" />
      <PageTransition>
        <div className="space-y-6 p-6">
          <div className="flex items-center gap-2">
            <Shield className="h-5 w-5 text-violet-400" />
            <p className="text-sm text-muted-foreground">
              Super admin panel — manage all organizations and users
            </p>
          </div>

          <Tabs defaultValue="overview" className="w-full">
            <TabsList>
              <TabsTrigger value="overview">Overview</TabsTrigger>
              <TabsTrigger value="organizations">Organizations</TabsTrigger>
              <TabsTrigger value="users">Users</TabsTrigger>
              <TabsTrigger value="billing">Billing</TabsTrigger>
            </TabsList>

            <TabsContent value="overview" className="mt-4">
              <OverviewTab stats={stats} loading={loadingStats} />
            </TabsContent>

            <TabsContent value="organizations" className="mt-4">
              <OrganizationsTab
                orgs={orgs}
                loading={loadingOrgs}
                onOrgCreated={() => {
                  loadOrgs();
                  loadStats();
                }}
              />
            </TabsContent>

            <TabsContent value="users" className="mt-4">
              <UsersTab
                users={users}
                orgs={orgs}
                loading={loadingUsers}
                onUserCreated={() => {
                  loadUsers();
                  loadStats();
                }}
              />
            </TabsContent>

            <TabsContent value="billing" className="mt-4">
              <BillingTab />
            </TabsContent>
          </Tabs>
        </div>
      </PageTransition>
    </>
  );
}
