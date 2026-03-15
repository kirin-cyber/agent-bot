import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function GET() {
  const hasGoogleApiKey = !!process.env.GOOGLE_API_KEY;
  const hasGoogleCseId = !!process.env.GOOGLE_CSE_ID;

  const status = hasGoogleApiKey && hasGoogleCseId ? "ok" : "degraded";

  return NextResponse.json({
    status,
    timestamp: new Date().toISOString(),
    services: {
      google_search: hasGoogleApiKey && hasGoogleCseId ? "configured" : "missing_credentials",
    },
  });
}
