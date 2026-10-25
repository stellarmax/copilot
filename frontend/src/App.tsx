import { useState } from "react";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { TraceDrawer } from "./components/TraceDrawer";
import { AISettingsPage } from "./features/AISettingsPage";
import { ChatPage } from "./features/ChatPage";
import { AuditPage } from "./features/AuditPage";
import { FeasibilityPage } from "./features/FeasibilityPage";
import { OrdersPage } from "./features/OrdersPage";
import { OverviewPage } from "./features/OverviewPage";
import { ProductionPage } from "./features/ProductionPage";
import { RemindersPage } from "./features/RemindersPage";

export default function App() {
  const [claimId, setClaimId] = useState<string | null>(null);
  const location = useLocation();
  const navigate = useNavigate();
  const isChatRoute = location.pathname === "/chat" || location.pathname.startsWith("/chat/");

  if (isChatRoute) {
    return (
      <>
        <Routes>
          <Route path="/chat" element={<ChatPage onTrace={setClaimId} />} />
          <Route path="/chat/:conversationId" element={<ChatPage onTrace={setClaimId} />} />
          <Route path="*" element={<Navigate to="/chat" replace />} />
        </Routes>
        <TraceDrawer claimId={claimId} onClose={() => setClaimId(null)} />
      </>
    );
  }

  return (
    <>
      <AppShell>
        <Routes>
          <Route path="/" element={<OverviewPage onTrace={setClaimId} onAsk={(message) => navigate("/chat", { state: { initialMessage: message } })} />} />
          <Route path="/orders" element={<OrdersPage onTrace={setClaimId} />} />
          <Route path="/production" element={<ProductionPage onTrace={setClaimId} />} />
          <Route path="/feasibility" element={<FeasibilityPage onTrace={setClaimId} />} />
          <Route path="/reminders" element={<RemindersPage />} />
          <Route path="/audit" element={<AuditPage />} />
          <Route path="/settings" element={<AISettingsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AppShell>
      <TraceDrawer claimId={claimId} onClose={() => setClaimId(null)} />
    </>
  );
}