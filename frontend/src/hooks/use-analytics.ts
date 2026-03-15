"use client";

import { useQuery, useMutation } from "@tanstack/react-query";
import {
  fetchAnalyticsSummary,
  fetchAnalyticsOutcomes,
  fetchAnalyticsRedFlags,
  fetchAnalyticsAlerts,
  fetchAnalyticsTrends,
  fetchAnalyticsCapturedData,
  fetchDashboardAnalytics,
  fetchCostBreakdown,
  fetchLeadIntelligence,
  acknowledgeAlert,
  snoozeAlert,
} from "@/lib/api";

export const analyticsKeys = {
  all: ["analytics"] as const,
  summary: (botId: string, params?: Record<string, string | undefined>) =>
    ["analytics", "summary", botId, params] as const,
  outcomes: (botId: string, params?: Record<string, string | boolean | number | undefined>) =>
    ["analytics", "outcomes", botId, params] as const,
  redFlags: (botId: string, params?: Record<string, string | undefined>) =>
    ["analytics", "red-flags", botId, params] as const,
  alerts: (botId: string) => ["analytics", "alerts", botId] as const,
  trends: (botId: string, params?: Record<string, string | undefined>) =>
    ["analytics", "trends", botId, params] as const,
  capturedData: (botId: string, params?: Record<string, string | undefined>) =>
    ["analytics", "captured-data", botId, params] as const,
};

export function useAnalyticsSummary(
  botId: string,
  params?: { start_date?: string; end_date?: string }
) {
  return useQuery({
    queryKey: analyticsKeys.summary(botId, params),
    queryFn: () => fetchAnalyticsSummary(botId, params),
    enabled: !!botId,
  });
}

export function useAnalyticsOutcomes(
  botId: string,
  params?: { outcome?: string; has_red_flags?: boolean; page?: number; page_size?: number }
) {
  return useQuery({
    queryKey: analyticsKeys.outcomes(botId, params),
    queryFn: () => fetchAnalyticsOutcomes(botId, params),
    enabled: !!botId,
  });
}

export function useAnalyticsRedFlags(
  botId: string,
  params?: { severity?: string; flag_id?: string }
) {
  return useQuery({
    queryKey: analyticsKeys.redFlags(botId, params),
    queryFn: () => fetchAnalyticsRedFlags(botId, params),
    enabled: !!botId,
  });
}

export function useAnalyticsAlerts(botId: string) {
  return useQuery({
    queryKey: analyticsKeys.alerts(botId),
    queryFn: () => fetchAnalyticsAlerts(botId),
    enabled: !!botId,
  });
}

export function useAnalyticsTrends(
  botId: string,
  params?: { interval?: "daily" | "weekly"; start_date?: string; end_date?: string }
) {
  return useQuery({
    queryKey: analyticsKeys.trends(botId, params),
    queryFn: () => fetchAnalyticsTrends(botId, params),
    enabled: !!botId,
  });
}

export function useAnalyticsCapturedData(
  botId: string,
  params?: { start_date?: string; end_date?: string }
) {
  return useQuery({
    queryKey: analyticsKeys.capturedData(botId, params),
    queryFn: () => fetchAnalyticsCapturedData(botId, params),
    enabled: !!botId,
  });
}

export function useAcknowledgeAlert() {
  return useMutation({
    mutationFn: ({ botId, analyticsId, acknowledgedBy }: { botId: string; analyticsId: string; acknowledgedBy: string }) =>
      acknowledgeAlert(botId, analyticsId, acknowledgedBy),
  });
}

export function useSnoozeAlert() {
  return useMutation({
    mutationFn: ({ botId, analyticsId, snoozeUntil }: { botId: string; analyticsId: string; snoozeUntil: string }) =>
      snoozeAlert(botId, analyticsId, snoozeUntil),
  });
}

// --- Dashboard ---

export function useDashboardAnalytics(params?: { bot_id?: string; days?: number }) {
  return useQuery({
    queryKey: ["analytics", "dashboard", params] as const,
    queryFn: () => fetchDashboardAnalytics(params),
  });
}

export function useCostBreakdown(params?: { bot_id?: string; days?: number }) {
  return useQuery({
    queryKey: ["analytics", "cost-breakdown", params] as const,
    queryFn: () => fetchCostBreakdown(params),
  });
}

export function useLeadIntelligence(params?: { bot_id?: string; days?: number }) {
  return useQuery({
    queryKey: ["analytics", "lead-intelligence", params] as const,
    queryFn: () => fetchLeadIntelligence(params),
  });
}
