import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";

export default tseslint.config(
  {
    ignores: [
      "dist",
      "node_modules",
      "playwright-report",
      "test-results",
      ".pnpm-store",
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // TypeScript already resolves globals; no-undef only produces noise here.
      "no-undef": "off",
      "react-refresh/only-export-components": "off",
      // React Compiler-era rules that disagree with this non-React-Compiler codebase:
      //   - set-state-in-effect fires on 37 idiomatic "bootstrap on mount" and
      //     "reset local UI state when a dep changes" patterns — both are shown
      //     in the official React docs and are the intended use of useEffect.
      //   - preserve-manual-memoization is purely informational (React Compiler
      //     skipped one optimization opportunity) and has zero correctness or
      //     performance impact.
      "react-hooks/set-state-in-effect": "off",
      "react-hooks/preserve-manual-memoization": "off",
      "@typescript-eslint/no-explicit-any": "warn",
      "@typescript-eslint/no-unused-vars": [
        "warn",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
    },
  },
);
