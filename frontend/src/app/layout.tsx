import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Academic Agent Platform",
  description: "学术辅助平台 — Assessment · Outline · NotebookLM · Zotero · APA 7th",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
