import { screen, renderWithProviders, userEvent, waitFor, fireEvent } from "@/test/test-utils";
import { toast } from "sonner";
import { ImportExportDialog } from "../ImportExportDialog";
import { previewImport, importTemplate } from "@/lib/sequences-api";

vi.mock("@/lib/sequences-api", () => ({
  importTemplate: vi.fn(),
  previewImport: vi.fn(),
}));

const mockPreviewImport = vi.mocked(previewImport);
const mockImportTemplate = vi.mocked(importTemplate);

vi.mock("@/components/ui/dialog", () => ({
  Dialog: ({ open, children }: any) =>
    open ? <div role="dialog">{children}</div> : null,
  DialogContent: ({ children }: any) => <div>{children}</div>,
  DialogHeader: ({ children }: any) => <div>{children}</div>,
  DialogTitle: ({ children }: any) => <h2>{children}</h2>,
  DialogDescription: ({ children }: any) => <p>{children}</p>,
}));

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ImportExportDialog", () => {
  const baseExportProps = {
    isOpen: true,
    onClose: vi.fn(),
    mode: "export" as const,
    exportData: { name: "My Sequence", steps: [{ id: "s1" }] },
  };

  const baseImportProps = {
    isOpen: true,
    onClose: vi.fn(),
    mode: "import" as const,
    onImportSuccess: vi.fn(),
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("export mode", () => {
    it("shows 'Export Template' title", () => {
      renderWithProviders(<ImportExportDialog {...baseExportProps} />);

      expect(screen.getByText("Export Template")).toBeInTheDocument();
    });

    it("shows copy and download buttons", () => {
      renderWithProviders(<ImportExportDialog {...baseExportProps} />);

      expect(
        screen.getByRole("button", { name: /copy to clipboard/i }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: /download/i }),
      ).toBeInTheDocument();
    });

    it("displays formatted JSON in textarea", () => {
      renderWithProviders(<ImportExportDialog {...baseExportProps} />);

      const textarea = screen.getByRole("textbox");
      expect(textarea).toHaveValue(
        JSON.stringify(baseExportProps.exportData, null, 2),
      );
    });
  });

  describe("import mode", () => {
    it("shows 'Import Template' title", () => {
      renderWithProviders(<ImportExportDialog {...baseImportProps} />);

      expect(screen.getByText("Import Template")).toBeInTheDocument();
    });

    it("shows upload area and paste textarea", () => {
      renderWithProviders(<ImportExportDialog {...baseImportProps} />);

      expect(screen.getByText("Upload .json file")).toBeInTheDocument();
      expect(
        screen.getByPlaceholderText(/My Sequence/),
      ).toBeInTheDocument();
    });

    it("Preview and Import buttons are disabled when no text", () => {
      renderWithProviders(<ImportExportDialog {...baseImportProps} />);

      const previewBtn = screen.getByRole("button", { name: /preview/i });
      const importBtn = screen.getByRole("button", { name: /import/i });

      expect(previewBtn).toBeDisabled();
      expect(importBtn).toBeDisabled();
    });

    it("preview with valid JSON calls previewImport and shows result", async () => {
      mockPreviewImport.mockResolvedValueOnce({
        valid: true,
        template: { name: "Test", trigger_type: "manual", step_count: 3 },
        errors: [],
      });

      renderWithProviders(<ImportExportDialog {...baseImportProps} />);

      const user = userEvent.setup();
      const textarea = screen.getByPlaceholderText(/My Sequence/);
      fireEvent.change(textarea, { target: { value: '{"name":"Test","steps":[]}' } });
      await user.click(screen.getByRole("button", { name: /preview/i }));

      await waitFor(() => {
        expect(mockPreviewImport).toHaveBeenCalledWith({ name: "Test", steps: [] });
      });

      await waitFor(() => {
        expect(screen.getByText("Valid template")).toBeInTheDocument();
      });
    });

    it("import with invalid JSON shows toast.error", async () => {
      renderWithProviders(<ImportExportDialog {...baseImportProps} />);

      const user = userEvent.setup();
      const textarea = screen.getByPlaceholderText(/My Sequence/);
      fireEvent.change(textarea, { target: { value: "{bad json" } });
      await user.click(screen.getByRole("button", { name: /import/i }));

      await waitFor(() => {
        expect(toast.error).toHaveBeenCalledWith("Invalid JSON — could not parse");
      });
    });

    it("successful import calls onImportSuccess and onClose", async () => {
      mockImportTemplate.mockResolvedValueOnce({ name: "Imported Seq" } as any);

      const onImportSuccess = vi.fn();
      const onClose = vi.fn();
      renderWithProviders(
        <ImportExportDialog
          {...baseImportProps}
          onImportSuccess={onImportSuccess}
          onClose={onClose}
        />,
      );

      const user = userEvent.setup();
      const textarea = screen.getByPlaceholderText(/My Sequence/);
      fireEvent.change(textarea, { target: { value: '{"name":"Imported Seq"}' } });
      await user.click(screen.getByRole("button", { name: /import/i }));

      await waitFor(() => {
        expect(mockImportTemplate).toHaveBeenCalledWith({ name: "Imported Seq" });
      });

      await waitFor(() => {
        expect(onImportSuccess).toHaveBeenCalledWith({ name: "Imported Seq" });
      });
      expect(onClose).toHaveBeenCalled();
    });
  });
});
