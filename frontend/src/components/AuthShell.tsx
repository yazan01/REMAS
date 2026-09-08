"use client";

import type { ReactNode } from "react";

export function AuthShell({
  title,
  body,
  children,
}: {
  title: string;
  body: string;
  children: ReactNode;
}) {
  return (
    <div className="shell" style={{ paddingBlock: "var(--space-8)" }}>
      <div className="shell-narrow stack stack-5">
        <div className="stack stack-2">
          <h1 style={{ fontSize: "var(--text-2xl)", fontWeight: 600 }}>{title}</h1>
          <p className="muted" style={{ fontSize: "var(--text-sm)" }}>
            {body}
          </p>
        </div>
        <div className="card card-pad card-raised">{children}</div>
      </div>
    </div>
  );
}

export function ErrorNote({ text }: { text: string }) {
  return (
    <p role="alert" className="note note-error">
      {text}
    </p>
  );
}

export function InfoNote({ children }: { children: ReactNode }) {
  return <div className="note note-info">{children}</div>;
}

export function Loading({ label }: { label: string }) {
  return (
    <div className="shell dim" style={{ paddingBlock: "var(--space-8)" }}>
      {label}
    </div>
  );
}
