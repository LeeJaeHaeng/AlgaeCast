import { MdTable } from "@/components/MdTable";
import { firstParagraphs, parseTables, readReport } from "@/lib/reports";
import { getMetrics } from "@/lib/queries";

export const revalidate = 3600;

function Section({ file, title, pick = [0], note, highlight = false, maxRows }: { file: string; title: string; pick?: number[]; note?: string; highlight?: boolean; maxRows?: number }) {
  const md = readReport(file);
  if (!md) return null;
  const tables = parseTables(md);
  const paras = firstParagraphs(md, 4);
  return (
    <section className="card space-y-2">
      <h2 className="font-semibold">{title}</h2>
      {note && <p className="text-xs text-slate-500">{note}</p>}
      {paras.map((p, i) => (
        <p key={i} className="text-xs text-slate-600">
          {p}
        </p>
      ))}
      {pick.map((i) => (tables[i] ? <MdTable key={i} table={tables[i].table} caption={tables[i].title} highlightFirstRow={highlight} maxRows={maxRows} /> : null))}
      <p className="text-[11px] text-slate-400">출처 reports/eval/{file}</p>
    </section>
  );
}

export default async function PerformancePage() {
  const metrics = await getMetrics();
  const post = metrics.filter((m) => m.split === "posthoc2026");
  const bench = readReport("tbl_benchmark_nier.md");
  const benchN = bench?.match(/n=(\d+)/)?.[1] ?? "0";
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">성능</h1>
      <p className="text-sm text-slate-600">
        원단위 R²·NSE 는 표 첫 줄에 그대로 보고하고 민감도 표(2025 봉우리 1건 = 분산 43%)를 병기합니다. 6개 변형 × 3개 보정 실험에서 어떤 조합도 원단위 R² 0.2 를 넘지 못했습니다. 주간 샘플링 자료의 7일 예측에서 원단위 R² 는 봉우리 높이 재현을 측정하며, 운영 목적(발령 선행 판단)에는 로그 R² 0.78 과 경보 F1 이 부합합니다.
      </p>
      <Section file="tbl_holdout_2025.md" title="2025 홀드아웃 — 전 지표 + 부트스트랩 95% CI" pick={[0, 1]} highlight />
      <section className="card">
        <h2 className="font-semibold">2026 사후 검증 열 (모델 동결 후, 선택·튜닝 미사용)</h2>
        <table className="tbl mt-2">
          <thead>
            <tr>
              <th>지표</th>
              <th>값</th>
            </tr>
          </thead>
          <tbody>
            {post.map((m) => (
              <tr key={m.metric}>
                <td>{m.metric}</td>
                <td>{m.value?.toFixed(3)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="text-[11px] text-slate-400">출처 model_metrics(split=posthoc2026), reports/eval/tbl_holdout_2026_posthoc.md</p>
      </section>
      <Section file="tbl_transitions.md" title="상태 전환 구간 평가 (진입 Recall 이 핵심)" pick={[0]} maxRows={14} />
      <Section file="tbl_leadtime.md" title="리드타임 — 경계 발령 사건 (2020~2025)" pick={[0]} />
      <Section file="tbl_holdout_2026_posthoc.md" title="2026 사후 검증 — 전환 분해·리드타임" pick={[2, 4]} />
      <Section file="tbl_operating_points.md" title="운영점 (놓침/헛경보 비용비 r)" pick={[0]} />
      <Section file="tbl_stat_tests.md" title="통계 검정 (Diebold-Mariano · Wilcoxon)" pick={[0]} />
      <Section file="tbl_cqr.md" title="분위 구간 보정 (CQR)" pick={[0]} />
      <Section file="tbl_ablation.md" title="피처 그룹 ablation" pick={[0]} />
      <section className="card">
        <h2 className="font-semibold">물모아(NIER) 공식 예측 벤치마크</h2>
        <p className="text-sm text-slate-600">누적 중 (현재 n={benchN}). 2026-10-19 발표분부터 스냅샷을 쌓고 있으며 실측 도착 후 단계 분류 비교표가 채워집니다.</p>
      </section>
    </div>
  );
}
