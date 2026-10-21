import { NextResponse } from "next/server";
import { getLatestRun, getObservations, getPredictions } from "@/lib/queries";

export const revalidate = 1800;

export async function GET(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const run = await getLatestRun();
  const [obs, preds] = await Promise.all([getObservations(id, 180), getPredictions(id, run?.run_id ?? null, 400)]);
  return NextResponse.json({ site_id: id, run_id: run?.run_id ?? null, observations: obs, predictions: preds });
}
