"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import {
  Plus,
  Trash2,
  Copy,
  Check,
  Bot,
  Volume2,
  Clock,
  Globe,
  Languages,
  MoreVertical,
  Pencil,
} from "lucide-react";
import { toast } from "sonner";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { fetchBots, deleteBot } from "@/lib/api";
import { formatDate } from "@/lib/utils";
import { LANGUAGE_OPTIONS } from "@/lib/constants";
import type { BotConfig } from "@/types/api";

export default function BotsPage() {
  const router = useRouter();
  const [bots, setBots] = useState<BotConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const loadBots = useCallback(async () => {
    try {
      const data = await fetchBots();
      setBots(data);
    } catch {
      toast.error("Failed to load bots");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadBots();
  }, [loadBots]);

  async function handleDelete(id: string) {
    try {
      await deleteBot(id);
      toast.success("Bot deleted");
      setDeleteConfirm(null);
      loadBots();
    } catch {
      toast.error("Delete failed");
    }
  }

  function copyId(id: string) {
    navigator.clipboard.writeText(id);
    setCopiedId(id);
    toast.success("Bot ID copied");
    setTimeout(() => setCopiedId(null), 2000);
  }

  const langLabel = (code: string) =>
    LANGUAGE_OPTIONS.find((l) => l.value === code)?.label || code;

  return (
    <>
      <Header title="Bots" />
      <PageTransition>
        <div className="p-6">
          <div className="flex items-center justify-between mb-6">
            <div>
              <h2 className="text-xl font-semibold">Bot Configurations</h2>
              <p className="text-sm text-muted-foreground">
                Manage your voice agents
              </p>
            </div>
            <Button onClick={() => router.push("/bots/new")}>
              <Plus className="mr-2 h-4 w-4" />
              New Bot
            </Button>
          </div>

          {loading ? (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-48" />
              ))}
            </div>
          ) : bots.length === 0 ? (
            <Card>
              <CardContent className="flex flex-col items-center justify-center py-16">
                <Bot className="mb-3 h-12 w-12 text-muted-foreground/30" />
                <p className="text-muted-foreground mb-2">No bots configured yet</p>
                <Button variant="link" onClick={() => router.push("/bots/new")}>
                  Create your first bot
                </Button>
              </CardContent>
            </Card>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
              {bots.map((bot, i) => (
                <motion.div
                  key={bot.id}
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.06 }}
                >
                  <Card
                    className="group relative transition-colors hover:border-violet-500/50 cursor-pointer"
                    onClick={() => router.push(`/bots/${bot.id}`)}
                  >
                    <CardContent className="pt-6">
                      <div className="flex items-start justify-between mb-4">
                        <div className="flex items-center gap-3">
                          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-gradient-to-br from-violet-500 to-indigo-500 text-white font-bold text-sm">
                            {bot.agent_name.slice(0, 2).toUpperCase()}
                          </div>
                          <div>
                            <h3 className="font-semibold">{bot.agent_name}</h3>
                            <p className="text-sm text-muted-foreground">{bot.company_name}</p>
                          </div>
                        </div>
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-8 w-8 opacity-0 group-hover:opacity-100 transition-opacity"
                              onClick={(e) => e.stopPropagation()}
                            >
                              <MoreVertical className="h-4 w-4" />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            <DropdownMenuItem onClick={(e) => { e.stopPropagation(); router.push(`/bots/${bot.id}`); }}>
                              <Pencil className="mr-2 h-4 w-4" /> Edit
                            </DropdownMenuItem>
                            <DropdownMenuItem onClick={(e) => { e.stopPropagation(); copyId(bot.id); }}>
                              {copiedId === bot.id ? <Check className="mr-2 h-4 w-4 text-green-500" /> : <Copy className="mr-2 h-4 w-4" />}
                              Copy ID
                            </DropdownMenuItem>
                            <DropdownMenuItem
                              className="text-destructive"
                              onClick={(e) => {
                                e.stopPropagation();
                                deleteConfirm === bot.id ? handleDelete(bot.id) : setDeleteConfirm(bot.id);
                              }}
                            >
                              <Trash2 className="mr-2 h-4 w-4" />
                              {deleteConfirm === bot.id ? "Click to confirm" : "Delete"}
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </div>

                      <div className="flex flex-wrap gap-2 mb-4">
                        <Badge variant={bot.telephony_provider === "twilio" ? "default" : "secondary"} className="gap-1 text-xs">
                          {bot.telephony_provider === "twilio" ? "Twilio" : "Plivo"}
                        </Badge>
                        <Badge variant="outline" className="gap-1 text-xs">
                          <Volume2 className="h-3 w-3" /> {bot.tts_voice}
                        </Badge>
                        <Badge variant="outline" className="gap-1 text-xs">
                          <Languages className="h-3 w-3" /> {langLabel(bot.language)}
                        </Badge>
                        <Badge variant="outline" className="gap-1 text-xs">
                          <Clock className="h-3 w-3" /> {bot.silence_timeout_secs}s
                        </Badge>
                        {bot.location && (
                          <Badge variant="outline" className="gap-1 text-xs">
                            <Globe className="h-3 w-3" /> {bot.location}
                          </Badge>
                        )}
                      </div>

                      <p className="text-xs text-muted-foreground line-clamp-2 mb-4">
                        {bot.system_prompt_template.slice(0, 120)}
                        {bot.system_prompt_template.length > 120 ? "..." : ""}
                      </p>

                      <div className="flex items-center justify-between pt-3 border-t">
                        <Badge variant={bot.is_active ? "default" : "secondary"} className="text-[10px]">
                          {bot.is_active ? "Active" : "Inactive"}
                        </Badge>
                        <span className="text-xs text-muted-foreground">{formatDate(bot.created_at)}</span>
                      </div>
                    </CardContent>
                  </Card>
                </motion.div>
              ))}
            </div>
          )}
        </div>
      </PageTransition>
    </>
  );
}
