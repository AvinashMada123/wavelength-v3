import { describe, it, expect } from "vitest";
import { screen, render } from "@testing-library/react";
import { useQueryClient } from "@tanstack/react-query";
import { QueryProvider } from "@/components/query-provider";

function QueryConsumer() {
  const client = useQueryClient();
  return <div data-testid="has-client">{client ? "yes" : "no"}</div>;
}

describe("QueryProvider", () => {
  it("renders children", () => {
    render(
      <QueryProvider>
        <div>Child content</div>
      </QueryProvider>
    );
    expect(screen.getByText("Child content")).toBeInTheDocument();
  });

  it("provides a QueryClient to children", () => {
    render(
      <QueryProvider>
        <QueryConsumer />
      </QueryProvider>
    );
    expect(screen.getByTestId("has-client")).toHaveTextContent("yes");
  });
});
