import type { NextRequest } from "next/server";

// Server-side proxy from the browser to FastAPI. The API token (API_TOKEN) is added here and never reaches
// the browser. Request and response bodies are streamed, so uploads are size-limited by the backend while
// they are being received.
const API_URL = process.env.API_URL ?? "http://127.0.0.1:8010";
const FORWARD_REQUEST_HEADERS = ["content-type", "content-length", "accept", "x-admin-token"];
const FORWARD_RESPONSE_HEADERS = ["content-type", "content-disposition", "content-length", "cache-control", "x-request-id"];

async function forward(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }): Promise<Response> {
  const { path } = await ctx.params;
  if (path.some((p) => p === ".." || p.includes("\\"))) {
    return Response.json({ detail: "Некорректный путь." }, { status: 400 });
  }
  const target = `${API_URL}/api/${path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`;
  const headers = new Headers();
  for (const h of FORWARD_REQUEST_HEADERS) {
    const v = req.headers.get(h);
    if (v) headers.set(h, v);
  }
  if (process.env.API_TOKEN) headers.set("authorization", `Bearer ${process.env.API_TOKEN}`);
  const hasBody = req.method !== "GET" && req.method !== "HEAD";
  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: req.method,
      headers,
      body: hasBody ? req.body : undefined,
      // required by Node's fetch when streaming a request body
      ...(hasBody ? { duplex: "half" } : {}),
      cache: "no-store",
      redirect: "manual",
    } as RequestInit);
  } catch {
    return Response.json({ detail: "Сервер аналитики недоступен." }, { status: 502 });
  }
  const out = new Headers();
  for (const h of FORWARD_RESPONSE_HEADERS) {
    const v = upstream.headers.get(h);
    if (v) out.set(h, v);
  }
  return new Response(upstream.body, { status: upstream.status, headers: out });
}

export const GET = forward;
export const POST = forward;
export const PUT = forward;
export const DELETE = forward;
