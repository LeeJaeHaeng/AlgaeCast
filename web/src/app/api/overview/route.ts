import { NextResponse } from "next/server";
import { getBloomEvents, getLatestRun, getSiteStatus, leadSummary } from "@/lib/queries";

export const revalidate = 1800;

export async function GET() {
  const [status, run, events] = await Promise.all([getSiteStatus(), getLatestRun(), getBloomEvents()]);
  return NextResponse.json({ run, lead: leadSummary(events), sites: status });
}
