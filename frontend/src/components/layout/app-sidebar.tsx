"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutDashboard, Bot, Phone, ClipboardList, Radio, ListOrdered, BarChart3, Users, ContactRound, Megaphone, CreditCard, LogOut, Shield, Settings } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarHeader,
} from "@/components/ui/sidebar";
import { useAuth } from "@/contexts/auth-context";
import { OrgSwitcher } from "@/components/layout/org-switcher";

const navItems = [
  { title: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
  { title: "Bots", href: "/bots", icon: Bot },
  { title: "Calls", href: "/calls", icon: Phone },
  { title: "Call Queue", href: "/queue", icon: ListOrdered },
  { title: "Call Logs", href: "/call-logs", icon: ClipboardList },
  { title: "Analytics", href: "/analytics", icon: BarChart3 },
  { title: "Leads", href: "/leads", icon: ContactRound },
  { title: "Campaigns", href: "/campaigns", icon: Megaphone },
  { title: "Team", href: "/team", icon: Users },
  { title: "Settings", href: "/settings", icon: Settings },
  { title: "Billing", href: "/billing", icon: CreditCard },
];

function UserMenu() {
  const { user, logout } = useAuth();
  if (!user) return null;

  return (
    <div className="flex items-center gap-3">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-violet-500/20 text-sm font-medium text-violet-400">
        {user.display_name.charAt(0).toUpperCase()}
      </div>
      <div className="flex-1 min-w-0">
        <p className="truncate text-sm font-medium">{user.display_name}</p>
        <p className="truncate text-xs text-muted-foreground">{user.org_name}</p>
      </div>
      <button
        onClick={logout}
        className="shrink-0 rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
        title="Sign out"
      >
        <LogOut className="h-4 w-4" />
      </button>
    </div>
  );
}

export function AppSidebar() {
  const pathname = usePathname();
  const { user } = useAuth();

  const allNavItems = user?.role === "super_admin"
    ? [...navItems, { title: "Admin", href: "/admin", icon: Shield }]
    : navItems;

  return (
    <Sidebar>
      <SidebarHeader className="border-b px-4 py-3 space-y-3">
        <div className="flex items-center gap-3">
          <div className="relative flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-violet-500 to-indigo-600 shadow-lg shadow-violet-500/25">
            <Radio className="h-5 w-5 text-white" />
          </div>
          <div>
            <span className="font-bold text-lg tracking-tight">Wavelength</span>
            <p className="text-[10px] font-medium uppercase tracking-widest text-muted-foreground">
              Voice AI
            </p>
          </div>
        </div>
        <OrgSwitcher />
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupContent className="mt-2">
            <SidebarMenu>
              {allNavItems.map((item) => {
                const isActive = pathname.startsWith(item.href);
                return (
                  <SidebarMenuItem key={item.href}>
                    <SidebarMenuButton asChild isActive={isActive}>
                      <Link href={item.href}>
                        <item.icon
                          className={cn(
                            "h-4 w-4",
                            isActive && "text-violet-400"
                          )}
                        />
                        <span>{item.title}</span>
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                );
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter className="border-t p-3">
        <UserMenu />
      </SidebarFooter>
    </Sidebar>
  );
}
