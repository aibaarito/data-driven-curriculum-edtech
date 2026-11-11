import { NextResponse, type NextRequest } from "next/server";

// Optional HTTP Basic protection for the whole UI (set DEMO_BASIC_AUTH_USER and DEMO_BASIC_AUTH_PASSWORD).
// Without them the UI is meant to be bound to 127.0.0.1 only (see README "Access").
function safeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export function proxy(request: NextRequest) {
  const user = process.env.DEMO_BASIC_AUTH_USER;
  const pass = process.env.DEMO_BASIC_AUTH_PASSWORD;
  if (!user || !pass) return NextResponse.next();
  const header = request.headers.get("authorization") ?? "";
  if (header.startsWith("Basic ")) {
    try {
      const decoded = atob(header.slice(6));
      const idx = decoded.indexOf(":");
      if (idx > 0 && safeEqual(decoded.slice(0, idx), user) && safeEqual(decoded.slice(idx + 1), pass)) {
        return NextResponse.next();
      }
    } catch {
      // Malformed base64 is an authentication failure.
    }
  }
  return new NextResponse("Требуется авторизация.", {
    status: 401,
    headers: { "WWW-Authenticate": 'Basic realm="Data-Driven Curriculum", charset="UTF-8"' },
  });
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
