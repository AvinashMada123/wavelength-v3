import { vi } from "vitest";
import "@testing-library/jest-dom/vitest";

// Mock next/navigation
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
  usePathname: () => "/dashboard",
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
}));

// Mock next-themes
vi.mock("next-themes", () => ({
  useTheme: () => ({ theme: "light", setTheme: vi.fn() }),
  ThemeProvider: ({ children }: { children: React.ReactNode }) => children,
}));

// Mock framer-motion to pass through children without animation
vi.mock("framer-motion", async () => {
  const actual = await vi.importActual("framer-motion");
  return {
    ...actual,
    motion: new Proxy(
      {},
      {
        get: (_target, prop) => {
          return ({
            children,
            ...rest
          }: {
            children?: React.ReactNode;
            [key: string]: unknown;
          }) => {
            const tag = typeof prop === "string" ? prop : "div";
            const { createElement } = require("react");
            // Filter out motion-specific props
            const domProps: Record<string, unknown> = {};
            for (const [key, value] of Object.entries(rest)) {
              if (
                !key.startsWith("animate") &&
                !key.startsWith("initial") &&
                !key.startsWith("exit") &&
                !key.startsWith("transition") &&
                !key.startsWith("variants") &&
                !key.startsWith("whileHover") &&
                !key.startsWith("whileTap") &&
                !key.startsWith("whileFocus") &&
                !key.startsWith("layout") &&
                key !== "style" ||
                key === "style"
              ) {
                domProps[key] = value;
              }
            }
            return createElement(tag, domProps, children);
          };
        },
      }
    ),
    AnimatePresence: ({ children }: { children: React.ReactNode }) => children,
  };
});

// Mock sonner toast
vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), {
    success: vi.fn(),
    error: vi.fn(),
    loading: vi.fn(),
    dismiss: vi.fn(),
  }),
  Toaster: () => null,
}));

// Mock IntersectionObserver
class MockIntersectionObserver {
  observe = vi.fn();
  unobserve = vi.fn();
  disconnect = vi.fn();
}
vi.stubGlobal("IntersectionObserver", MockIntersectionObserver);

// Mock matchMedia
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

// Mock ResizeObserver
class MockResizeObserver {
  observe = vi.fn();
  unobserve = vi.fn();
  disconnect = vi.fn();
}
vi.stubGlobal("ResizeObserver", MockResizeObserver);
