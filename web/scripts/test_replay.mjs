// 과거 시점 다시 보기(src/lib/replay.ts) 순수 함수 검사 — 실행: node --test scripts/test_replay.mjs (Node 22.18+/24 의 타입 제거 실행)
// 관측·예측·사건·상황 기록 거르기, '그 뒤 실제로는' 21일 범위, 허용 범위 판정, 링크 쿼리.
import assert from "node:assert/strict";
import test from "node:test";
import { AFTER_DAYS, REPLAY_MIN, REPLAY_RUN_ID, SCENES, WEATHER_DAYS, addDaysISO, afterWindow, buildStatusAsOf, eventsAsOf, fillActualAsOf, isIsoDate, logAsOf, maskFutureActual, mergeLogAsOf, mergeSameDate, obsAfter, obsAsOf, parseReplay, pickPredAsOf, predsAsOf, replayMinOf, replayQuery, replayState, sceneOf, summarizeWeatherAsOf, tierChangesAsOf, weatherWindow } from "../src/lib/replay.ts";

const bounds = { min: "2026-05-04", max: "2026-10-22" };

test("날짜 형식: YYYY-MM-DD 이고 실제 있는 날짜만", () => {
  assert.ok(isIsoDate("2026-07-27"));
  assert.ok(isIsoDate("2024-02-29"));
  for (const bad of ["2026-02-30", "2026-13-01", "2026-7-27", "20260727", "2026-07-27T00:00", "", "abc", undefined, null, 20260727]) assert.equal(isIsoDate(bad), false, String(bad));
});

test("날짜 더하기: 달·해 넘김, 시간대 무관", () => {
  assert.equal(addDaysISO("2026-07-27", 7), "2026-08-03");
  assert.equal(addDaysISO("2026-07-27", 21), "2026-08-17");
  assert.equal(addDaysISO("2026-01-01", -1), "2025-12-31");
  assert.equal(addDaysISO("2026-03-01", -1), "2026-02-28");
});

test("허용 범위: max(2026-01-01, 데이터 첫 기준일) ≤ asof ≤ 데이터 마지막 기준일, 형식이 틀리면 bad", () => {
  assert.equal(replayState(undefined, bounds), "none");
  assert.equal(replayState("", bounds), "none");
  assert.equal(replayState("2026-07-27", bounds), "ok");
  assert.equal(replayState("2026-05-04", bounds), "ok");
  assert.equal(replayState("2026-10-22", bounds), "ok");
  assert.equal(replayState("2026-10-23", bounds), "range"); // 마지막 기준일 뒤
  assert.equal(replayState("2026-05-03", bounds), "range"); // 2026 첫 기준일 전(그날 예측 없음)
  assert.equal(replayState("2025-08-01", bounds), "range"); // 2025 이전: v2.1 학습기간과 겹침
  assert.equal(replayState("2025-12-31", { min: "2025-01-06", max: "2026-10-22" }), "range"); // 데이터가 2025 부터 있어도 정책 하한 2026-01-01
  assert.equal(replayState("2026-02-30", bounds), "bad");
  assert.equal(replayState("07-27", bounds), "bad");
  assert.equal(replayState("2026-07-27", { min: null, max: null }), "range");
  assert.equal(replayMinOf({ min: "2025-01-06", max: "2026-10-22" }), REPLAY_MIN);
  assert.equal(replayMinOf(bounds), "2026-05-04");
});

test("parseReplay: 맞을 때만 상태, after 는 '1' 일 때만", () => {
  assert.deepEqual(parseReplay({ asof: "2026-07-27" }, bounds), { asof: "2026-07-27", after: false });
  assert.deepEqual(parseReplay({ asof: "2026-07-27", after: "1" }, bounds), { asof: "2026-07-27", after: true });
  assert.deepEqual(parseReplay({ asof: "2026-07-27", after: "true" }, bounds), { asof: "2026-07-27", after: false });
  assert.equal(parseReplay({ asof: "2025-07-27", after: "1" }, bounds), null);
  assert.equal(parseReplay({}, bounds), null);
});

const obs = [
  { site_id: "A", obs_date: "2026-07-20", cell_count: 100, alert_level: 0, water_temp: 25 },
  { site_id: "A", obs_date: "2026-07-27", cell_count: 8457, alert_level: 1, water_temp: 30 },
  { site_id: "A", obs_date: "2026-08-03", cell_count: 98859, alert_level: 1, water_temp: 31 },
  { site_id: "A", obs_date: "2026-08-17", cell_count: 5000, alert_level: 2, water_temp: 29 },
  { site_id: "A", obs_date: "2026-08-18", cell_count: 483021, alert_level: 2, water_temp: 28 },
];

test("관측 거르기: 관측일 ≤ asof (asof 당일 포함, 다음 날부터 제외), days 창", () => {
  assert.deepEqual(obsAsOf(obs, "2026-07-27").map((o) => o.obs_date), ["2026-07-20", "2026-07-27"]);
  assert.deepEqual(obsAsOf(obs, "2026-07-26").map((o) => o.obs_date), ["2026-07-20"]);
  assert.deepEqual(obsAsOf(obs, "2026-08-03", 7).map((o) => o.obs_date), ["2026-07-27", "2026-08-03"]);
  assert.ok(obsAsOf(obs, "2026-07-27").every((o) => o.obs_date <= "2026-07-27"));
});

test("'그 뒤 실제로는': asof < 관측일 ≤ asof+21 (asof 당일·22일째 제외)", () => {
  assert.equal(AFTER_DAYS, 21);
  assert.deepEqual(afterWindow("2026-07-27"), { from: "2026-07-28", to: "2026-08-17" });
  assert.deepEqual(obsAfter(obs, "2026-07-27").map((o) => o.obs_date), ["2026-08-03", "2026-08-17"]);
  assert.ok(!obsAfter(obs, "2026-07-27").some((o) => o.obs_date === "2026-07-27"));
  assert.ok(!obsAfter(obs, "2026-07-27").some((o) => o.obs_date === "2026-08-18"));
});

const preds = [
  { site_id: "A", base_date: "2025-12-22", target_date: "2025-12-29", pred_cell_count: 1, obs_cell_count: 2, tier: "normal" },
  { site_id: "A", base_date: "2026-07-20", target_date: "2026-07-27", pred_cell_count: 1906, obs_cell_count: 8457, tier: "watch" },
  { site_id: "A", base_date: "2026-07-23", target_date: "2026-07-27", pred_cell_count: 1092, obs_cell_count: 8457, tier: "normal" },
  { site_id: "A", base_date: "2026-07-27", target_date: "2026-08-03", pred_cell_count: 10662, obs_cell_count: 98859, tier: "alert" },
  { site_id: "A", base_date: "2026-08-03", target_date: "2026-08-10", pred_cell_count: 26550, obs_cell_count: 29200, tier: "alert" },
  { site_id: "B", base_date: "2026-07-06", target_date: "2026-07-13", pred_cell_count: 55, obs_cell_count: null, tier: "normal" },
];

test("예측 거르기: 기준일 ≤ asof 중 최신, 2025 기준일 제외, 목표일이 asof 뒤면 실측 지움", () => {
  const p = pickPredAsOf(preds, "A", "2026-07-27");
  assert.equal(p.base_date, "2026-07-27");
  assert.equal(p.pred_cell_count, 10662);
  assert.equal(p.obs_cell_count, null, "목표일 08-03 > asof 07-27 → 그 실측(98,859)은 asof 이후 관측");
  assert.equal(pickPredAsOf(preds, "A", "2026-07-26").base_date, "2026-07-23");
  assert.equal(pickPredAsOf(preds, "A", "2026-07-26").obs_cell_count, null, "목표일 07-27 > asof 07-26");
  assert.equal(pickPredAsOf(preds, "A", "2026-07-27").base_date, "2026-07-27");
  assert.equal(pickPredAsOf(preds, "A", "2026-08-03").obs_cell_count, null);
  assert.equal(pickPredAsOf(preds, "A", "2026-01-15"), null, "2025 기준일 예측은 쓰지 않음");
  const all = predsAsOf(preds, "2026-07-27");
  assert.ok(all.every((x) => x.base_date >= REPLAY_MIN && x.base_date <= "2026-07-27"));
  assert.ok(all.every((x) => x.target_date <= "2026-07-27" || x.obs_cell_count === null));
  assert.equal(all.find((x) => x.base_date === "2026-07-23").obs_cell_count, 8457, "목표일 = asof 이면 실측 남김");
  assert.equal(maskFutureActual({ target_date: "2026-08-03", obs_cell_count: 5 }, "2026-08-03").obs_cell_count, 5);
});

test("같은 기준일 두 행이면 목표일 늦은 것(v_site_status 와 같은 순서)", () => {
  const two = [
    { site_id: "A", base_date: "2026-07-27", target_date: "2026-08-02", pred_cell_count: 1, obs_cell_count: null },
    { site_id: "A", base_date: "2026-07-27", target_date: "2026-08-03", pred_cell_count: 2, obs_cell_count: null },
  ];
  assert.equal(pickPredAsOf(two, "A", "2026-07-30").pred_cell_count, 2);
});

test("사건 거르기: 그날까지 판정된 사건(공식 발령일 ≤ asof)만", () => {
  const ev = [
    { event_id: "e1", first_exceed_date: "2026-06-08", official_alert_date: "2026-06-15" },
    { event_id: "e2", first_exceed_date: "2026-08-03", official_alert_date: "2026-08-10" },
  ];
  assert.deepEqual(eventsAsOf(ev, "2026-08-03").map((e) => e.event_id), ["e1"], "첫 초과일 당일엔 아직 판정 전");
  assert.deepEqual(eventsAsOf(ev, "2026-08-10").map((e) => e.event_id), ["e1", "e2"]);
  assert.deepEqual(eventsAsOf(ev, "2026-06-14").map((e) => e.event_id), []);
});

test("상황 기록 거르기: asof-30 ≤ 날짜 ≤ asof, 파이프라인 갱신(run) 기록 제외", () => {
  const rows = [
    { event_date: "2026-06-26", kind: "observation" },
    { event_date: "2026-06-27", kind: "observation" },
    { event_date: "2026-07-27", kind: "tier_change" },
    { event_date: "2026-07-27", kind: "run" },
    { event_date: "2026-07-28", kind: "observation" },
  ];
  assert.deepEqual(logAsOf(rows, "2026-07-27").map((r) => `${r.event_date}/${r.kind}`), ["2026-06-27/observation", "2026-07-27/tier_change"]);
});

test("그날 기준 지점 상태: 최근 관측·예측·목표일 실측 모두 asof 기준", () => {
  const sites = [{ site_id: "A", name: "가", basin: "낙동강" }, { site_id: "B", name: "나", basin: "금강" }];
  const [a, b] = buildStatusAsOf(sites, preds, obs, "2026-07-27");
  assert.equal(a.latest_obs_date, "2026-07-27");
  assert.equal(a.latest_cell_count, 8457);
  assert.equal(a.latest_alert_level, 1);
  assert.equal(a.base_date, "2026-07-27");
  assert.equal(a.target_date, "2026-08-03");
  assert.equal(a.tier, "alert");
  assert.equal(a.obs_cell_count, null, "목표일이 asof 뒤 → 실측 없음");
  assert.equal(b.base_date, "2026-07-06", "B: 기준일 ≤ asof 중 최신 예측(오래돼도 그날 볼 수 있던 마지막 예상)");
  assert.equal(b.latest_obs_date, null, "B: 관측 자료 없음");
  const [, b2] = buildStatusAsOf(sites, preds, obs, "2026-07-05");
  assert.equal(b2.base_date, null, "기준일 07-06 예측은 07-05 에는 아직 없음");
  assert.equal(b2.tier, null);
  // asof 이후 관측 값이 어디에도 없어야 한다
  const flat = JSON.stringify(buildStatusAsOf(sites, preds, obs, "2026-07-27"));
  assert.ok(!flat.includes("98859") && !flat.includes("483021") && !flat.includes("2026-08-17"));
  // 목표일 ≤ asof 면 실측 표시(예측 행 실측 우선)
  const [a3] = buildStatusAsOf(sites, preds.filter((p) => p.base_date <= "2026-07-23"), obs, "2026-07-27");
  assert.equal(a3.obs_cell_count, 8457);
});

test("링크 쿼리: asof·after 유지, 기본 화면 모양 그대로", () => {
  assert.equal(replayQuery({}), "");
  assert.equal(replayQuery({ expert: true }), "?view=expert");
  assert.equal(replayQuery({ kiosk: true }), "?kiosk=1");
  assert.equal(replayQuery({ kiosk: true, expert: true }), "?kiosk=1&view=expert", "기존 순환 URL 과 같은 순서");
  assert.equal(replayQuery({ replay: { asof: "2026-07-27", after: false }, expert: true }), "?asof=2026-07-27&view=expert");
  assert.equal(replayQuery({ replay: { asof: "2026-07-27", after: true } }), "?asof=2026-07-27&after=1");
});

test("장면 3개: 허용 범위 안, 놓친 사례 포함, 장면 지점·날짜", () => {
  assert.equal(SCENES.length, 3);
  for (const s of SCENES) assert.equal(replayState(s.asof, bounds), "ok", s.id);
  assert.deepEqual(SCENES.map((s) => [s.id, s.asof, s.siteId]), [["pre", "2026-07-27", "2011G56"], ["onset", "2026-08-03", "2011G56"], ["miss", "2026-07-06", "3008G30"]]);
  assert.equal(sceneOf("2026-07-06").id, "miss");
  assert.equal(sceneOf("2026-07-07"), undefined);
});

test("빈 실측 채우기: 목표일 ≤ asof 일 때만 그 날 관측값, asof 뒤 목표일은 실측 지움, DB 실측은 그대로", () => {
  const ps = [
    { site_id: "B", base_date: "2026-07-13", target_date: "2026-07-20", pred_cell_count: 50, obs_cell_count: null },
    { site_id: "B", base_date: "2026-07-20", target_date: "2026-07-27", pred_cell_count: 60, obs_cell_count: null },
    { site_id: "B", base_date: "2026-07-27", target_date: "2026-08-03", pred_cell_count: 70, obs_cell_count: null },
    { site_id: "B", base_date: "2026-07-06", target_date: "2026-07-13", pred_cell_count: 40, obs_cell_count: 999 },
  ];
  const ob = [
    { obs_date: "2026-07-20", cell_count: 523 },
    { obs_date: "2026-07-27", cell_count: 1204 },
    { obs_date: "2026-08-03", cell_count: 777 },
    { obs_date: "2026-07-13", cell_count: 5 },
  ];
  const f = fillActualAsOf(ps, ob, "2026-07-27");
  assert.deepEqual(f.map((p) => p.obs_cell_count), [523, 1204, null, 999]);
  // asof 뒤 관측(08-03, 777)은 어떤 행에도 들어가지 않는다
  assert.ok(!JSON.stringify(f).includes("777"));
  // 목표일 = asof 다음 날이면 그 날 관측이 넘어와도 쓰지 않는다
  assert.equal(fillActualAsOf(ps, ob, "2026-07-26")[1].obs_cell_count, null);
  // DB 실측이 있어도 목표일이 asof 뒤면 지운다
  assert.equal(fillActualAsOf([{ target_date: "2026-08-03", obs_cell_count: 98859 }], ob, "2026-07-27")[0].obs_cell_count, null);
  // 원본은 바꾸지 않는다
  assert.equal(ps[0].obs_cell_count, null);
});

test("상황 기록 단계 변화: 다시 보기 run 예측으로(v_event_log 와 같은 규칙), 창·직전 단계·같은 기준일·asof 뒤 제외", () => {
  const sites = [{ site_id: "A", name: "가" }, { site_id: "B", name: "나" }];
  const tp = [
    { site_id: "A", base_date: "2026-05-04", target_date: "2026-05-11", tier: "normal", p_alert: 0.01, q50: 10, q90_cqr: 100 },
    { site_id: "A", base_date: "2026-07-20", target_date: "2026-07-27", tier: "watch", p_alert: 0.2, q50: 1906, q90_cqr: 9000 },
    { site_id: "A", base_date: "2026-07-23", target_date: "2026-07-26", tier: "alert", p_alert: 0.9, q50: 1, q90_cqr: 1 }, // 같은 기준일의 앞선 목표일 → 버림
    { site_id: "A", base_date: "2026-07-23", target_date: "2026-07-27", tier: "normal", p_alert: 0.1, q50: 1092, q90_cqr: 5000 },
    { site_id: "A", base_date: "2026-07-27", target_date: "2026-08-03", tier: "alert", p_alert: 0.773, q50: 10662, q90_cqr: 45882 },
    { site_id: "A", base_date: "2026-08-03", target_date: "2026-08-10", tier: "watch", p_alert: 0.5, q50: 26550, q90_cqr: 90000 }, // asof 뒤
    { site_id: "B", base_date: "2026-05-04", target_date: "2026-05-11", tier: "watch", p_alert: 0.3, q50: 50, q90_cqr: 500 },
  ];
  const seed = [{ site_id: "A", tier: "normal" }, { site_id: "B", tier: "normal" }];
  const r = tierChangesAsOf(tp, seed, sites, "2026-07-27");
  assert.deepEqual(r.map((e) => `${e.event_date} ${e.site_id} ${e.tier_from}->${e.tier_to}`), ["2026-07-20 A normal->watch", "2026-07-23 A watch->normal", "2026-07-27 A normal->alert"]);
  assert.equal(r[2].event_time, "2026-07-27T00:00:00+00:00", "기준일 09시 KST = 00:00 UTC(뷰와 같은 값)");
  assert.equal(r[2].site_name, "가");
  assert.equal(r[2].p_alert, 0.773);
  assert.ok(!JSON.stringify(r).includes("26550") && !JSON.stringify(r).includes("2026-08-03"), "asof 뒤 기준일 예측은 쓰지 않음");
  // 창(30일) 밖 변화는 빼되 직전 단계 비교에는 쓴다: B 의 05-04 normal->watch 는 창 밖
  assert.ok(!r.some((e) => e.site_id === "B"));
  const r2 = tierChangesAsOf(tp, seed, sites, "2026-05-04");
  assert.deepEqual(r2.map((e) => `${e.site_id} ${e.tier_from}->${e.tier_to}`), ["B normal->watch"], "seed 와 같은 단계(A normal)는 변화 아님");
  // seed 가 없으면 첫 예측은 tier_from = null 로 기록(뷰의 첫 행과 같음)
  assert.deepEqual(tierChangesAsOf(tp, [], sites, "2026-05-04").map((e) => `${e.site_id} ${e.tier_from}->${e.tier_to}`), ["A null->normal", "B null->watch"]);
});

test("상황 기록 합치기: 새 측정(뷰) + 단계 변화(run), 그날까지 30일·시각 내림차순·limit, run·단계 변화 행은 뷰에서 받지 않음", () => {
  const obsRows = [
    { event_time: "2026-07-27T03:00:00+00:00", event_date: "2026-07-27", kind: "observation", id: "o1" },
    { event_time: "2026-07-20T03:00:00+00:00", event_date: "2026-07-20", kind: "observation", id: "o2" },
    { event_time: "2026-07-28T03:00:00+00:00", event_date: "2026-07-28", kind: "observation", id: "o3" }, // asof 뒤
    { event_time: "2026-06-20T03:00:00+00:00", event_date: "2026-06-20", kind: "observation", id: "o4" }, // 창 밖
    { event_time: "2026-07-27T00:00:00+00:00", event_date: "2026-07-27", kind: "tier_change", id: "view-tier" }, // 뷰의 단계 변화(최신 run) → 버림
    { event_time: "2026-07-27T05:00:00+00:00", event_date: "2026-07-27", kind: "run", id: "run" },
  ];
  const tierRows = [{ event_time: "2026-07-27T00:00:00+00:00", event_date: "2026-07-27", kind: "tier_change", id: "t1" }];
  assert.deepEqual(mergeLogAsOf(obsRows, tierRows, "2026-07-27").map((r) => r.id), ["o1", "t1", "o2"]);
  assert.deepEqual(mergeLogAsOf(obsRows, tierRows, "2026-07-27", 30, 2).map((r) => r.id), ["o1", "t1"]);
});

test("다시 보기 run 고정: 상수 한 곳(uuid 형식)", () => {
  assert.match(REPLAY_RUN_ID, /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/);
  assert.ok(REPLAY_RUN_ID.startsWith("9269d95d"));
});

test("다시 보기 날씨 칸(실측): 창 = 그날−6 ~ 그날(창 끝 = 그날), 그날 뒤·창 앞 행 제외, 평균·합계 소수 1자리, 자료 일수", () => {
  assert.equal(WEATHER_DAYS, 7);
  assert.deepEqual(weatherWindow("2026-07-27"), { from: "2026-07-21", to: "2026-07-27" });
  assert.deepEqual(weatherWindow("2026-08-03"), { from: "2026-07-28", to: "2026-08-03" });
  assert.deepEqual(weatherWindow("2026-03-02"), { from: "2026-02-24", to: "2026-03-02" }, "달 넘김");
  const rows = [
    { site_id: "A", obs_date: "2026-07-20", ta_mean: 10, rn_sum: 100 }, // 창 앞(그날−7)
    { site_id: "A", obs_date: "2026-07-21", ta_mean: 28.1, rn_sum: 0 },
    { site_id: "A", obs_date: "2026-07-22", ta_mean: 28.4, rn_sum: 1.2 },
    { site_id: "A", obs_date: "2026-07-23", ta_mean: null, rn_sum: 0.3 }, // 기온 없음(비만)
    { site_id: "A", obs_date: "2026-07-27", ta_mean: 30, rn_sum: null }, // 그날(포함), 비 없음
    { site_id: "A", obs_date: "2026-07-28", ta_mean: 99, rn_sum: 999 }, // 그날 다음 날 → 제외
    { site_id: "B", obs_date: "2026-07-27", ta_mean: 25.04, rn_sum: 5.26 },
    { site_id: "B", obs_date: "2026-07-25", ta_mean: null, rn_sum: null }, // 값 없는 행은 일수에 안 셈
  ];
  const [a, b, c] = summarizeWeatherAsOf(rows, ["A", "B", "C"], "2026-07-27");
  assert.deepEqual(a, { site_id: "A", ta_mean: 28.8, rn_sum: 1.5, days: 4 }, "A: 기온 (28.1+28.4+30)/3=28.83→28.8, 비 0+1.2+0.3=1.5, 자료 4일");
  assert.deepEqual(b, { site_id: "B", ta_mean: 25.0, rn_sum: 5.3, days: 1 }, "B: 소수 1자리 반올림, 값 없는 날은 안 셈");
  assert.deepEqual(c, { site_id: "C", ta_mean: null, rn_sum: null, days: 0 }, "C: 자료 없음 → null");
  const flat = JSON.stringify([a, b, c]);
  assert.ok(!flat.includes("99") && !flat.includes("100"), "그날 뒤·창 앞 값이 섞이지 않음");
  // 7일 모두 있으면 days = 7
  const full = Array.from({ length: 7 }, (_, i) => ({ site_id: "D", obs_date: addDaysISO("2026-07-21", i), ta_mean: 20 + i, rn_sum: 1 }));
  assert.deepEqual(summarizeWeatherAsOf(full, ["D"], "2026-07-27")[0], { site_id: "D", ta_mean: 23.0, rn_sum: 7.0, days: 7 });
  // 같은 날 두 행이면 값 있는 칸이 이김
  const dup = [
    { site_id: "E", obs_date: "2026-07-27", ta_mean: null, rn_sum: 2 },
    { site_id: "E", obs_date: "2026-07-27", ta_mean: 21, rn_sum: null },
  ];
  assert.deepEqual(summarizeWeatherAsOf(dup, ["E"], "2026-07-27")[0], { site_id: "E", ta_mean: 21.0, rn_sum: 2.0, days: 1 });
});

test("큰 차트 같은 날짜 점 합치기: 측정 점과 목표일 예상 점이 한 점으로, 값 있는 칸 유지", () => {
  const pts = [
    { date: "2026-09-07", obs: 1200, past_pred: 900 },
    { date: "2026-09-03", obs: 800, past_pred: null },
    { date: "2026-09-07", obs: null, pred: 1500, lo: 100, hi: 9000 },
  ];
  const m = mergeSameDate(pts);
  assert.equal(m.length, 2);
  assert.deepEqual(m.map((p) => p.date), ["2026-09-03", "2026-09-07"]);
  assert.deepEqual(m[1], { date: "2026-09-07", obs: 1200, past_pred: 900, pred: 1500, lo: 100, hi: 9000 });
});
