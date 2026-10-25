import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { NavLink, useLocation } from "react-router-dom";
import {
  Activity,
  BellRing,
  Boxes,
  ChartNoAxesCombined,
  ClipboardList,
  Factory,
  Info,
  Link2,
  Menu,
  ShieldCheck,
  Settings2,
  MoreHorizontal,
  RefreshCw,
  X,
} from "lucide-react";
import { getHealth } from "../lib/api";

const navigation = [
  { to: "/", label: "Overview", icon: ChartNoAxesCombined, end: true },
  { to: "/orders", label: "Orders", icon: Boxes },
  { to: "/production", label: "Production", icon: Factory },
  { to: "/feasibility", label: "Feasibility", icon: Activity },
  { to: "/reminders", label: "Reminders", icon: BellRing },
  { to: "/audit", label: "Action log", icon: ClipboardList },
  { to: "/settings", label: "AI settings", icon: Settings2 },
];

const headings: Record<string, { title: string; kicker: string }> = {
  "/": { title: "Operations overview", kicker: "DAILY CONTROL ROOM" },
  "/orders": { title: "Order book", kicker: "ORDER INTELLIGENCE" },
  "/production": { title: "Production pulse", kicker: "STAGE PERFORMANCE" },
  "/feasibility": { title: "New order check", kicker: "CAPACITY PLANNING" },
  "/reminders": { title: "Reminders", kicker: "ORDER FOLLOW-UPS" },
  "/audit": { title: "Action ledger", kicker: "LOCAL AUDIT TRAIL" },
  "/settings": { title: "AI settings", kicker: "PROVIDER & MEMORY" },
};

interface AppShellProps {
  children: React.ReactNode;
}

export function AppShell({ children }: AppShellProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [profileMenuOpen, setProfileMenuOpen] = useState(false);
  const [demoInfoOpen, setDemoInfoOpen] = useState(false);
  const [menuNotice, setMenuNotice] = useState("");
  const profileMenuRef = useRef<HTMLDivElement>(null);
  const firstMenuItemRef = useRef<HTMLButtonElement>(null);
  const location = useLocation();
  const health = useQuery({ queryKey: ["health"], queryFn: getHealth, refetchInterval: 30_000 });
  const page = headings[location.pathname] ?? headings["/"];

  useEffect(() => {
    if (profileMenuOpen) firstMenuItemRef.current?.focus();
  }, [profileMenuOpen]);

  useEffect(() => {
    if (!profileMenuOpen && !demoInfoOpen) return;
    const handlePointerDown = (event: PointerEvent) => {
      if (profileMenuRef.current && !profileMenuRef.current.contains(event.target as Node)) {
        setProfileMenuOpen(false);
      }
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setProfileMenuOpen(false);
        setDemoInfoOpen(false);
      }
    };
    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [profileMenuOpen, demoInfoOpen]);

  async function copyPageLink() {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setMenuNotice("Page link copied.");
    } catch {
      setMenuNotice("Clipboard unavailable. Copy the address from your browser.");
    }
  }

  async function recheckConnection() {
    const result = await health.refetch();
    setMenuNotice(result.isError ? "API is offline." : "API connection is healthy.");
  }

  return (
    <div className="app-frame">
      {menuOpen && <button className="mobile-scrim" onClick={() => setMenuOpen(false)} aria-label="Close navigation" />}
      <aside className={`sidebar ${menuOpen ? "sidebar-open" : ""}`}>
        <div className="brand-lockup">
          <div className="brand-mark"><span>F</span></div>
          <div><strong>FIELDWORK</strong><small>OPERATIONS CO-PILOT</small></div>
          <button className="icon-button sidebar-close" onClick={() => setMenuOpen(false)} aria-label="Close navigation"><X size={18} /></button>
        </div>
        <div
          className="workspace-label"
          aria-label="Current workspace: Factory workspace. Switching workspaces is not available in this demo."
          title="Only one demo workspace is configured"
        >
          <span className="workspace-dot" />
          <span>Factory workspace</span>
          <span className="workspace-mode">DEMO</span>
        </div>
        <div className="nav-caption">WORKSPACE</div>
        <nav className="primary-nav" aria-label="Main navigation">
          {navigation.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`} onClick={() => setMenuOpen(false)}>
              <Icon size={18} strokeWidth={1.8} aria-hidden="true" />
              <span>{label}</span>            </NavLink>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="sidebar-rule" />
          <div className="privacy-note"><ShieldCheck size={16} /><span>Track 1 course dataset<br /><small>No external actions enabled</small></span></div>
          <div className="user-stub">
            <div className="avatar">GM</div>
            <div><strong>Workspace user</strong><small>Local demo</small></div>
            <div className="user-menu-wrap" ref={profileMenuRef}>
              <button
                className="user-menu-button"
                type="button"
                aria-label="Workspace user options"
                aria-haspopup="menu"
                aria-expanded={profileMenuOpen}
                title="Workspace user options"
                onClick={() => {
                  setMenuNotice("");
                  setProfileMenuOpen((open) => !open);
                }}
              >
                <MoreHorizontal size={19} />
              </button>
              {profileMenuOpen && (
                <div className="profile-menu" role="menu" aria-label="Workspace user options">
                  <button ref={firstMenuItemRef} type="button" role="menuitem" onClick={copyPageLink}>
                    <Link2 size={15} /> Copy this page link
                  </button>
                  <button type="button" role="menuitem" onClick={recheckConnection}>
                    <RefreshCw size={15} className={health.isFetching ? "spin" : ""} /> Check API connection
                  </button>
                  <div className="profile-menu-divider" />
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => {
                      setProfileMenuOpen(false);
                      setDemoInfoOpen(true);
                    }}
                  >
                    <Info size={15} /> About this demo
                  </button>
                  {menuNotice && <p className="profile-menu-notice" role="status">{menuNotice}</p>}
                </div>
              )}
            </div>
          </div>
        </div>
      </aside>

      <main className="main-column">
        <header className="topbar">
          <button className="icon-button mobile-menu" onClick={() => setMenuOpen(true)} aria-label="Open navigation"><Menu size={20} /></button>
          <div className="topbar-title"><span>{page.kicker}</span><h1>{page.title}</h1></div>
          <div className="topbar-meta">
            <div className={`connection-pill ${health.isError ? "offline" : ""}`}>
              <span className="connection-dot" />
              {health.isLoading ? "Connecting" : health.isError ? "API offline" : "API connected"}
            </div>
            <div className="demo-tag"><span>TRACK 1</span> COURSE DATASET</div>
          </div>
        </header>
        <div className="page-content">{children}</div>
        <footer className="app-footer"><span>FIELDWORK OPERATIONS</span><span>Decision support · not a delivery guarantee</span></footer>
      </main>
      {demoInfoOpen && (
        <div className="dialog-scrim" onMouseDown={(event) => event.target === event.currentTarget && setDemoInfoOpen(false)}>
          <section className="demo-info-dialog" role="dialog" aria-modal="true" aria-labelledby="demo-info-title">
            <div className="dialog-heading">
              <div><span className="eyebrow">WORKSPACE DETAILS</span><h2 id="demo-info-title">Factory workspace</h2></div>
              <button className="icon-button" onClick={() => setDemoInfoOpen(false)} aria-label="Close demo information"><X size={18} /></button>
            </div>
            <div className="demo-info-body">
              <div className="demo-info-row"><span>Dataset</span><strong>Track 1 course dataset</strong></div>
              <div className="demo-info-row"><span>Workspace</span><strong>Factory workspace</strong></div>
              <div className="demo-info-row"><span>API status</span><strong className={health.isError ? "info-offline" : "info-online"}>{health.isError ? "Offline" : health.isLoading ? "Checking" : "Connected"}</strong></div>
              <p>This demo has one fixed workspace. Sign-in, user profiles and workspace switching are not configured. Actions are recorded locally and are not sent externally.</p>
            </div>
            <div className="dialog-actions"><button className="button button-primary" onClick={() => setDemoInfoOpen(false)}>Done</button></div>
          </section>
        </div>
      )}
    </div>
  );
}