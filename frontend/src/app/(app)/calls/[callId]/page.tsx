"use client";

import { useRef, useState, useMemo, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import { motion } from "framer-motion";
import {
  ArrowLeft,
  Play,
  Pause,
  Search,
  Clock,
  Phone,
  MessageSquare,
  BarChart3,
  Brain,
  Database,
  Download,
  AlertTriangle,
  Target,
  Volume2,
  X,
  ExternalLink,
} from "lucide-react";
import Link from "next/link";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useCallDetail } from "@/hooks/use-calls";
import { getRecordingUrl } from "@/lib/api";
import { formatDate, formatDuration, formatPhoneNumber, cn } from "@/lib/utils";
import { SEVERITY_COLORS, INTEREST_CONFIG } from "@/lib/status-config";

// ---------- Score badge ----------

function ScoreBadge({ score }: { score: number | null | undefined }) {
  if (score == null) return <span className="text-muted-foreground text-sm">-</span>;
  const color =
    score >= 80
      ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20"
      : score >= 50
        ? "bg-amber-500/10 text-amber-400 border-amber-500/20"
        : "bg-red-500/10 text-red-400 border-red-500/20";
  return (
    <Badge variant="outline" className={cn("text-sm font-semibold tabular-nums", color)}>
      {score}
    </Badge>
  );
}

// ---------- Sentiment badge ----------

const SENTIMENT_CONFIG: Record<string, { emoji: string; color: string }> = {
  positive: { emoji: "+", color: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" },
  neutral: { emoji: "~", color: "bg-slate-500/10 text-slate-400 border-slate-500/20" },
  negative: { emoji: "-", color: "bg-red-500/10 text-red-400 border-red-500/20" },
  mixed: { emoji: "+/-", color: "bg-amber-500/10 text-amber-400 border-amber-500/20" },
};

function SentimentBadge({ sentiment }: { sentiment: string | null | undefined }) {
  if (!sentiment) return <span className="text-muted-foreground text-sm">-</span>;
  const config = SENTIMENT_CONFIG[sentiment.toLowerCase()] || SENTIMENT_CONFIG.neutral;
  return (
    <Badge variant="outline" className={cn("text-xs", config.color)}>
      {config.emoji} {sentiment}
    </Badge>
  );
}

// ---------- Status badge (reuse pattern) ----------

function StatusBadge({ status }: { status: string }) {
  const colorMap: Record<string, string> = {
    completed: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
    failed: "bg-red-500/10 text-red-400 border-red-500/20",
    error: "bg-red-500/10 text-red-400 border-red-500/20",
    "in-progress": "bg-blue-500/10 text-blue-400 border-blue-500/20",
    initiated: "bg-slate-500/10 text-slate-400 border-slate-500/20",
    ringing: "bg-blue-500/10 text-blue-400 border-blue-500/20",
    "no-answer": "bg-amber-500/10 text-amber-400 border-amber-500/20",
    busy: "bg-amber-500/10 text-amber-400 border-amber-500/20",
  };
  return (
    <Badge variant="outline" className={cn("text-xs capitalize", colorMap[status] || "")}>
      {status}
    </Badge>
  );
}

// ---------- Audio Player ----------

function AudioPlayer({ callSid }: { callSid: string }) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [playbackRate, setPlaybackRate] = useState(1);

  const rates = [0.5, 0.75, 1, 1.25, 1.5, 2];

  function togglePlay() {
    if (!audioRef.current) return;
    if (playing) {
      audioRef.current.pause();
    } else {
      audioRef.current.play();
    }
    setPlaying(!playing);
  }

  function handleTimeUpdate() {
    if (audioRef.current) setCurrentTime(audioRef.current.currentTime);
  }

  function handleLoadedMetadata() {
    if (audioRef.current) setDuration(audioRef.current.duration);
  }

  function handleSeek(e: React.ChangeEvent<HTMLInputElement>) {
    const time = parseFloat(e.target.value);
    if (audioRef.current) {
      audioRef.current.currentTime = time;
      setCurrentTime(time);
    }
  }

  function changeRate(rate: number) {
    setPlaybackRate(rate);
    if (audioRef.current) audioRef.current.playbackRate = rate;
  }

  function seekTo(seconds: number) {
    if (audioRef.current) {
      audioRef.current.currentTime = seconds;
      setCurrentTime(seconds);
      if (!playing) {
        audioRef.current.play();
        setPlaying(true);
      }
    }
  }

  function fmtTime(s: number) {
    if (!isFinite(s) || isNaN(s)) return "0:00";
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return `${m}:${sec.toString().padStart(2, "0")}`;
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm flex items-center gap-2">
            <Volume2 className="h-4 w-4 text-violet-400" />
            Recording
          </CardTitle>
          <a
            href={getRecordingUrl(callSid)}
            download={`recording-${callSid}.wav`}
            className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            <Download className="h-3.5 w-3.5" />
            Download
          </a>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <audio
          ref={audioRef}
          src={getRecordingUrl(callSid)}
          preload="metadata"
          onTimeUpdate={handleTimeUpdate}
          onLoadedMetadata={handleLoadedMetadata}
          onEnded={() => setPlaying(false)}
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
        />

        <div className="flex items-center gap-3">
          <Button
            variant="outline"
            size="icon"
            className="h-9 w-9 shrink-0"
            onClick={togglePlay}
          >
            {playing ? (
              <Pause className="h-4 w-4" />
            ) : (
              <Play className="h-4 w-4 ml-0.5" />
            )}
          </Button>

          <div className="flex-1 space-y-1">
            <input
              type="range"
              min={0}
              max={duration || 0}
              step={0.1}
              value={currentTime}
              onChange={handleSeek}
              className="w-full h-1.5 rounded-full appearance-none cursor-pointer bg-muted accent-violet-500"
            />
            <div className="flex justify-between text-[10px] text-muted-foreground tabular-nums">
              <span>{fmtTime(currentTime)}</span>
              <span>{fmtTime(duration)}</span>
            </div>
          </div>
        </div>

        {/* Playback speed */}
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] text-muted-foreground mr-1">Speed</span>
          {rates.map((rate) => (
            <Button
              key={rate}
              variant={playbackRate === rate ? "default" : "outline"}
              size="sm"
              className="h-6 px-2 text-[10px]"
              onClick={() => changeRate(rate)}
            >
              {rate}x
            </Button>
          ))}
        </div>

        <p className="text-[10px] text-muted-foreground">
          Stereo recording — Left: AI, Right: User
        </p>
      </CardContent>
    </Card>
  );
}

// ---------- Transcript ----------

function Transcript({
  transcript,
  onSeekTo,
}: {
  transcript: Array<{ role: "user" | "assistant"; content: string }>;
  onSeekTo?: (seconds: number) => void;
}) {
  const [search, setSearch] = useState("");

  const filtered = useMemo(() => {
    if (!search.trim()) return transcript;
    const q = search.toLowerCase();
    return transcript.filter((t) => t.content.toLowerCase().includes(q));
  }, [transcript, search]);

  return (
    <Card className="flex flex-col h-full">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm flex items-center gap-2">
            <MessageSquare className="h-4 w-4 text-violet-400" />
            Transcript
            <span className="text-[10px] text-muted-foreground font-normal">
              ({transcript.length} turns)
            </span>
          </CardTitle>
        </div>
        <div className="relative mt-2">
          <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search transcript..."
            className="pl-8 h-8 text-xs"
          />
          {search && (
            <Button
              variant="ghost"
              size="icon"
              className="absolute right-0.5 top-1/2 -translate-y-1/2 h-6 w-6"
              onClick={() => setSearch("")}
            >
              <X className="h-3 w-3" />
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="flex-1 min-h-0">
        <ScrollArea className="h-[500px]">
          <div className="space-y-3 pr-3">
            {filtered.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-8">
                {search ? "No matching messages" : "No transcript available"}
              </p>
            ) : (
              filtered.map((entry, i) => {
                const isBot = entry.role === "assistant";
                return (
                  <motion.div
                    key={i}
                    initial={{ opacity: 0, y: 4 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.15, delay: Math.min(i * 0.02, 0.5) }}
                    className={cn(
                      "flex gap-2.5",
                      isBot ? "flex-row" : "flex-row-reverse"
                    )}
                  >
                    <div
                      className={cn(
                        "rounded-lg px-3 py-2 text-sm max-w-[85%]",
                        isBot
                          ? "bg-violet-500/10 border border-violet-500/20"
                          : "bg-muted"
                      )}
                    >
                      <div className="flex items-center gap-1.5 mb-1">
                        <Badge
                          variant={isBot ? "default" : "secondary"}
                          className="text-[9px] h-4 px-1.5"
                        >
                          {isBot ? "Bot" : "Lead"}
                        </Badge>
                        <span className="text-[10px] text-muted-foreground">
                          #{i + 1}
                        </span>
                      </div>
                      <p className="text-sm leading-relaxed">{entry.content}</p>
                    </div>
                  </motion.div>
                );
              })
            )}
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
  );
}

// ---------- Talk Ratio Bar ----------

function TalkRatioBar({ agentShare }: { agentShare: number }) {
  const botPct = Math.round(agentShare * 100);
  const leadPct = 100 - botPct;
  return (
    <div className="space-y-1.5">
      <div className="flex justify-between text-[10px] text-muted-foreground">
        <span>Bot {botPct}%</span>
        <span>Lead {leadPct}%</span>
      </div>
      <div className="h-2.5 rounded-full overflow-hidden bg-muted flex">
        <div
          className="bg-gradient-to-r from-violet-500 to-indigo-500 transition-all"
          style={{ width: `${botPct}%` }}
        />
        <div
          className="bg-gradient-to-r from-emerald-500 to-green-500 transition-all"
          style={{ width: `${leadPct}%` }}
        />
      </div>
    </div>
  );
}

// ---------- Main Page ----------

export default function CallDetailPage() {
  const params = useParams();
  const router = useRouter();
  const callId = params.callId as string;

  const { data: call, isLoading, error } = useCallDetail(callId);

  if (isLoading) {
    return (
      <>
        <Header title="Call Details" />
        <PageTransition>
          <div className="p-6 space-y-6">
            <div className="flex items-center gap-3">
              <Skeleton className="h-9 w-24" />
              <Skeleton className="h-8 w-48" />
            </div>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <div className="space-y-6">
                <Skeleton className="h-40 w-full" />
                <Skeleton className="h-96 w-full" />
              </div>
              <div className="space-y-6">
                <Skeleton className="h-48 w-full" />
                <Skeleton className="h-48 w-full" />
                <Skeleton className="h-32 w-full" />
              </div>
            </div>
          </div>
        </PageTransition>
      </>
    );
  }

  if (error || !call) {
    return (
      <>
        <Header title="Call Details" />
        <PageTransition>
          <div className="p-6">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => router.push("/call-logs")}
              className="mb-6 gap-1.5"
            >
              <ArrowLeft className="h-4 w-4" />
              Back to Call Logs
            </Button>
            <Card>
              <CardContent className="flex flex-col items-center justify-center py-16">
                <Phone className="h-12 w-12 text-muted-foreground/30 mb-3" />
                <p className="font-medium text-muted-foreground">
                  {error ? "Failed to load call details" : "Call not found"}
                </p>
                <p className="text-sm text-muted-foreground mt-1">
                  {error?.message || "The call you are looking for does not exist."}
                </p>
                <Button
                  variant="outline"
                  size="sm"
                  className="mt-4"
                  onClick={() => router.push("/call-logs")}
                >
                  Go to Call Logs
                </Button>
              </CardContent>
            </Card>
          </div>
        </PageTransition>
      </>
    );
  }

  const transcript = call.metadata?.transcript || [];
  const analytics = call.analytics;
  const metrics = call.metadata?.call_metrics;
  const interestLevel = call.metadata?.interest_level;
  const interestConfig = interestLevel ? INTEREST_CONFIG[interestLevel] : null;
  const capturedData = analytics?.captured_data;

  // Derive a simple score from captured_data or analytics
  const score =
    capturedData && typeof capturedData.score === "number"
      ? capturedData.score
      : capturedData && typeof capturedData.call_score === "number"
        ? capturedData.call_score
        : null;

  const sentiment =
    capturedData && typeof capturedData.sentiment === "string"
      ? capturedData.sentiment
      : capturedData && typeof capturedData.overall_sentiment === "string"
        ? capturedData.overall_sentiment
        : null;

  const temperature =
    capturedData && typeof capturedData.temperature === "string"
      ? capturedData.temperature
      : capturedData && typeof capturedData.lead_temperature === "string"
        ? capturedData.lead_temperature
        : null;

  const nextStep =
    capturedData && typeof capturedData.next_step === "string"
      ? capturedData.next_step
      : capturedData && typeof capturedData.next_steps === "string"
        ? capturedData.next_steps
        : null;

  const budget =
    capturedData && (capturedData.budget != null)
      ? String(capturedData.budget)
      : null;

  const objections =
    capturedData && typeof capturedData.objections === "string"
      ? capturedData.objections
      : capturedData && Array.isArray(capturedData.objections)
        ? (capturedData.objections as string[]).join(", ")
        : null;

  return (
    <>
      <Header title="Call Details" />
      <PageTransition>
        <div className="p-6 space-y-6">
          {/* Back + Header */}
          <div className="space-y-4">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => router.push("/call-logs")}
              className="gap-1.5 -ml-2"
            >
              <ArrowLeft className="h-4 w-4" />
              Back to Call Logs
            </Button>

            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex flex-col sm:flex-row sm:items-center justify-between gap-4"
            >
              <div>
                <div className="flex items-center gap-3">
                  <h1 className="text-2xl font-bold">{call.contact_name}</h1>
                  {call.contact_phone && (
                    <Button variant="outline" size="sm" className="h-7 text-xs gap-1" asChild>
                      <Link href={`/leads?search=${encodeURIComponent(call.contact_phone)}`}>
                        <ExternalLink className="h-3 w-3" />
                        View Lead
                      </Link>
                    </Button>
                  )}
                </div>
                <div className="flex items-center gap-3 mt-1 text-sm text-muted-foreground">
                  <span>{formatPhoneNumber(call.contact_phone)}</span>
                  <span className="text-muted-foreground/40">|</span>
                  <span>{formatDate(call.created_at)}</span>
                  {call.call_duration != null && (
                    <>
                      <span className="text-muted-foreground/40">|</span>
                      <span className="flex items-center gap-1">
                        <Clock className="h-3 w-3" />
                        {formatDuration(call.call_duration)}
                      </span>
                    </>
                  )}
                </div>
              </div>

              <div className="flex items-center gap-2 flex-wrap">
                <StatusBadge status={call.status} />
                {score != null && <ScoreBadge score={score as number} />}
                {sentiment && <SentimentBadge sentiment={sentiment} />}
                {interestConfig && (
                  <Badge variant="outline" className={cn("text-xs", interestConfig.color)}>
                    {interestConfig.label}
                  </Badge>
                )}
              </div>
            </motion.div>
          </div>

          {/* Two-column layout */}
          <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
            {/* LEFT COLUMN (3/5) */}
            <div className="lg:col-span-3 space-y-6">
              {/* Audio Player */}
              {call.metadata?.recording_url || call.call_sid ? (
                <motion.div
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.05 }}
                >
                  <AudioPlayer callSid={call.call_sid} />
                </motion.div>
              ) : null}

              {/* Transcript */}
              <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.1 }}
              >
                <Transcript transcript={transcript} />
              </motion.div>
            </div>

            {/* RIGHT COLUMN (2/5) */}
            <div className="lg:col-span-2 space-y-6">
              {/* AI Summary */}
              {call.summary && (
                <motion.div
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.15 }}
                >
                  <Card>
                    <CardHeader className="pb-3">
                      <CardTitle className="text-sm flex items-center gap-2">
                        <Brain className="h-4 w-4 text-violet-400" />
                        AI Summary
                      </CardTitle>
                    </CardHeader>
                    <CardContent>
                      <p className="text-sm text-muted-foreground leading-relaxed">
                        {call.summary}
                      </p>
                    </CardContent>
                  </Card>
                </motion.div>
              )}

              {/* Extracted Data */}
              <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.2 }}
              >
                <Card>
                  <CardHeader className="pb-3">
                    <CardTitle className="text-sm flex items-center gap-2">
                      <Database className="h-4 w-4 text-cyan-400" />
                      Extracted Data
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="grid grid-cols-2 gap-3">
                      <DataItem label="Interest" value={interestLevel || null} />
                      <DataItem label="Temperature" value={temperature} />
                      <DataItem label="Objections" value={objections} className="col-span-2" />
                      <DataItem label="Next Step" value={nextStep} className="col-span-2" />
                      <DataItem label="Budget" value={budget} />
                      <DataItem
                        label="Outcome"
                        value={
                          analytics?.goal_outcome
                            ? analytics.goal_outcome.replace(/_/g, " ")
                            : call.outcome || null
                        }
                      />
                    </div>

                    {/* Additional captured data (anything not already shown) */}
                    {capturedData && Object.keys(capturedData).length > 0 && (
                      <>
                        <Separator className="my-3" />
                        <div className="grid grid-cols-2 gap-2">
                          {Object.entries(capturedData)
                            .filter(
                              ([key]) =>
                                ![
                                  "score",
                                  "call_score",
                                  "sentiment",
                                  "overall_sentiment",
                                  "temperature",
                                  "lead_temperature",
                                  "next_step",
                                  "next_steps",
                                  "budget",
                                  "objections",
                                ].includes(key)
                            )
                            .map(([key, val]) => (
                              <div
                                key={key}
                                className="rounded bg-muted/50 p-2 text-xs"
                              >
                                <p className="text-muted-foreground capitalize">
                                  {key.replace(/_/g, " ")}
                                </p>
                                <p className="font-medium mt-0.5">
                                  {String(val ?? "-")}
                                </p>
                              </div>
                            ))}
                        </div>
                      </>
                    )}
                  </CardContent>
                </Card>
              </motion.div>

              {/* Sentiment Arc */}
              {transcript.length > 0 && (
                <motion.div
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.25 }}
                >
                  <Card>
                    <CardHeader className="pb-3">
                      <CardTitle className="text-sm flex items-center gap-2">
                        <BarChart3 className="h-4 w-4 text-amber-400" />
                        Conversation Flow
                      </CardTitle>
                    </CardHeader>
                    <CardContent>
                      <div className="flex items-end gap-[2px] h-12">
                        {transcript.map((entry, i) => {
                          const isBot = entry.role === "assistant";
                          const height = Math.max(
                            20,
                            Math.min(100, (entry.content.length / 200) * 100)
                          );
                          return (
                            <div
                              key={i}
                              className={cn(
                                "flex-1 rounded-t-sm transition-all min-w-[2px]",
                                isBot
                                  ? "bg-violet-500/60"
                                  : "bg-emerald-500/60"
                              )}
                              style={{ height: `${height}%` }}
                              title={`${isBot ? "Bot" : "Lead"}: ${entry.content.slice(0, 60)}...`}
                            />
                          );
                        })}
                      </div>
                      <div className="flex items-center gap-4 mt-2 text-[10px] text-muted-foreground">
                        <span className="flex items-center gap-1">
                          <span className="h-2 w-2 rounded-sm bg-violet-500/60" /> Bot
                        </span>
                        <span className="flex items-center gap-1">
                          <span className="h-2 w-2 rounded-sm bg-emerald-500/60" /> Lead
                        </span>
                      </div>
                    </CardContent>
                  </Card>
                </motion.div>
              )}

              {/* Call Metrics */}
              <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.3 }}
              >
                <Card>
                  <CardHeader className="pb-3">
                    <CardTitle className="text-sm flex items-center gap-2">
                      <Target className="h-4 w-4 text-violet-400" />
                      Call Metrics
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    {/* Talk ratio */}
                    {analytics?.agent_word_share != null && (
                      <div>
                        <p className="text-xs text-muted-foreground mb-2">Talk Ratio</p>
                        <TalkRatioBar agentShare={analytics.agent_word_share} />
                      </div>
                    )}

                    <div className="grid grid-cols-2 gap-3">
                      <MetricItem
                        label="Duration"
                        value={formatDuration(call.call_duration)}
                      />
                      <MetricItem
                        label="Turn Count"
                        value={
                          analytics?.turn_count?.toString() ??
                          metrics?.turn_count?.toString() ??
                          "-"
                        }
                      />
                      <MetricItem
                        label="Goal Type"
                        value={analytics?.goal_type || "-"}
                      />
                      <MetricItem
                        label="Outcome"
                        value={
                          analytics?.goal_outcome
                            ? analytics.goal_outcome.replace(/_/g, " ")
                            : call.outcome || "-"
                        }
                      />
                    </div>
                  </CardContent>
                </Card>
              </motion.div>

              {/* Red Flags */}
              {analytics?.has_red_flags &&
                analytics.red_flags &&
                analytics.red_flags.length > 0 && (
                  <motion.div
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.35 }}
                  >
                    <Card className="border-red-500/20">
                      <CardHeader className="pb-3">
                        <CardTitle className="text-sm flex items-center gap-2 text-red-400">
                          <AlertTriangle className="h-4 w-4" />
                          Red Flags ({analytics.red_flags.length})
                        </CardTitle>
                      </CardHeader>
                      <CardContent className="space-y-2">
                        {analytics.red_flags.map((rf, j) => (
                          <div
                            key={`${rf.id}-${j}`}
                            className="rounded bg-muted/50 p-2.5 text-xs"
                          >
                            <div className="flex items-center gap-1.5 mb-1">
                              <Badge
                                variant="outline"
                                className={cn(
                                  "text-[10px] py-0",
                                  SEVERITY_COLORS[rf.severity] || ""
                                )}
                              >
                                {rf.severity}
                              </Badge>
                              <span className="font-medium capitalize">
                                {rf.id.replace(/_/g, " ")}
                              </span>
                            </div>
                            {rf.evidence && (
                              <p className="text-muted-foreground italic mt-0.5">
                                &ldquo;{rf.evidence}&rdquo;
                              </p>
                            )}
                          </div>
                        ))}
                      </CardContent>
                    </Card>
                  </motion.div>
                )}
            </div>
          </div>
        </div>
      </PageTransition>
    </>
  );
}

// ---------- Helper components ----------

function DataItem({
  label,
  value,
  className,
}: {
  label: string;
  value: string | null;
  className?: string;
}) {
  return (
    <div className={cn("rounded bg-muted/50 p-2.5 text-xs", className)}>
      <p className="text-muted-foreground">{label}</p>
      <p className="font-medium mt-0.5 capitalize">{value || "-"}</p>
    </div>
  );
}

function MetricItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded bg-muted/50 p-2.5 text-xs">
      <p className="text-muted-foreground">{label}</p>
      <p className="font-medium mt-0.5 capitalize">{value}</p>
    </div>
  );
}
