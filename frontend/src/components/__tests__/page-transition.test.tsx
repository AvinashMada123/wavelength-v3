import { describe, it, expect } from "vitest";
import { render, screen } from "@/test/test-utils";
import { PageTransition } from "../layout/page-transition";

describe("PageTransition", () => {
  it("renders children", () => {
    render(
      <PageTransition>
        <p>Page content</p>
      </PageTransition>
    );
    expect(screen.getByText("Page content")).toBeInTheDocument();
  });

  it("renders multiple children correctly", () => {
    render(
      <PageTransition>
        <p>First</p>
        <p>Second</p>
      </PageTransition>
    );
    expect(screen.getByText("First")).toBeInTheDocument();
    expect(screen.getByText("Second")).toBeInTheDocument();
  });
});
