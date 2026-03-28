"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  LayoutDashboard,
  Bot,
  Phone,
  ClipboardList,
  ListOrdered,
  BarChart3,
  ContactRound,
  Megaphone,
  Users,
  Settings,
  CreditCard,
  Plus,
} from "lucide-react";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";

interface NavItem {
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  href: string;

}

const NAV_ITEMS: NavItem[] = [
  { label: "Dashboard", icon: LayoutDashboard, href: "/dashboard" },
  { label: "Bots", icon: Bot, href: "/bots" },
  { label: "Calls", icon: Phone, href: "/calls" },
  { label: "Call Queue", icon: ListOrdered, href: "/queue" },
  { label: "Call Logs", icon: ClipboardList, href: "/call-logs" },
  { label: "Analytics", icon: BarChart3, href: "/analytics" },
  { label: "Leads", icon: ContactRound, href: "/leads" },
  { label: "Campaigns", icon: Megaphone, href: "/campaigns" },
  { label: "Team", icon: Users, href: "/team" },
  { label: "Settings", icon: Settings, href: "/settings" },
  { label: "Billing", icon: CreditCard, href: "/billing" },
];

const ACTION_ITEMS: NavItem[] = [
  { label: "New Bot", icon: Plus, href: "/bots/new" },
  { label: "Trigger Call", icon: Phone, href: "/calls" },
  { label: "Add Lead", icon: Plus, href: "/leads" },
  { label: "New Campaign", icon: Plus, href: "/campaigns" },
];

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const router = useRouter();

  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen((o) => !o);
      }
    };
    document.addEventListener("keydown", down);
    return () => document.removeEventListener("keydown", down);
  }, []);

  const runCommand = useCallback(
    (href: string) => {
      setOpen(false);
      router.push(href);
    },
    [router]
  );

  return (
    <CommandDialog open={open} onOpenChange={setOpen}>
      <CommandInput placeholder="Type a command or search..." />
      <CommandList>
        <CommandEmpty>No results found.</CommandEmpty>
        <CommandGroup heading="Navigation">
          {NAV_ITEMS.map((item) => (
            <CommandItem
              key={item.label}
              onSelect={() => runCommand(item.href)}
            >
              <item.icon className="mr-2 h-4 w-4" />
              <span>{item.label}</span>

            </CommandItem>
          ))}
        </CommandGroup>
        <CommandSeparator />
        <CommandGroup heading="Quick Actions">
          {ACTION_ITEMS.map((item) => (
            <CommandItem
              key={item.label}
              onSelect={() => runCommand(item.href)}
            >
              <item.icon className="mr-2 h-4 w-4" />
              <span>{item.label}</span>
            </CommandItem>
          ))}
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  );
}
