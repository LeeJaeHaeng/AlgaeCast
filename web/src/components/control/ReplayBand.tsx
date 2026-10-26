import Link from "next/link";
import { REPLAY } from "@/lib/copy";
import { replayQuery, type Replay } from "@/lib/replay";

/**
 * 다시 보기 화면 맨 위 띠(항상): 지정 문구(날짜 포함) + 버튼('그 뒤 실제로는' 토글·현재 화면으로 돌아가기)만.
 * 장면 이름(결과를 알려 주는 말)은 띠에 넣지 않는다 — 진입 메뉴(ReplayMenu)에만 있다.
 * path = 이 화면의 경로(/, /sites/ID, /log) — 토글·돌아가기 링크가 같은 화면을 가리킨다. toggle=false: 차트가 없는 화면(/log)
 * 띠는 얇게(버튼 위아래 여백 2px) — 1920×1080 메인이 띠를 더해도 한 화면에 들어가게. 좁은 화면에서는 버튼 묶음이 줄바꿈된다.
 */
export function ReplayBand({ replay, path, expert, toggle = true }: { replay: Replay; path: string; expert: boolean; toggle?: boolean }) {
  const toggleHref = `${path}${replayQuery({ replay: { asof: replay.asof, after: !replay.after }, expert })}`;
  const live = `${path}${expert ? "?view=expert" : ""}`;
  const thin = { paddingTop: 2, paddingBottom: 2 };
  return (
    <div className="sticky top-0 z-[1050] border-b border-[var(--replay)] bg-[color-mix(in_srgb,var(--replay)_20%,var(--bg))]" role="note" aria-label={REPLAY.button} data-replay-band={replay.asof}>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-1 text-sm">
        <strong className="min-w-0 font-semibold">{REPLAY.band(replay.asof)}</strong>
        <span className="ml-auto flex min-w-0 flex-wrap items-center gap-2">
          {toggle && (
            <Link href={toggleHref} className="btn" style={thin} data-active={replay.after ? "true" : undefined} data-after-toggle>
              {replay.after ? REPLAY.afterOff : REPLAY.afterOn}
            </Link>
          )}
          <Link href={live} className="btn" style={thin} data-replay-back>
            {REPLAY.back}
          </Link>
        </span>
      </div>
    </div>
  );
}

/** asof 가 틀렸거나 범위 밖일 때 — 파라미터는 무시하고 현재 화면을 보여 주며 한 줄로 알린다 */
export function ReplayNotice({ text }: { text: string }) {
  return (
    <div className="border-b border-border bg-panel px-4 py-1.5 text-sm text-dim" role="note" data-replay-notice>
      {text}
    </div>
  );
}
