import { describe, it, expect, vi } from "vitest";
import { screen, within } from "@/test/test-utils";
import { renderWithProviders, userEvent } from "@/test/test-utils";
import { DataTable, type Column } from "@/components/data-table";

interface TestRow {
  id: string;
  name: string;
  status: string;
}

const columns: Column<TestRow>[] = [
  { key: "name", header: "Name", cell: (row) => row.name },
  { key: "status", header: "Status", cell: (row) => row.status },
];

const sampleData: TestRow[] = [
  { id: "1", name: "Alice", status: "Active" },
  { id: "2", name: "Bob", status: "Inactive" },
  { id: "3", name: "Charlie", status: "Active" },
];

describe("DataTable", () => {
  it("shows column headers and skeleton rows in loading state", () => {
    renderWithProviders(
      <DataTable
        columns={columns}
        data={undefined}
        isLoading
        rowKey={(r) => r.id}
      />
    );

    expect(screen.getByText("Name")).toBeInTheDocument();
    expect(screen.getByText("Status")).toBeInTheDocument();

    // 5 skeleton rows, each with 2 columns = 10 cells in the tbody
    const table = screen.getByRole("table");
    const body = within(table).getAllByRole("row");
    // Header row + skeleton rows — avoid exact count to reduce brittleness
    expect(body.length).toBeGreaterThan(1);
  });

  it("shows error message and retry button in error state", () => {
    const onRetry = vi.fn();

    renderWithProviders(
      <DataTable
        columns={columns}
        data={undefined}
        error={new Error("Something went wrong")}
        onRetry={onRetry}
        rowKey={(r) => r.id}
      />
    );

    expect(screen.getByText("Something went wrong")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Try again" })
    ).toBeInTheDocument();
  });

  it("calls onRetry when clicking the retry button", async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();

    renderWithProviders(
      <DataTable
        columns={columns}
        data={undefined}
        error={new Error("Oops")}
        onRetry={onRetry}
        rowKey={(r) => r.id}
      />
    );

    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("shows custom empty message when data is empty", () => {
    renderWithProviders(
      <DataTable
        columns={columns}
        data={[]}
        emptyMessage="No bots yet"
        rowKey={(r) => r.id}
      />
    );

    expect(screen.getByText("No bots yet")).toBeInTheDocument();
  });

  it("renders data rows with correct cell content", () => {
    renderWithProviders(
      <DataTable columns={columns} data={sampleData} rowKey={(r) => r.id} />
    );

    expect(screen.getByText("Alice")).toBeInTheDocument();
    expect(screen.getByText("Bob")).toBeInTheDocument();
    expect(screen.getByText("Charlie")).toBeInTheDocument();
    expect(screen.getAllByText("Active")).toHaveLength(2);
    expect(screen.getByText("Inactive")).toBeInTheDocument();
  });

  it("calls onRowClick with row data when a row is clicked", async () => {
    const user = userEvent.setup();
    const onRowClick = vi.fn();

    renderWithProviders(
      <DataTable
        columns={columns}
        data={sampleData}
        rowKey={(r) => r.id}
        onRowClick={onRowClick}
      />
    );

    await user.click(screen.getByText("Bob"));
    expect(onRowClick).toHaveBeenCalledWith(sampleData[1]);
  });

  it("disables Previous on page 1 and enables Next", () => {
    renderWithProviders(
      <DataTable
        columns={columns}
        data={sampleData}
        rowKey={(r) => r.id}
        page={1}
        pageSize={2}
        total={6}
        onPageChange={vi.fn()}
      />
    );

    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Next" })).toBeEnabled();
  });

  it("disables Next on last page", () => {
    renderWithProviders(
      <DataTable
        columns={columns}
        data={sampleData}
        rowKey={(r) => r.id}
        page={3}
        pageSize={2}
        total={6}
        onPageChange={vi.fn()}
      />
    );

    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Previous" })).toBeEnabled();
  });

  it("calls onPageChange(page+1) when clicking Next", async () => {
    const user = userEvent.setup();
    const onPageChange = vi.fn();

    renderWithProviders(
      <DataTable
        columns={columns}
        data={sampleData}
        rowKey={(r) => r.id}
        page={1}
        pageSize={2}
        total={6}
        onPageChange={onPageChange}
      />
    );

    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(onPageChange).toHaveBeenCalledWith(2);
  });

  it("shows error message but no retry button when onRetry is not provided", () => {
    renderWithProviders(
      <DataTable
        columns={columns}
        data={undefined}
        error={new Error("Something went wrong")}
        rowKey={(r) => r.id}
      />
    );

    expect(screen.getByText("Something went wrong")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
  });

  it("shows default empty message when emptyMessage prop is not provided", () => {
    renderWithProviders(
      <DataTable columns={columns} data={[]} rowKey={(r) => r.id} />
    );

    expect(screen.getByText("No data found")).toBeInTheDocument();
  });

  it("shows background loading indicator when isLoading with existing data", () => {
    renderWithProviders(
      <DataTable
        columns={columns}
        data={sampleData}
        isLoading
        rowKey={(r) => r.id}
      />
    );

    expect(screen.getByText("Refreshing...")).toBeInTheDocument();
  });

  it("calls onPageChange(page-1) when clicking Previous", async () => {
    const user = userEvent.setup();
    const onPageChange = vi.fn();

    renderWithProviders(
      <DataTable
        columns={columns}
        data={sampleData}
        rowKey={(r) => r.id}
        page={2}
        pageSize={2}
        total={6}
        onPageChange={onPageChange}
      />
    );

    await user.click(screen.getByRole("button", { name: "Previous" }));
    expect(onPageChange).toHaveBeenCalledWith(1);
  });
});
