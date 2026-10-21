export const revalidate = 86400;

const SOURCES = [
  ["조류경보제 측정 자료 (WQ-01)", "국립환경과학원 / 공공데이터포털", "공공누리 1유형", "5지점 2012~, 세포수·수온·수질"],
  ["댐유역 하천 일평균수위 (HY-05) ★DataON", "K-water · DataON 국가참조표준 (DOI 10.20925/KSRD.74670854.v5)", "CC BY-NC-SA (제3자 제공 금지, 파일 미배포)", "187개소 2010~2024 + WAMIS 연속"],
  ["수문 운영 정보·다목적댐 (HY-01/02)", "K-water 공공데이터포털", "이용제한 없음", "댐·보 유입·방류·수위"],
  ["표준수문DB WAMIS (HY-06)", "환경부 한강홍수통제소", "공공누리", "보 일자료·수위관측소"],
  ["ASOS 일자료 (MT-01)", "기상청", "공공누리 1유형", "11개 관측소 2012~"],
  ["단기·중기예보 (MT-05/06)", "기상청", "공공누리 1유형", "2026-10-21 이후 매일 누적"],
  ["물모아 AI 녹조 예측 (WQ-04)", "환경부 물모아", "공공누리", "벤치마크 스냅샷(누적 중)"],
  ["AIDA 격자 자료 (AI-01~03)", "기상청 AI 데이터", "공공누리", "Should 항목(미적용)"],
];

export default function AboutPage() {
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">소개</h1>
      <section className="card">
        <h2 className="font-semibold">방법 요약</h2>
        <pre className="mt-2 overflow-x-auto rounded bg-slate-50 p-3 text-xs leading-5">
{`공공 API/DataON 수집 ─▶ 일 달력 정렬(S1 LOCF) ─▶ 피처 101 → 선별 30 (VIF·Boruta·보 ablation)
     │                                                     │
     │                               LightGBM 변형 C1·C2·C3 (Optuna) ─▶ NNLS 앙상블(제출용 세포수)
     │                               분류기(b, +4~+10일 ≥10k) ─▶ p_alert ─▶ 경보 (p ≥ 0.52, r=3)
     │                               분위 q10/50/90 + CQR ─▶ 감시 (q90 ≥ 10,000)
     └▶ 연도 expanding CV(2020~24) → 2025 홀드아웃 → 모델 동결 → 2026 사후 검증 ─▶ Supabase ─▶ 이 대시보드`}
        </pre>
        <ul className="mt-2 list-disc pl-5 text-sm text-slate-700">
          <li>누수 방지: 모든 피처 함수는 base_date 이후 행을 진입 즉시 제거하고, 전 샘플 재계산 감사로 불일치 0건을 확인했습니다.</li>
          <li>임계·운영점은 CV OOF에서만 정하고 2025·2026 결과로 바꾸지 않았습니다. 2026 타깃은 격리 파일에서 사후 검증 전용 함수로만 읽습니다.</li>
          <li>원단위 R²·NSE 는 봉우리 높이 재현을 측정해 0.2 미만이며, 운영 목적에는 로그 R² 0.78·경보 F1·리드타임을 사용합니다.</li>
        </ul>
      </section>
      <section className="card">
        <h2 className="font-semibold">데이터 출처·라이선스</h2>
        <table className="tbl mt-2">
          <thead>
            <tr>
              <th>자료</th>
              <th>제공</th>
              <th>라이선스</th>
              <th>비고</th>
            </tr>
          </thead>
          <tbody>
            {SOURCES.map((r) => (
              <tr key={r[0]} className={r[0].includes("DataON") ? "bg-amber-50" : ""}>
                {r.map((c, i) => (
                  <td key={i}>{c}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-1 text-xs text-slate-500">전체 목록·수집 일시는 저장소 data/raw/MANIFEST.md.</p>
      </section>
      <section className="card">
        <h2 className="font-semibold">재현 (3줄)</h2>
        <pre className="mt-2 rounded bg-slate-50 p-3 text-xs">
{`make setup            # Python 3.11 venv + 의존성 + pre-commit
make collect align features   # 공공 API 수집(.env 키) → 일 달력 → 피처·분할
make select alert evaluate    # 피처 선별 → 모델·경보·앙상블 → 평가 보고서`}
        </pre>
        <p className="mt-2 text-sm">
          GitHub:{" "}
          <a className="text-sky-700 underline" href="https://github.com/LeeJaeHaeng/AlgaeCast" target="_blank" rel="noreferrer">
            github.com/LeeJaeHaeng/AlgaeCast
          </a>{" "}
          · 문서 docs/00~11, 방법 설명서 reports/방법설명서.md
        </p>
      </section>
    </div>
  );
}
