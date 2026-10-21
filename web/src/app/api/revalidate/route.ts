import { revalidatePath, revalidateTag } from "next/cache";
import { NextResponse } from "next/server";

/** POST /api/revalidate?secret=...  — 일일 파이프라인이 Supabase 적재 후 호출 */
export async function POST(req: Request) {
  const url = new URL(req.url);
  const secret = url.searchParams.get("secret") ?? req.headers.get("x-revalidate-secret");
  if (!process.env.REVALIDATE_SECRET || secret !== process.env.REVALIDATE_SECRET) {
    return NextResponse.json({ ok: false, error: "unauthorized" }, { status: 401 });
  }
  // 메인(동적 렌더 + 60초 데이터 캐시 태그) · 지점 상세 · 성능 · 이야기 · 상황 기록
  revalidateTag("board-data");
  for (const p of ["/", "/performance", "/insights", "/log", "/sites/[id]"]) revalidatePath(p, "page");
  return NextResponse.json({ ok: true, revalidated_at: new Date().toISOString() });
}
