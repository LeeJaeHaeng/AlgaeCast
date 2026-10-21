import { NextResponse } from "next/server";
import { getSiteStatus } from "@/lib/queries";

export const revalidate = 1800;

export async function GET() {
  const rows = await getSiteStatus();
  return NextResponse.json({ generated_at: new Date().toISOString(), sites: rows });
}
