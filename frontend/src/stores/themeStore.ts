import { create } from "zustand";

type Theme = "light" | "dark";

const _stored = localStorage.getItem("ts-theme") as Theme | null;

interface ThemeState {
  theme: Theme;
  toggle: () => void;
}

export const useThemeStore = create<ThemeState>((set) => ({
  theme: _stored ?? "light",
  toggle: () =>
    set((s) => {
      const next: Theme = s.theme === "light" ? "dark" : "light";
      localStorage.setItem("ts-theme", next);
      document.documentElement.setAttribute("data-theme", next);
      return { theme: next };
    }),
}));

// Apply persisted theme immediately on module load
document.documentElement.setAttribute("data-theme", _stored ?? "light");
