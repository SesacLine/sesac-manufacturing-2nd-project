import { Route, Routes, useLocation, useNavigate } from "react-router-dom";
import DashboardPage from "./pages/DashboardPage";
import ProgressPage from "./pages/ProgressPage";
import ResultPage from "./pages/ResultPage";

export default function App() {
  const navigate = useNavigate();
  const location = useLocation();
  const crumb = location.pathname.startsWith("/batches")
    ? "화면 2 · 분석 진행"
    : location.pathname.startsWith("/analyses")
      ? "화면 3 · 분석 결과"
      : "화면 1 · 대시보드";
  const onDashboard = location.pathname === "/";

  return (
    <>
      <div className="topbar">
        <div>
          <span className="brand">
            SesacLine SemiRCA
            <span className="dim">웨이퍼 결함 RCA · 그룹 단위 분석 · 결과 누적</span>
          </span>
        </div>
        <div className="crumb">{crumb}</div>
        <button className="back-btn" disabled={onDashboard} onClick={() => navigate("/")}>
          ◀ 대시보드로
        </button>
      </div>
      <div className="page">
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/batches/:batchId" element={<ProgressPage />} />
          <Route path="/analyses/:analysisId" element={<ResultPage />} />
        </Routes>
      </div>
    </>
  );
}
