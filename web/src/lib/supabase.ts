import { createClient, type SupabaseClient } from "@supabase/supabase-js";

/** 서버 컴포넌트/Route Handler 전용 — anon 키(읽기 전용, RLS). 클라이언트 번들에 포함하지 않는다. */
let cached: SupabaseClient | null = null;

export function supabase(): SupabaseClient {
  if (cached) return cached;
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !key) throw new Error("NEXT_PUBLIC_SUPABASE_URL / NEXT_PUBLIC_SUPABASE_ANON_KEY 가 설정되지 않았습니다");
  cached = createClient(url, key, { auth: { persistSession: false } });
  return cached;
}

export const SITE_ORDER = ["2011G26", "2011G56", "2020G33", "2022G05", "3008G30"] as const;
