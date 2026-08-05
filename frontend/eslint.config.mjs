import eslint from "@eslint/js";
import eslintConfigPrettier from "eslint-config-prettier/flat";
import eslintPluginVue from "eslint-plugin-vue";
import globals from "globals";
import typescriptEslint from "typescript-eslint";

const linterOptions = {
  reportUnusedDisableDirectives: "error",
};

export default typescriptEslint.config(
  {
    ignores: ["coverage/**", "dist/**", "node_modules/**"],
  },
  {
    ...eslint.configs.recommended,
    files: ["eslint.config.mjs", "prettier.config.mjs"],
    languageOptions: {
      ecmaVersion: "latest",
      globals: globals.node,
      sourceType: "module",
    },
    linterOptions,
  },
  {
    extends: [
      eslint.configs.recommended,
      ...typescriptEslint.configs.recommended,
      ...eslintPluginVue.configs["flat/essential"],
    ],
    files: ["src/**/*.{ts,vue}", "vite.config.ts"],
    languageOptions: {
      ecmaVersion: "latest",
      parserOptions: {
        parser: typescriptEslint.parser,
      },
      sourceType: "module",
    },
    linterOptions,
    rules: {
      "@typescript-eslint/consistent-type-imports": [
        "error",
        {
          fixStyle: "inline-type-imports",
          prefer: "type-imports",
        },
      ],
      "@typescript-eslint/no-explicit-any": "error",
      eqeqeq: ["error", "always"],
      "no-console": [
        "error",
        {
          allow: ["error", "warn"],
        },
      ],
      "prefer-const": "error",
      "vue/component-api-style": ["error", ["script-setup"]],
      "vue/no-unused-properties": [
        "error",
        {
          groups: ["props", "data", "computed", "methods", "setup"],
        },
      ],
    },
  },
  {
    files: ["src/**/*.{ts,vue}"],
    languageOptions: {
      globals: globals.browser,
    },
  },
  {
    files: ["vite.config.ts"],
    languageOptions: {
      globals: globals.node,
    },
  },
  eslintConfigPrettier,
);
