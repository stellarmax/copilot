import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
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
import { SignInPage } from "./features/SignInPage";
import { getCurrentUser, SIGNED_OUT_EVENT, type User } from "./lib/api";

export default function App() {
  const queryClient = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: getCurrentUser, retry: false, staleTime: Infinity });

  useEffect(() => {
    // Any 401 means the session is gone: drop every cached answer so the next user sees nothing of it.
    const handleSignedOut = () => {
      queryClient.clear();
      queryClient.setQueryData(["me"], null);
    };
    window.addEventListener(SIGNED_OUT_EVENT, handleSignedOut);
    return () => window.removeEventListener(SIGNED_OUT_EVENT, handleSignedOut);
  }, [queryClient]);

  function handleSignedIn(user: User) {
    queryClient.clear();
    queryClient.setQueryData(["me"], user);
  }

  if (me.isPending) return <div className="auth-page" aria-busy="true" />;
  if (me.isError) return <div className="auth-page"><p className="auth-loading-error">{me.error.message}</p></div>;
  if (!me.data) return <SignInPage onSignedIn={handleSignedIn} />;
  return <Workspace user={me.data} />;
}

function Workspace({ user }: { user: User }) {
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
      <AppShell user={user}>
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