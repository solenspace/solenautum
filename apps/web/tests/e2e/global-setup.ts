import { createServer, type Server } from "node:http";

import { clerkSetup } from "@clerk/testing/playwright";
import type { FullConfig } from "@playwright/test";

// The api enforces SSRF on every URL (invariant 1) — fixture URLs from
// `:9999` hit a private CIDR. Running the full mission flow against this
// server therefore requires the api to be launched with
// `AUTUMN_URL_ALLOWLIST=127.0.0.1`. The mission-flow spec documents the
// env it expects and skips when it is missing.
const FIXTURE_PORT = 9999;

declare global {
  // eslint-disable-next-line no-var
  var __AUTUMN_FIXTURE_SERVER__: Server | undefined;
}

function bootFixtureServer(): Promise<Server> {
  return new Promise((resolve, reject) => {
    const server = createServer((req, res) => {
      const path = req.url ?? "/";
      const html = `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8"/>
    <title>Fixture page ${path}</title>
  </head>
  <body>
    <main>
      <h1>Fixture page</h1>
      <p>Path: ${path}</p>
      <p>This page is served by Autumn's e2e fixture server. Returned for
      every path on <code>:${FIXTURE_PORT}</code>.</p>
    </main>
  </body>
</html>`;
      res.writeHead(200, {
        "content-type": "text/html; charset=utf-8",
        "content-length": Buffer.byteLength(html).toString(),
      });
      res.end(html);
    });
    const onError = (err: Error) => reject(err);
    server.once("error", onError);
    server.listen(FIXTURE_PORT, "127.0.0.1", () => {
      server.removeListener("error", onError);
      resolve(server);
    });
  });
}

export default async function globalSetup(_config: FullConfig): Promise<() => Promise<void>> {
  const server = await bootFixtureServer();
  globalThis.__AUTUMN_FIXTURE_SERVER__ = server;
  if (process.env.CLERK_PUBLISHABLE_KEY && process.env.CLERK_SECRET_KEY) {
    await clerkSetup();
  }
  return async () => {
    await new Promise<void>((resolve, reject) => {
      server.close((err) => (err ? reject(err) : resolve()));
    });
    globalThis.__AUTUMN_FIXTURE_SERVER__ = undefined;
  };
}
