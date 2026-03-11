"use client";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html>
      <body>
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            height: "100vh",
            fontFamily: "system-ui, sans-serif",
            background: "#0a0a0a",
            color: "#fafafa",
          }}
        >
          <h2 style={{ fontSize: 24, fontWeight: 600, marginBottom: 8 }}>
            Something went wrong
          </h2>
          <p style={{ color: "#888", marginBottom: 24, fontSize: 14 }}>
            {error.message || "An unexpected error occurred"}
          </p>
          <div style={{ display: "flex", gap: 12 }}>
            <button
              onClick={reset}
              style={{
                padding: "8px 20px",
                borderRadius: 6,
                border: "none",
                background: "#7c3aed",
                color: "#fff",
                cursor: "pointer",
                fontSize: 14,
              }}
            >
              Try again
            </button>
            <button
              onClick={() => {
                localStorage.clear();
                window.location.href = "/login";
              }}
              style={{
                padding: "8px 20px",
                borderRadius: 6,
                border: "1px solid #333",
                background: "transparent",
                color: "#ccc",
                cursor: "pointer",
                fontSize: 14,
              }}
            >
              Clear data & login
            </button>
          </div>
        </div>
      </body>
    </html>
  );
}
