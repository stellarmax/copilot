import { AlertCircle, LoaderCircle, LockKeyhole, LogIn } from "lucide-react";
import { Link, useLocation } from "react-router-dom";
import { SIGN_IN_MESSAGE } from "../lib/api";

export function LoadingState({ label = "Loading data" }: { label?: string }) {
  return (
    <div className="feedback-line" role="status">
      <LoaderCircle size={16} className="spin" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

/** Shown instead of data while signed out: neutral, with a way to sign in and come back here. */
export function SignInNotice({ message = SIGN_IN_MESSAGE }: { message?: string }) {
  const location = useLocation();
  return (
    <div className="sign-in-notice" role="status">
      <LockKeyhole size={16} aria-hidden="true" />
      <span>{message}</span>
      <Link className="button button-primary button-small" to="/signin" state={{ from: location.pathname }}><LogIn size={14} /> Sign in</Link>
    </div>
  );
}

export function ErrorState({ message }: { message: string }) {
  if (message === SIGN_IN_MESSAGE) return <SignInNotice />;
  return (
    <div className="error-state" role="alert">
      <AlertCircle size={17} aria-hidden="true" />
      <span>{message}</span>
    </div>
  );
}

export function InlineError({ error }: { error: unknown }) {
  if (!error) return null;
  return <ErrorState message={error instanceof Error ? error.message : "Something went wrong."} />;
}