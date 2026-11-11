import { connection } from "next/server";

// No user data, credentials, hostnames or upstream error messages are returned.
// Check the same private backend used by the proxy, including a real DB query.
export async function GET() {
  await connection();
  const unavailable = () => Response.json({ status: "unavailable" }, {
    status: 503, headers: { "cache-control": "no-store" },
  });
  try {
    const upstream = await fetch(`${process.env.API_URL ?? "http://127.0.0.1:8010"}/api/health`, {
      cache: "no-store", redirect: "error", signal: AbortSignal.timeout(5000),
    });
    if (!upstream.ok) return unavailable();
    const body = await upstream.json();
    if (body.status !== "ok" || body.database !== true) return unavailable();
    return Response.json({ status: "ready" }, { headers: { "cache-control": "no-store" } });
  } catch {
    return unavailable();
  }
}
