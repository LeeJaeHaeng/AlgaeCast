// ⓘ 설명 상자 위치 계산(src/lib/tip.ts) 검사 — 실행: node --test scripts/test_tip.mjs (Node 22.18+/24 의 타입 제거 실행)
import assert from "node:assert/strict";
import test from "node:test";
import { TIP_EDGE, TIP_GAP, placeTip } from "../src/lib/tip.ts";

const box = { width: 256, height: 80 };
const view = { width: 1350, height: 940 };
const at = (left, top, width = 24, height = 20) => ({ left, top, bottom: top + height, width });

test("화면 가운데 ⓘ: 가운데 정렬, ⓘ 아래 4px (예전 absolute 배치와 같은 자리)", () => {
  const a = at(600, 300);
  assert.deepEqual(placeTip(a, box, view), { x: 600 + 12 - 128, y: 320 + TIP_GAP });
});

test("오른쪽 끝 ⓘ(1350 폭 '고정한 모델'): 화면 안으로 밀림", () => {
  const { x } = placeTip(at(1240, 500), box, view);
  assert.equal(x, view.width - TIP_EDGE - box.width);
  assert.ok(x + box.width <= view.width - TIP_EDGE);
});

test("왼쪽 끝 ⓘ: 왼쪽 여백에 붙음", () => {
  assert.equal(placeTip(at(2, 300), box, view).x, TIP_EDGE);
});

test("아래 공간 부족(화면 맨 아래 성적표 띠): ⓘ 위에 띄움", () => {
  const a = at(1700, 1050);
  const { y } = placeTip(a, box, { width: 1920, height: 1080 });
  assert.equal(y, 1050 - TIP_GAP - box.height);
});

test("위아래 모두 부족: 아래 유지", () => {
  const { y } = placeTip(at(100, 30), { width: 256, height: 400 }, { width: 400, height: 300 });
  assert.equal(y, 50 + TIP_GAP);
});

test("상자가 화면보다 넓음: 왼쪽 여백에 붙임", () => {
  assert.equal(placeTip(at(100, 30), { width: 500, height: 80 }, { width: 360, height: 780 }).x, TIP_EDGE);
});
