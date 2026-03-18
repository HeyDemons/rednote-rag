import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Rednote Atlas - 小红书知识库",
  description: "把小红书点赞和收藏变成可检索、可追溯来源的个人知识库",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
