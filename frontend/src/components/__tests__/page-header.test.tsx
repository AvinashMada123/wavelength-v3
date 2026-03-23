import { describe, it, expect } from "vitest";
import { screen } from "@/test/test-utils";
import { renderWithProviders } from "@/test/test-utils";
import { PageHeader } from "@/components/page-header";

describe("PageHeader", () => {
  it("renders title as heading", () => {
    renderWithProviders(<PageHeader title="Dashboard" />);
    expect(screen.getByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
  });

  it("renders description when provided", () => {
    renderWithProviders(<PageHeader title="Dashboard" description="Overview of your data" />);
    expect(screen.getByText("Overview of your data")).toBeInTheDocument();
  });

  it("does not render description when omitted", () => {
    renderWithProviders(<PageHeader title="Dashboard" />);
    expect(screen.queryByText(/./i, { selector: "p" })).not.toBeInTheDocument();
  });

  it("renders children in actions area", () => {
    renderWithProviders(
      <PageHeader title="Dashboard">
        <button>Add New</button>
      </PageHeader>
    );
    expect(screen.getByRole("button", { name: "Add New" })).toBeInTheDocument();
  });

  it("applies custom className", () => {
    const { container } = renderWithProviders(<PageHeader title="Dashboard" className="my-custom-class" />);
    // The root element should contain the custom class
    expect(container.firstElementChild).toHaveClass("my-custom-class");
  });
});
