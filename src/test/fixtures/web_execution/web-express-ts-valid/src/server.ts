import express from "express";
const app = express();
app.get("/health", (_request, response) => response.json({ status: "ok" }));
app.listen(3000, "127.0.0.1");
