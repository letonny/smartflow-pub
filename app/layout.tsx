import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "SmartFlow | Spatial Traffic Intelligence",
  description: "Explore traffic observations, spatial congestion, and travel time predictions in SmartFlow.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
