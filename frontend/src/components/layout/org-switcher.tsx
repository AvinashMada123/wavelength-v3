"use client";

import { useEffect, useState, useCallback } from "react";
import { Check, ChevronsUpDown, Building2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/contexts/auth-context";
import { fetchUserOrgs, type OrgMembership } from "@/lib/api";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

export function OrgSwitcher() {
  const { user, switchOrg } = useAuth();
  const [orgs, setOrgs] = useState<OrgMembership[]>([]);
  const [loading, setLoading] = useState(false);
  const [switching, setSwitching] = useState(false);

  const loadOrgs = useCallback(async () => {
    try {
      const data = await fetchUserOrgs();
      setOrgs(data);
    } catch {
      // silent
    }
  }, []);

  useEffect(() => {
    if (user) loadOrgs();
  }, [user, loadOrgs]);

  // Don't show switcher if user only has 1 org and isn't super_admin
  if (orgs.length <= 1 && user?.role !== "super_admin") return null;

  const activeOrg = orgs.find((o) => o.is_active);

  async function handleSwitch(orgId: string) {
    if (orgId === user?.org_id) return;
    setSwitching(true);
    try {
      await switchOrg(orgId);
    } catch {
      setSwitching(false);
    }
  }

  return (
    <DropdownMenu onOpenChange={(open) => { if (open) loadOrgs(); }}>
      <DropdownMenuTrigger
        className={cn(
          "flex w-full items-center gap-2 rounded-md border px-3 py-2 text-sm transition-colors",
          "hover:bg-accent focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
          switching && "pointer-events-none opacity-50"
        )}
      >
        <Building2 className="h-4 w-4 shrink-0 text-violet-400" />
        <span className="flex-1 truncate text-left font-medium">
          {activeOrg?.org_name || user?.org_name || "Select org"}
        </span>
        <ChevronsUpDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-64">
        <DropdownMenuLabel className="text-xs text-muted-foreground">
          Switch organization
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        {orgs.map((org) => (
          <DropdownMenuItem
            key={org.org_id}
            onClick={() => handleSwitch(org.org_id)}
            className="flex items-center gap-2"
          >
            <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded bg-muted text-[10px] font-bold uppercase">
              {org.org_name.charAt(0)}
            </div>
            <div className="flex-1 min-w-0">
              <p className="truncate text-sm font-medium">{org.org_name}</p>
              <p className="truncate text-[11px] text-muted-foreground">{org.role.replace("_", " ")}</p>
            </div>
            {org.is_active && (
              <Check className="h-4 w-4 shrink-0 text-violet-400" />
            )}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
