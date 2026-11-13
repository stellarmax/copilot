import { type FormEvent, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Link, Navigate, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { ArrowLeft, KeyRound, LogIn, UserPlus } from "lucide-react";
import { ErrorState } from "../components/Feedback";
import { register, signIn, type User } from "../lib/api";

export function SignInPage({ signedIn, onSignedIn }: { signedIn: boolean; onSignedIn: (user: User) => void }) {
  const [params] = useSearchParams();
  // Set while a successful sign-in is navigating away, so the redirect below cannot override it.
  const leaving = useRef(false);
  const navigate = useNavigate();
  // The page the visitor came from, so signing in takes them straight back to it.
  const from = (useLocation().state as { from?: string } | null)?.from ?? "/";
  const [mode, setMode] = useState<"sign-in" | "register">(params.get("mode") === "register" ? "register" : "sign-in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const submit = useMutation({
    mutationFn: () => mode === "sign-in"
      ? signIn({ email, password })
      : register({ email, password, display_name: displayName }),
    onSuccess: (user) => {
      leaving.current = true;
      // A new account has no AI key yet: start on AI settings with a welcome note.
      if (mode === "register") navigate("/settings", { replace: true, state: { welcome: true } });
      else navigate(from, { replace: true });
      onSignedIn(user);
    },
  });
  const registering = mode === "register";

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    submit.mutate();
  }

  function switchMode() {
    submit.reset();
    setMode(registering ? "sign-in" : "register");
  }

  if (signedIn && !leaving.current) return <Navigate to="/" replace />;

  return (
    <div className="auth-page">
      <section className="auth-card panel">
        <Link className="auth-back text-link" to={from}><ArrowLeft size={14} /> Back to the workspace</Link>
        <div className="auth-brand">
          <div className="brand-mark"><span>F</span></div>
          <div><strong>FIELDWORK</strong><small>OPERATIONS CO-PILOT</small></div>
        </div>
        <span className="eyebrow">{registering ? "NEW ACCOUNT" : "WELCOME BACK"}</span>
        <h1>{registering ? "Create your account" : "Sign in"}</h1>
        <form className="auth-form" onSubmit={handleSubmit}>
          <label>E-mail
            <input type="email" required autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} />
          </label>
          {registering && (
            <label>Name <small>optional</small>
              <input maxLength={60} autoComplete="name" value={displayName} onChange={(event) => setDisplayName(event.target.value)} />
            </label>
          )}
          <label>Password
            <input
              type="password"
              required
              minLength={registering ? 8 : undefined}
              autoComplete={registering ? "new-password" : "current-password"}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>
          {submit.error && <ErrorState message={submit.error.message} />}
          <button className="button button-primary button-wide" type="submit" disabled={submit.isPending}>
            {registering ? <UserPlus size={15} /> : <LogIn size={15} />}
            {submit.isPending ? "Please wait" : registering ? "Create account" : "Sign in"}
          </button>
        </form>
        <p className="auth-switch">
          {registering ? "Already have an account?" : "New to the team workspace?"}{" "}
          <button className="text-button" type="button" onClick={switchMode}>{registering ? "Sign in" : "Create an account"}</button>
        </p>
        <p className="auth-footnote"><KeyRound size={14} /> Each account uses its own AI provider key, chats, reminders and action log.</p>
      </section>
    </div>
  );
}
