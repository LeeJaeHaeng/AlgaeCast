import { NextResponse } from "next/server";
import { getMetrics, getTransitionMetrics } from "@/lib/queries";

export const revalidate = 3600;

export async function GET() {
  const [metrics, transitions] = await Promise.all([getMetrics(), getTransitionMetrics()]);
  return NextResponse.json({ metrics, transitions });
}
