import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { ReminderNotifier } from "./components/ReminderNotifier";
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
import { getCurrentUser, setSessionActive, SIGNED_OUT_EVENT, type User } from "./lib/api";
import { switchUser } from "./lib/session";
import { useDueReminders } from "./lib/useDueReminders";

export default function App() {
  const queryClient = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: getCurrentUser, retry: false, staleTime: Infinity });

  useEffect(() => {
    // Any 401 means the session is gone: drop every cached answer so the next user sees nothing of it.
    const handleSignedOut = () => switchUser(queryClient, null);
    window.addEventListener(SIGNED_OUT_EVENT, handleSignedOut);
    return () => window.removeEventListener(SIGNED_OUT_EVENT, handleSignedOut);
  }, [queryClient]);

  if (me.isPending) return <div className="auth-page" aria-busy="true" />;
  if (me.isError) return <div className="auth-page"><p className="auth-loading-error">{me.error.message}</p></div>;
  // Set before any page renders, so signed-out pages never send data requests.
  setSessionActive(Boolean(me.data));
  return (
    <Routes>
      <Route path="/signin" element={<SignInPage signedIn={Boolean(me.data)} onSignedIn={(user) => switchUser(queryClient, user)} />} />
      <Route path="*" element={<Workspace user={me.data ?? null} />} />
    </Routes>
  );
}

/** The app layout. Signed out (user = null), every page is open but shows no data and the AI never runs. */
function Workspace({ user }: { user: User | null }) {
  const [claimId, setClaimId] = useState<string | null>(null);
  const location = useLocation();
  const navigate = useNavigate();
  const isChatRoute = location.pathname === "/chat" || location.pathname.startsWith("/chat/");
  // Lives above both layouts so reminders still notify while the full-screen chat is open.
  const { due } = useDueReminders(user !== null);

  const notifier = user && <ReminderNotifier due={due} userId={user.user_id} />;

  if (isChatRoute) {
    return (
      <>
        {notifier}
        <Routes>
          <Route path="/chat" element={<ChatPage onTrace={setClaimId} signedIn={user !== null} />} />
          <Route path="/chat/:conversationId" element={<ChatPage onTrace={setClaimId} signedIn={user !== null} />} />
          <Route path="*" element={<Navigate to="/chat" replace />} />
        </Routes>
        <TraceDrawer claimId={claimId} onClose={() => setClaimId(null)} />
      </>
    );
  }

  return (
    <>
      {notifier}
      <AppShell user={user} dueCount={user ? due.length : 0}>
        <Routes>
          <Route path="/" element={<OverviewPage onTrace={setClaimId} onAsk={(message) => navigate("/chat", { state: { initialMessage: message } })} />} />
          <Route path="/orders" element={<OrdersPage onTrace={setClaimId} />} />
          <Route path="/production" element={<ProductionPage onTrace={setClaimId} />} />
          <Route path="/feasibility" element={<FeasibilityPage onTrace={setClaimId} />} />
          <Route path="/reminders" element={<RemindersPage onTrace={setClaimId} />} />
          <Route path="/audit" element={<AuditPage />} />
          <Route path="/settings" element={<AISettingsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AppShell>
      <TraceDrawer claimId={claimId} onClose={() => setClaimId(null)} />
    </>
  );
}