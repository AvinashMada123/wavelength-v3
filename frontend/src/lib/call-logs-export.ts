import type { CallLog } from "@/types/api";

function escapeCsv(value: string): string {
  if (value.includes(",") || value.includes('"') || value.includes("\n")) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}

function fmtDate(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleString("en-IN", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatTranscript(
  transcript?: Array<{ role: string; content: string }>
): string {
  if (!transcript || transcript.length === 0) return "";
  return transcript
    .map((t) => `${t.role === "assistant" ? "AI" : "User"}: ${t.content}`)
    .join("\n");
}

const HEADERS = [
  "Contact Name",
  "Phone",
  "Status",
  "Outcome",
  "Interest Level",
  "Duration (s)",
  "Turns",
  "Summary",
  "Transcript",
  "Call SID",
  "Started At",
  "Ended At",
  "Created At",
];

function callToRow(call: CallLog): string[] {
  return [
    call.contact_name,
    call.contact_phone,
    call.status,
    call.outcome || "",
    call.metadata?.interest_level || "",
    call.call_duration?.toString() || "",
    call.metadata?.call_metrics?.turn_count?.toString() || "",
    call.summary || "",
    formatTranscript(call.metadata?.transcript),
    call.call_sid,
    fmtDate(call.started_at),
    fmtDate(call.ended_at),
    fmtDate(call.created_at),
  ];
}

export function exportCallsCSV(calls: CallLog[]) {
  const rows = [
    HEADERS.map(escapeCsv).join(","),
    ...calls.map((c) => callToRow(c).map(escapeCsv).join(",")),
  ];
  const csv = rows.join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `call-logs-${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
