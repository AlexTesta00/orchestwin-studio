/** @type {import("prettier").Config & import("prettier-plugin-tailwindcss").PluginOptions} */
const configuration = {
  arrowParens: "always",
  bracketSameLine: false,
  endOfLine: "lf",
  plugins: ["prettier-plugin-tailwindcss"],
  printWidth: 100,
  proseWrap: "preserve",
  semi: true,
  singleAttributePerLine: false,
  singleQuote: false,
  tabWidth: 2,
  tailwindStylesheet: "./src/styles/tailwind.css",
  trailingComma: "all",
  useTabs: false,
};

export default configuration;