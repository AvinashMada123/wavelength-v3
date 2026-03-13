"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useSearchParams } from "next/navigation";
import { motion } from "framer-motion";
import {
  Wallet,
  ArrowUpRight,
  ArrowDownRight,
  RefreshCw,
  Wrench,
  CreditCard,
  Receipt,
  Loader2,
} from "lucide-react";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  fetchCreditBalance,
  fetchCreditTransactions,
  createPaymentOrder,
  verifyPayment,
  type CreditTransaction,
  type PaginatedTransactions,
} from "@/lib/api";

const TYPE_FILTERS = ["all", "topup", "usage", "adjustment", "refund"] as const;
type TypeFilter = (typeof TYPE_FILTERS)[number];

const TYPE_BADGE_STYLES: Record<string, string> = {
  topup: "bg-green-500/15 text-green-400 border-green-500/30 hover:bg-green-500/25",
  usage: "bg-red-500/15 text-red-400 border-red-500/30 hover:bg-red-500/25",
  adjustment: "bg-yellow-500/15 text-yellow-400 border-yellow-500/30 hover:bg-yellow-500/25",
  refund: "bg-blue-500/15 text-blue-400 border-blue-500/30 hover:bg-blue-500/25",
};

const TYPE_ICONS: Record<string, typeof ArrowUpRight> = {
  topup: ArrowUpRight,
  usage: ArrowDownRight,
  adjustment: Wrench,
  refund: RefreshCw,
};

const CREDIT_PRICE = 4.5;

function TransactionTypeBadge({ type }: { type: string }) {
  const Icon = TYPE_ICONS[type] || Receipt;
  return (
    <Badge
      variant="outline"
      className={`gap-1 ${TYPE_BADGE_STYLES[type] || ""}`}
    >
      <Icon className="h-3 w-3" />
      {type}
    </Badge>
  );
}

function formatCurrency(amount: number): string {
  return new Intl.NumberFormat("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);
}

function loadCashfreeScript(): Promise<void> {
  return new Promise((resolve, reject) => {
    if (document.getElementById("cashfree-sdk")) {
      resolve();
      return;
    }
    const script = document.createElement("script");
    script.id = "cashfree-sdk";
    script.src = "https://sdk.cashfree.com/js/v3/cashfree.js";
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Failed to load Cashfree SDK"));
    document.head.appendChild(script);
  });
}

const PAGE_SIZE = 10;

export default function BillingPage() {
  const searchParams = useSearchParams();
  const [balance, setBalance] = useState<number | null>(null);
  const [transactions, setTransactions] = useState<CreditTransaction[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("all");
  const [loadingBalance, setLoadingBalance] = useState(true);
  const [loadingTxns, setLoadingTxns] = useState(true);

  // Add Credits dialog state
  const [dialogOpen, setDialogOpen] = useState(false);
  const [creditCount, setCreditCount] = useState<string>("100");
  const [phone, setPhone] = useState<string>("");
  const [paymentLoading, setPaymentLoading] = useState(false);
  const [paymentError, setPaymentError] = useState<string | null>(null);
  const [paymentSuccess, setPaymentSuccess] = useState<string | null>(null);
  const verifiedRef = useRef(false);

  const loadBalance = useCallback(async () => {
    setLoadingBalance(true);
    try {
      const data = await fetchCreditBalance();
      setBalance(data.balance);
    } catch {
      // silent
    } finally {
      setLoadingBalance(false);
    }
  }, []);

  const loadTransactions = useCallback(async () => {
    setLoadingTxns(true);
    try {
      const params: { page: number; page_size: number; type?: string } = {
        page,
        page_size: PAGE_SIZE,
      };
      if (typeFilter !== "all") params.type = typeFilter;
      const data: PaginatedTransactions = await fetchCreditTransactions(params);
      setTransactions(data.items);
      setTotal(data.total);
    } catch {
      // silent
    } finally {
      setLoadingTxns(false);
    }
  }, [page, typeFilter]);

  useEffect(() => {
    loadBalance();
  }, [loadBalance]);

  useEffect(() => {
    loadTransactions();
  }, [loadTransactions]);

  // Handle redirect-back from Cashfree: verify payment via URL param
  useEffect(() => {
    const orderId = searchParams.get("order_id");
    if (!orderId || verifiedRef.current) return;
    verifiedRef.current = true;

    (async () => {
      try {
        const result = await verifyPayment(orderId);
        if (result.status === "paid") {
          setPaymentSuccess(`Payment successful! ${result.credits} credits added.`);
          loadBalance();
          loadTransactions();
        }
      } catch {
        // silent — user can check balance manually
      }
      // Clean up URL param
      window.history.replaceState({}, "", "/billing");
    })();
  }, [searchParams, loadBalance, loadTransactions]);

  const handleAddCredits = async () => {
    const credits = parseInt(creditCount, 10);
    if (isNaN(credits) || credits < 10 || credits > 10000) {
      setPaymentError("Enter between 10 and 10,000 credits.");
      return;
    }

    setPaymentLoading(true);
    setPaymentError(null);
    setPaymentSuccess(null);

    try {
      // 1. Create order on backend
      const order = await createPaymentOrder(credits, phone || undefined);

      // 2. Load Cashfree SDK
      await loadCashfreeScript();

      // 3. Open Cashfree checkout modal
      const cashfree = (window as any).Cashfree({
        mode: order.cf_environment === "production" ? "production" : "sandbox",
      });

      setDialogOpen(false);

      const checkoutResult = await cashfree.checkout({
        paymentSessionId: order.payment_session_id,
        redirectTarget: "_modal",
      });

      // 4. After modal closes, verify payment
      if (checkoutResult.error) {
        setPaymentError(checkoutResult.error.message || "Payment was not completed.");
        return;
      }

      // Verify payment status with backend
      const verification = await verifyPayment(order.order_id);
      if (verification.status === "paid") {
        setPaymentSuccess(`Payment successful! ${verification.credits} credits added.`);
        loadBalance();
        loadTransactions();
      } else {
        setPaymentError("Payment is being processed. Your credits will be added shortly.");
      }
    } catch (err: any) {
      setPaymentError(err.message || "Something went wrong. Please try again.");
    } finally {
      setPaymentLoading(false);
    }
  };

  const creditsNum = parseInt(creditCount, 10) || 0;
  const calculatedAmount = creditsNum * CREDIT_PRICE;
  const totalPages = Math.ceil(total / PAGE_SIZE);

  return (
    <>
      <Header title="Billing" />
      <PageTransition>
        <div className="space-y-6 p-6">
          <p className="text-sm text-muted-foreground">
            Manage your credits and view transaction history
          </p>

          {/* Success / Error banners */}
          {paymentSuccess && (
            <motion.div
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              className="rounded-lg border border-green-500/30 bg-green-500/10 px-4 py-3 text-sm text-green-400"
            >
              {paymentSuccess}
            </motion.div>
          )}
          {paymentError && (
            <motion.div
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-400"
            >
              {paymentError}
            </motion.div>
          )}

          {/* Credit Balance Card */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
          >
            <Card className="relative overflow-hidden border-violet-500/20">
              <div className="absolute inset-0 bg-gradient-to-br from-violet-500/5 to-indigo-500/5" />
              <CardContent className="relative flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 pt-6">
                <div className="flex items-center gap-4">
                  <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-violet-500 to-indigo-600 text-white shadow-lg shadow-violet-500/25">
                    <Wallet className="h-7 w-7" />
                  </div>
                  <div>
                    {loadingBalance ? (
                      <Skeleton className="h-10 w-32" />
                    ) : (
                      <p className="text-4xl font-bold tracking-tight">
                        {formatCurrency(balance ?? 0)}
                      </p>
                    )}
                    <p className="text-sm text-muted-foreground">
                      Credits remaining
                    </p>
                  </div>
                </div>

                <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
                  <DialogTrigger asChild>
                    <Button
                      className="bg-gradient-to-r from-violet-500 to-indigo-600 text-white hover:from-violet-600 hover:to-indigo-700"
                      onClick={() => {
                        setPaymentError(null);
                        setPaymentSuccess(null);
                      }}
                    >
                      <CreditCard className="h-4 w-4" />
                      Add Credits
                    </Button>
                  </DialogTrigger>
                  <DialogContent className="sm:max-w-md">
                    <DialogHeader>
                      <DialogTitle>Add Credits</DialogTitle>
                      <DialogDescription>
                        Purchase credits at Rs {CREDIT_PRICE} per credit. Minimum 10, maximum 10,000.
                      </DialogDescription>
                    </DialogHeader>
                    <div className="space-y-4 py-4">
                      <div className="space-y-2">
                        <Label htmlFor="credits">Number of Credits</Label>
                        <Input
                          id="credits"
                          type="number"
                          min={10}
                          max={10000}
                          value={creditCount}
                          onChange={(e) => setCreditCount(e.target.value)}
                          placeholder="100"
                        />
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="phone">Phone Number</Label>
                        <Input
                          id="phone"
                          type="tel"
                          value={phone}
                          onChange={(e) => setPhone(e.target.value)}
                          placeholder="9876543210"
                        />
                        <p className="text-xs text-muted-foreground">
                          Required by payment gateway
                        </p>
                      </div>
                      {creditsNum >= 10 && (
                        <div className="rounded-lg border border-violet-500/20 bg-violet-500/5 px-4 py-3">
                          <div className="flex items-center justify-between">
                            <span className="text-sm text-muted-foreground">
                              {creditsNum.toLocaleString("en-IN")} credits
                            </span>
                            <span className="text-lg font-semibold">
                              Rs {formatCurrency(calculatedAmount)}
                            </span>
                          </div>
                        </div>
                      )}
                    </div>
                    <DialogFooter>
                      <Button
                        variant="outline"
                        onClick={() => setDialogOpen(false)}
                        disabled={paymentLoading}
                      >
                        Cancel
                      </Button>
                      <Button
                        onClick={handleAddCredits}
                        disabled={paymentLoading || creditsNum < 10 || creditsNum > 10000}
                        className="bg-gradient-to-r from-violet-500 to-indigo-600 text-white hover:from-violet-600 hover:to-indigo-700"
                      >
                        {paymentLoading ? (
                          <>
                            <Loader2 className="h-4 w-4 animate-spin" />
                            Processing...
                          </>
                        ) : (
                          <>
                            <CreditCard className="h-4 w-4" />
                            Pay Rs {formatCurrency(calculatedAmount)}
                          </>
                        )}
                      </Button>
                    </DialogFooter>
                  </DialogContent>
                </Dialog>
              </CardContent>
            </Card>
          </motion.div>

          {/* Transaction History */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 }}
          >
            <Card>
              <CardHeader>
                <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
                  <div>
                    <CardTitle>Transaction History</CardTitle>
                    <CardDescription>
                      {total} transaction{total !== 1 ? "s" : ""} total
                    </CardDescription>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {TYPE_FILTERS.map((filter) => (
                      <Button
                        key={filter}
                        size="sm"
                        variant={typeFilter === filter ? "default" : "outline"}
                        onClick={() => {
                          setTypeFilter(filter);
                          setPage(1);
                        }}
                        className={
                          typeFilter === filter
                            ? "bg-gradient-to-r from-violet-500 to-indigo-600 text-white hover:from-violet-600 hover:to-indigo-700"
                            : ""
                        }
                      >
                        {filter.charAt(0).toUpperCase() + filter.slice(1)}
                      </Button>
                    ))}
                  </div>
                </div>
              </CardHeader>
              <CardContent className="p-0">
                {loadingTxns ? (
                  <div className="space-y-3 p-6">
                    {Array.from({ length: 5 }).map((_, i) => (
                      <Skeleton key={i} className="h-12 w-full" />
                    ))}
                  </div>
                ) : transactions.length === 0 ? (
                  <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
                    <Receipt className="mb-3 h-10 w-10 opacity-30" />
                    <p className="text-sm">No transactions found</p>
                    {typeFilter !== "all" && (
                      <Button
                        variant="link"
                        size="sm"
                        onClick={() => {
                          setTypeFilter("all");
                          setPage(1);
                        }}
                      >
                        Clear filter
                      </Button>
                    )}
                  </div>
                ) : (
                  <>
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Date</TableHead>
                          <TableHead>Type</TableHead>
                          <TableHead>Description</TableHead>
                          <TableHead className="text-right">Amount</TableHead>
                          <TableHead className="text-right">Balance After</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {transactions.map((txn) => (
                          <TableRow key={txn.id}>
                            <TableCell className="text-muted-foreground whitespace-nowrap">
                              {new Date(txn.created_at).toLocaleDateString("en-IN", {
                                day: "numeric",
                                month: "short",
                                year: "numeric",
                              })}
                            </TableCell>
                            <TableCell>
                              <TransactionTypeBadge type={txn.type} />
                            </TableCell>
                            <TableCell className="max-w-xs truncate">
                              {txn.description}
                            </TableCell>
                            <TableCell className="text-right font-medium whitespace-nowrap">
                              <span
                                className={
                                  txn.amount >= 0
                                    ? "text-green-400"
                                    : "text-red-400"
                                }
                              >
                                {txn.amount >= 0 ? "+" : ""}
                                {formatCurrency(txn.amount)}
                              </span>
                            </TableCell>
                            <TableCell className="text-right text-muted-foreground whitespace-nowrap">
                              {formatCurrency(txn.balance_after)}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>

                    {/* Pagination */}
                    {totalPages > 1 && (
                      <div className="flex items-center justify-between border-t px-4 py-3">
                        <p className="text-sm text-muted-foreground">
                          Page {page} of {totalPages}
                        </p>
                        <div className="flex gap-2">
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={page <= 1}
                            onClick={() => setPage((p) => p - 1)}
                          >
                            Previous
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={page >= totalPages}
                            onClick={() => setPage((p) => p + 1)}
                          >
                            Next
                          </Button>
                        </div>
                      </div>
                    )}
                  </>
                )}
              </CardContent>
            </Card>
          </motion.div>
        </div>
      </PageTransition>
    </>
  );
}
