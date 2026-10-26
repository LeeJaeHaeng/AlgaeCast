/** ⓘ 설명 상자 위치 계산(순수 함수) — components/Info.tsx 가 쓰고 scripts/test_tip.mjs 가 검사한다 */

/** 설명 상자와 ⓘ 사이 간격(px) */
export const TIP_GAP = 4;
/** 화면 가장자리 여백(px) */
export const TIP_EDGE = 8;

export type Anchor = { left: number; top: number; bottom: number; width: number };
export type Size = { width: number; height: number };

/**
 * 설명 상자의 화면 좌표(position: fixed 기준 left·top)를 돌려준다.
 * - 가로: ⓘ 묶음 가운데 정렬, 화면 밖으로 나가면 가장자리 여백 안으로 민다(상자가 화면보다 넓으면 왼쪽 여백에 붙임).
 * - 세로: ⓘ 아래(간격 4px), 아래 공간이 모자라고 위 공간이 충분하면 ⓘ 위.
 */
export function placeTip(anchor: Anchor, box: Size, view: Size): { x: number; y: number } {
  const centered = anchor.left + anchor.width / 2 - box.width / 2;
  const x = Math.min(Math.max(centered, TIP_EDGE), Math.max(TIP_EDGE, view.width - TIP_EDGE - box.width));
  const below = anchor.bottom + TIP_GAP;
  const above = anchor.top - TIP_GAP - box.height;
  const y = below + box.height > view.height - TIP_EDGE && above >= TIP_EDGE ? above : below;
  return { x, y };
}
