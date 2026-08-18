export default {
  branches: ["main"],
  tagFormat: "v${version}",
  plugins: [
    [
      "@semantic-release/commit-analyzer",
      {
        releaseRules: [
          { type: "security", release: "patch" },
          { type: "revert", release: "patch" },
        ],
      },
    ],
    [
      "@semantic-release/release-notes-generator",
      {
        writerOpts: {
          commitsSort: ["scope", "subject"],
        },
      },
    ],
    [
      "@semantic-release/github",
      {
        failComment: false,
        releasedLabels: false,
        successComment: false,
      },
    ],
  ],
};
