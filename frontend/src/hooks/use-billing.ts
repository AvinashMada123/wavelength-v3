"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  fetchCreditBalance,
  fetchCreditTransactions,
  createPaymentOrder,
  verifyPayment,
  addCredits,
  fetchOrgBalances,
} from "@/lib/api";

export const billingKeys = {
  balance: ["billing", "balance"] as const,
  transactions: (params?: Record<string, string | number | undefined>) =>
    ["billing", "transactions", params] as const,
  orgBalances: ["billing", "org-balances"] as const,
};

export function useCreditBalance() {
  return useQuery({
    queryKey: billingKeys.balance,
    queryFn: fetchCreditBalance,
  });
}

export function useCreditTransactions(params?: { page?: number; page_size?: number; type?: string }) {
  return useQuery({
    queryKey: billingKeys.transactions(params),
    queryFn: () => fetchCreditTransactions(params),
  });
}

export function useCreatePaymentOrder() {
  return useMutation({
    mutationFn: ({ credits, phone }: { credits: number; phone?: string }) =>
      createPaymentOrder(credits, phone),
  });
}

export function useVerifyPayment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (orderId: string) => verifyPayment(orderId),
    onSuccess: () => qc.invalidateQueries({ queryKey: billingKeys.balance }),
  });
}

export function useAddCredits() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ orgId, amount, description }: { orgId: string; amount: number; description?: string }) =>
      addCredits(orgId, amount, description),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: billingKeys.balance });
      qc.invalidateQueries({ queryKey: billingKeys.orgBalances });
    },
  });
}

export function useOrgBalances() {
  return useQuery({
    queryKey: billingKeys.orgBalances,
    queryFn: fetchOrgBalances,
  });
}
