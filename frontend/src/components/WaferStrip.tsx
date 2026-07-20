/** §2.6 로트 웨이퍼 그리드 — wafers.length 기준 렌더(25칸 고정 금지),
 *  받은 순서 그대로(서버가 정수 오름차순 정렬), 이미지 404는 placeholder로 방어. */

import { useState } from "react";
import { api } from "../api/client";
import type { LotWafers } from "../api/types";

function WaferImage({ src, alt }: { src: string; alt: string }) {
  const [failed, setFailed] = useState(false);
  if (failed) {
    return (
      <div className="wf-map" style={{ display: "flex", alignItems: "center", justifyContent: "center", fontSize: 9, color: "var(--text-dim)" }}>
        이미지 없음
      </div>
    );
  }
  return <img className="wf-map" src={src} alt={alt} onError={() => setFailed(true)} />;
}

export default function WaferStrip({
  data,
  onClose,
}: {
  data: LotWafers;
  onClose: () => void;
}) {
  return (
    <div className="wafer-depth">
      <div className="wd-head">
        <span>
          Lot {data.lot_id} · 판독 {data.wafer_count}장 중 불량 {data.defect_count}장 · 정상{" "}
          {data.normal_count}장{" "}
          <span style={{ fontWeight: 400, color: "var(--text-dim)" }}>(CNN 분류 기준)</span>
        </span>
        <button className="ghost-btn" onClick={onClose}>
          ✕ 닫기
        </button>
      </div>
      <div className="wf-strip">
        {data.wafers.map((w) => (
          <div key={w.wafer_id} className={w.defect_pattern === "Normal" ? "wf-item normal" : "wf-item"}>
            <WaferImage src={api.dieMapUrl(w.die_map_url)} alt={`wafer ${w.wafer_id}`} />
            <div className="wf-id">#{w.wafer_id}</div>
            <div className="wf-tag">{w.defect_pattern === "Normal" ? "정상" : w.defect_pattern}</div>
          </div>
        ))}
        {data.wafers.length === 0 && <div className="na-note">판독 웨이퍼가 없습니다.</div>}
      </div>
    </div>
  );
}
