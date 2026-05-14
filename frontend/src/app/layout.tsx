import type { Metadata } from "next";
import localFont from "next/font/local";
import Script from "next/script";
import "./globals.css";
import { Providers } from "@/components/ui/providers";

const inter = localFont({
  src: [
    {
      path: "./fonts/InterVariable.woff2",
      style: "normal",
      weight: "100 900",
    },
    {
      path: "./fonts/InterVariable-Italic.woff2",
      style: "italic",
      weight: "100 900",
    },
  ],
  display: "swap",
  variable: "--font-inter",
});

export const metadata: Metadata = {
  title: process.env.NEXT_PUBLIC_APP_NAME || "MinerU",
  description: "Document parsing platform powered by MinerU",
  icons: {
    icon: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <head>
        <Script src="/browser-polyfills.js" strategy="beforeInteractive" />
        <Script src="/runtime-config.js" strategy="beforeInteractive" />
      </head>
      <body className={inter.className}>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
