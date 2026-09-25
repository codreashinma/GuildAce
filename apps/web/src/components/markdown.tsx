"use client";

import ReactMarkdown from "react-markdown";

export function Markdown({ children }: { children: string }) {
  return (
    <div className="prose-md text-sm text-slate-800">
      <ReactMarkdown>{children}</ReactMarkdown>
    </div>
  );
}
