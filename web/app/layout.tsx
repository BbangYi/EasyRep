import type { Metadata } from "next";
import "./globals.css";
import "./forest-scene.css";
import "./dashboard-layout.css";
import "./account-management.css";

export const metadata: Metadata = {
  title: "EasyRep · 사육장 대시보드",
  description:
    "여러 사육장의 사진, 카메라 예시, 센서 실측과 장치 상태를 확인하는 EasyRep 데모 워크스페이스.",
  icons: {
    icon: "/brand/easyrep-app-icon.webp",
    shortcut: "/brand/easyrep-app-icon.webp",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko">
      <body className="antialiased forest-scene">{children}</body>
    </html>
  );
}
